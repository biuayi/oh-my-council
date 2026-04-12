"""MCP server for oh-my-council.

Exposes tools (omc_status, ...) and prompt templates over stdio.
The `_*_impl` helpers are pure functions for unit testing without
the MCP transport.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

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


def build_server(docs_root: Path | None = None) -> FastMCP:
    root = docs_root or _default_docs_root()
    app = FastMCP("oh-my-council")

    @app.tool()
    def omc_status(project_id: str) -> dict:
        """Return the task list + status for a project_id."""
        return _omc_status_impl(docs_root=root, project_id=project_id)

    return app


def run_stdio(docs_root: Path | None = None) -> None:
    """Blocking: run the FastMCP server over stdio."""
    build_server(docs_root).run(transport="stdio")
