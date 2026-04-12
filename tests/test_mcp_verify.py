"""Unit tests for MCP omc_verify tool."""

from datetime import datetime
from pathlib import Path

from omc.mcp_server import _omc_verify_impl
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def test_verify_impl_returns_summary(tmp_path: Path):
    docs = tmp_path / "docs"
    project_root = docs / "projects" / "p1"
    MDLayout(project_root).scaffold()
    MDLayout(project_root).write_requirement("# greet\n\nImplement greet(name).")
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime(2026, 4, 12)
    store.upsert_task(Task(
        id="T1", project_id="p1", md_path="tasks/T1.md",
        status=TaskStatus.ACCEPTED, path_whitelist=["src/generated/g.py"],
        created_at=now, updated_at=now,
    ))
    result = _omc_verify_impl(docs_root=docs, project_id="p1")
    assert result["project_id"] == "p1"
    assert "greet(name)" in result["requirement"]
    assert any(t["id"] == "T1" for t in result["tasks"])


def test_verify_impl_missing_project(tmp_path: Path):
    result = _omc_verify_impl(docs_root=tmp_path / "docs", project_id="nope")
    assert "error" in result
