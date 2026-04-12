"""MCP server for oh-my-council.

Exposes tools (omc_status, ...) and prompt templates over stdio.
The `_*_impl` helpers are pure functions for unit testing without
the MCP transport.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from omc.models import Project, ProjectStatus
from omc.store.index import IndexStore
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _default_docs_root() -> Path:
    return Path.cwd() / "docs"


def _omc_status_impl(*, docs_root: Path, project_id: str) -> dict:
    project_root = docs_root / "projects" / project_id
    if not project_root.exists():
        return {"error": f"project not found: {project_id}"}
    store = ProjectStore(project_root / "council.sqlite3")
    tasks = [
        {
            "id": t.id,
            "status": t.status.name,
            "attempts": t.attempts,
            "tokens_used": t.tokens_used,
        }
        for t in store.list_tasks()
    ]
    return {"project_id": project_id, "tasks": tasks}


def _omc_new_impl(*, docs_root: Path, slug: str) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    project_id = f"{today}-{slug}"
    project_root = docs_root / "projects" / project_id
    idx = IndexStore(docs_root / "index.sqlite3")
    now = datetime.now()
    idx.upsert_project(Project(
        id=project_id, title=slug, status=ProjectStatus.PLANNING,
        root_path=str(project_root), created_at=now, updated_at=now,
    ))
    MDLayout(project_root).scaffold()
    ProjectStore(project_root / "council.sqlite3")
    MDLayout(project_root).write_requirement(f"# {slug}\n\n(fill in the requirement)\n")
    return {"project_id": project_id, "root": str(project_root)}


def _omc_start_impl(*, docs_root: Path, project_id: str, task_id: str) -> dict:
    from omc.budget import BudgetTracker, Limits
    from omc.clients.fake_auditor import FakeAuditor
    from omc.clients.fake_codex import FakeCodexClient
    from omc.clients.fake_worker import FakeWorkerRunner
    from omc.dispatcher import Dispatcher, DispatcherDeps

    project_root = docs_root / "projects" / project_id
    if not project_root.exists():
        return {"error": f"project not found: {project_id}"}
    md = MDLayout(project_root)
    store = ProjectStore(project_root / "council.sqlite3")
    if store.get_task(task_id) is None:
        return {"error": f"task not found: {task_id}"}
    workspace = project_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    deps = DispatcherDeps(
        store=store, md=md,
        codex=FakeCodexClient(), worker=FakeWorkerRunner(), auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=workspace,
    )
    Dispatcher(deps).run_once(task_id, requirement=md.read_requirement())
    got = store.get_task(task_id)
    return {"task_id": task_id, "status": got.status.name if got else "MISSING"}


def _find_project_dir(docs_root: Path, slug: str) -> Path | None:
    """Find project directory matching pattern YYYY-MM-DD-<slug>."""
    projects_dir = docs_root / "projects"
    if not projects_dir.exists():
        return None
    for d in projects_dir.iterdir():
        if d.is_dir() and d.name.endswith(f"-{slug}"):
            return d
    return None


def _project_from_dir(store: ProjectStore, project_dir: Path) -> Project | None:
    """Get project info from a directory by extracting from directory name."""
    # Extract project_id from directory name (format: YYYY-MM-DD-<slug>)
    project_id = project_dir.name
    # Extract title/slug from project_id
    parts = project_id.rsplit("-", 3)
    slug = parts[-1] if len(parts) >= 2 else project_id
    # Create a minimal Project object (we don't need to query the store)
    return Project(
        id=project_id,
        title=slug,
        status=ProjectStatus.PLANNING,
        root_path=str(project_dir),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _omc_budget_impl(docs_root: Path, slug: str) -> dict:
    from omc.budget import Limits

    pdir = _find_project_dir(docs_root, slug)
    if pdir is None:
        return {"error": f"project {slug!r} not found"}
    store = ProjectStore(pdir / "council.sqlite3")
    project = _project_from_dir(store, pdir)
    if project is None:
        return {"error": f"project {slug!r} not found"}
    return {
        "slug": project.title,
        "project_id": project.id,
        "spend_usd": round(store.project_cost_usd(project.id), 6),
        "limit_usd": Limits().l4_project_usd,
        "remaining_usd": round(
            max(0.0, Limits().l4_project_usd - store.project_cost_usd(project.id)), 6
        ),
        "by_agent": {
            k: round(v, 6) for k, v in store.cost_breakdown_by_agent(project.id).items()
        },
    }


def _omc_verify_impl(*, docs_root: Path, project_id: str) -> dict:
    project_root = docs_root / "projects" / project_id
    if not project_root.exists():
        return {"error": f"project not found: {project_id}"}
    md = MDLayout(project_root)
    store = ProjectStore(project_root / "council.sqlite3")
    tasks = [
        {"id": t.id, "status": t.status.name, "attempts": t.attempts}
        for t in store.list_tasks()
    ]
    return {
        "project_id": project_id,
        "requirement": md.read_requirement(),
        "tasks": tasks,
        "hint": (
            "Decide ACCEPT / NEED_DETAIL / REJECT based on requirement vs "
            "task statuses. Use the `omc verify` CLI if you want a "
            "subprocess-Claude second opinion."
        ),
    }


def build_server(docs_root: Path | None = None) -> FastMCP:
    root = docs_root or _default_docs_root()
    app = FastMCP("oh-my-council")

    @app.tool()
    def omc_status(project_id: str) -> dict:
        """Return the task list + status for a project_id."""
        return _omc_status_impl(docs_root=root, project_id=project_id)

    @app.tool()
    def omc_new(slug: str) -> dict:
        """Create a new oh-my-council project under docs/projects/."""
        return _omc_new_impl(docs_root=root, slug=slug)

    @app.tool()
    def omc_start(project_id: str, task_id: str) -> dict:
        """Run a task through the fake pipeline for smoke testing."""
        return _omc_start_impl(docs_root=root, project_id=project_id, task_id=task_id)

    @app.tool()
    def omc_verify(project_id: str) -> dict:
        """Return project summary so the current Claude session can render a
        milestone verdict (ACCEPT / NEED_DETAIL / REJECT)."""
        return _omc_verify_impl(docs_root=root, project_id=project_id)

    @app.tool()
    def omc_budget(slug: str) -> dict:
        """Return project USD spend vs L4 limit + per-agent breakdown."""
        return _omc_budget_impl(root, slug)

    @app.prompt(name="omc_new")
    def _prompt_omc_new(slug: str) -> str:
        """Start a new oh-my-council project."""
        return (f"Call the `omc_new` tool with slug=`{slug}`. "
                f"Then open `docs/projects/<id>/requirement.md` for the user to edit.")

    @app.prompt(name="omc_plan")
    def _prompt_omc_plan() -> str:
        """(Phase 3b) Trigger Codex to produce task specs from requirement.md."""
        return "Not yet implemented — scheduled for Phase 3b (CCB bridge)."

    @app.prompt(name="omc_start")
    def _prompt_omc_start(project_id: str, task_id: str) -> str:
        """Run a task through the fake pipeline."""
        return f"Call `omc_start` with project_id=`{project_id}` task_id=`{task_id}`."

    @app.prompt(name="omc_verify")
    def omc_verify_prompt(project_id: str) -> str:
        """Milestone verify."""
        return (
            f"Call the `omc_verify` tool with project_id=`{project_id}`. "
            f"Read the requirement + task list it returns, decide ACCEPT / "
            f"NEED_DETAIL / REJECT, and explain briefly. For a subprocess "
            f"second opinion, suggest running `omc verify {project_id}`."
        )

    @app.prompt(name="omc_status")
    def _prompt_omc_status(project_id: str) -> str:
        """Summarize task statuses for a project."""
        return f"Call `omc_status` with project_id=`{project_id}` and summarize the output."

    @app.prompt(name="omc_tmux")
    def _prompt_omc_tmux(project_id: str) -> str:
        """Launch the observer panel."""
        return f"In a shell, run: `omc tmux {project_id}`."

    @app.prompt(name="omc_budget")
    def _prompt_omc_budget(slug: str) -> str:
        return (
            f"Show me the current USD spend for project {slug!r}. "
            f"Call the omc_budget tool with slug={slug!r} and report "
            f"spend, limit, remaining, and per-agent breakdown."
        )

    return app


def run_stdio(docs_root: Path | None = None) -> None:
    """Blocking: run the FastMCP server over stdio."""
    build_server(docs_root).run(transport="stdio")
