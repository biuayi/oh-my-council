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

    return app


def run_stdio(docs_root: Path | None = None) -> None:
    """Blocking: run the FastMCP server over stdio."""
    build_server(docs_root).run(transport="stdio")
