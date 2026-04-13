"""MCP server for oh-my-council.

Exposes tools (omc_status, ...) and prompt templates over stdio.
The `_*_impl` helpers are pure functions for unit testing without
the MCP transport.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from omc.models import Project, ProjectStatus, Task, TaskStatus
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


def _omc_plan_impl(*, docs_root: Path, project_id: str, force: bool = False) -> dict:
    from omc.clients.codex_cli import CodexCLI
    from omc.clients.real_codex import RealCodexClient
    from omc.config import load_settings

    project_root = docs_root / "projects" / project_id
    if not project_root.exists():
        return {"error": f"project not found: {project_id}"}
    md = MDLayout(project_root)
    requirement = md.read_requirement()
    if not requirement.strip():
        return {"error": "requirement.md is empty — write it first"}

    settings = load_settings()
    codex = RealCodexClient(
        cli=CodexCLI(
            bin=settings.codex_bin,
            timeout_s=settings.codex_timeout_s,
            reasoning_effort=settings.codex_reasoning_effort,
        ),
        workspace_root=project_root / "workspace",
    )
    tasks = codex.produce_plan(requirement)
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime.now()
    seeded: list[str] = []
    skipped: list[str] = []
    for t in tasks:
        tid = t["task_id"]
        if store.get_task(tid) is not None and not force:
            skipped.append(tid)
            continue
        store.upsert_task(
            Task(
                id=tid, project_id=project_id,
                md_path=f"tasks/{tid}.md",
                status=TaskStatus.PENDING,
                path_whitelist=t["path_whitelist"],
                created_at=now, updated_at=now,
            )
        )
        seeded.append(tid)
    return {"project_id": project_id, "seeded": seeded, "skipped": skipped, "tasks": tasks}


def _omc_task_add_impl(
    *, docs_root: Path, project_id: str, task_id: str,
    path_whitelist: list[str], force: bool = False,
) -> dict:
    project_root = docs_root / "projects" / project_id
    if not project_root.exists():
        return {"error": f"project not found: {project_id}"}
    store = ProjectStore(project_root / "council.sqlite3")
    if store.get_task(task_id) is not None and not force:
        return {"error": f"task {task_id} already exists (pass force=true to overwrite)"}
    now = datetime.now()
    store.upsert_task(
        Task(
            id=task_id, project_id=project_id,
            md_path=f"tasks/{task_id}.md",
            status=TaskStatus.PENDING,
            path_whitelist=list(path_whitelist),
            created_at=now, updated_at=now,
        )
    )
    return {"task_id": task_id, "project_id": project_id, "path_whitelist": list(path_whitelist)}


def _omc_run_impl(*, docs_root: Path, project_id: str, task_id: str) -> dict:
    """Run a task through the REAL pipeline (spec → write → review → audit)."""
    from omc.budget import BudgetTracker, Limits
    from omc.clients.codex_cli import CodexCLI
    from omc.clients.real_auditor import LiteLLMAuditor
    from omc.clients.real_codex import RealCodexClient
    from omc.clients.real_worker import LiteLLMWorker
    from omc.config import load_settings
    from omc.dispatcher import Dispatcher, DispatcherDeps
    from omc.notify import Notifier

    project_root = docs_root / "projects" / project_id
    if not project_root.exists():
        return {"error": f"project not found: {project_id}"}
    md = MDLayout(project_root)
    store = ProjectStore(project_root / "council.sqlite3")
    if store.get_task(task_id) is None:
        return {"error": f"task not found: {task_id}"}

    settings = load_settings()
    workspace = project_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    deps = DispatcherDeps(
        store=store, md=md,
        codex=RealCodexClient(
            cli=CodexCLI(
                bin=settings.codex_bin,
                timeout_s=settings.codex_timeout_s,
                reasoning_effort=settings.codex_reasoning_effort,
            ),
            workspace_root=workspace,
        ),
        worker=LiteLLMWorker(settings),
        auditor=LiteLLMAuditor(settings),
        budget=BudgetTracker(Limits(), project_id=project_id, notifier=Notifier()),
        project_source_root=workspace,
        notifier=Notifier(),
    )
    Dispatcher(deps).run_once(task_id, requirement=md.read_requirement())
    got = store.get_task(task_id)
    return {
        "task_id": task_id,
        "status": got.status.name if got else "MISSING",
        "attempts": got.attempts if got else 0,
        "tokens_used": got.tokens_used if got else 0,
        "cost_usd": round(store.task_cost_usd(task_id), 6),
    }


def _omc_stats_impl(*, docs_root: Path) -> dict:
    idx = IndexStore(docs_root / "index.sqlite3")
    projects = idx.list_projects()
    rows: list[dict] = []
    total_cost = 0.0
    totals = {"pending": 0, "running": 0, "done": 0, "blocked": 0}
    for p in projects:
        db = docs_root / "projects" / p.id / "council.sqlite3"
        if not db.exists():
            rows.append({"project_id": p.id, "status": p.status.value, "cost_usd": 0.0})
            continue
        ps = ProjectStore(db)
        cost = ps.project_cost_usd(p.id)
        total_cost += cost
        counts = {"pending": 0, "running": 0, "done": 0, "blocked": 0}
        for t in ps.list_tasks():
            s = t.status.value
            if s in ("pending", "running"):
                counts[s] += 1
            elif s in ("accepted", "audit_passed", "review_passed"):
                counts["done"] += 1
            else:
                counts["blocked"] += 1
        for k, v in counts.items():
            totals[k] += v
        rows.append({
            "project_id": p.id, "status": p.status.value,
            "tasks": counts, "cost_usd": round(cost, 6),
        })
    return {"projects": rows, "totals": totals, "total_cost_usd": round(total_cost, 6)}


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

    @app.tool()
    def omc_plan(project_id: str, force: bool = False) -> dict:
        """Decompose requirement.md into tasks via Codex; seed them PENDING."""
        return _omc_plan_impl(docs_root=root, project_id=project_id, force=force)

    @app.tool()
    def omc_task_add(
        project_id: str, task_id: str, path_whitelist: list[str],
        force: bool = False,
    ) -> dict:
        """Manually seed a PENDING task with an explicit path_whitelist."""
        return _omc_task_add_impl(
            docs_root=root, project_id=project_id, task_id=task_id,
            path_whitelist=path_whitelist, force=force,
        )

    @app.tool()
    def omc_run(project_id: str, task_id: str) -> dict:
        """Run a task through the REAL pipeline (spec → write → review → audit).
        Uses the provider chain from Settings (primary → fallback)."""
        return _omc_run_impl(docs_root=root, project_id=project_id, task_id=task_id)

    @app.tool()
    def omc_stats() -> dict:
        """Cross-project rollup: per-project task-state counts + USD spend."""
        return _omc_stats_impl(docs_root=root)

    @app.prompt(name="omc_new")
    def _prompt_omc_new(slug: str) -> str:
        """Start a new oh-my-council project."""
        return (f"Call the `omc_new` tool with slug=`{slug}`. "
                f"Then open `docs/projects/<id>/requirement.md` for the user to edit.")

    @app.prompt(name="omc_plan")
    def _prompt_omc_plan(project_id: str) -> str:
        """Trigger Codex to decompose requirement.md into PENDING tasks."""
        return (
            f"Call the `omc_plan` tool with project_id=`{project_id}`. "
            f"Then call `omc_status` to list the seeded tasks, and suggest "
            f"running `omc_run` per task_id to execute the pipeline."
        )

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
