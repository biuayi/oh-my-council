"""Unit tests for the oh-my-council MCP server tools."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from omc.mcp_server import _omc_status_impl
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def test_status_returns_task_list(tmp_path: Path):
    docs = tmp_path / "docs"
    project_root = docs / "projects" / "p1"
    MDLayout(project_root).scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime(2026, 4, 12)
    store.upsert_task(Task(
        id="T1", project_id="p1", md_path="tasks/T1.md",
        status=TaskStatus.PENDING, path_whitelist=["src/generated/T1.py"],
        created_at=now, updated_at=now,
    ))

    result = _omc_status_impl(docs_root=docs, project_id="p1")
    assert result["project_id"] == "p1"
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["id"] == "T1"
    assert result["tasks"][0]["status"] == "PENDING"


def test_status_missing_project(tmp_path: Path):
    result = _omc_status_impl(docs_root=tmp_path / "docs", project_id="nope")
    assert result == {"error": "project not found: nope"}
