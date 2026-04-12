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


def test_new_creates_project(tmp_path: Path):
    from omc.mcp_server import _omc_new_impl
    docs = tmp_path / "docs"
    result = _omc_new_impl(docs_root=docs, slug="demo")
    assert "project_id" in result
    pid = result["project_id"]
    assert (docs / "projects" / pid / "council.sqlite3").exists()


def test_start_runs_fake_pipeline(tmp_path: Path):
    from omc.mcp_server import _omc_new_impl, _omc_start_impl
    docs = tmp_path / "docs"
    new_result = _omc_new_impl(docs_root=docs, slug="demo")
    pid = new_result["project_id"]

    from omc.models import Task, TaskStatus
    from omc.store.project import ProjectStore
    now = datetime(2026, 4, 12)
    store = ProjectStore(docs / "projects" / pid / "council.sqlite3")
    store.upsert_task(Task(
        id="T1", project_id=pid, md_path="tasks/T1.md",
        status=TaskStatus.PENDING,
        path_whitelist=["src/generated/T1.py"],
        created_at=now, updated_at=now,
    ))

    result = _omc_start_impl(docs_root=docs, project_id=pid, task_id="T1")
    assert result["task_id"] == "T1"
    assert result["status"] in ("ACCEPTED", "BLOCKED")


def test_start_missing_project(tmp_path: Path):
    from omc.mcp_server import _omc_start_impl
    result = _omc_start_impl(docs_root=tmp_path / "docs", project_id="nope", task_id="T1")
    assert "error" in result


def test_server_registers_six_prompts():
    import asyncio

    from omc.mcp_server import build_server

    app = build_server()
    prompts = asyncio.run(app.list_prompts())
    names = {p.name for p in prompts}
    # FastMCP may keep underscores in prompt names; accept either form
    expected_dashed = {"omc-new", "omc-plan", "omc-start",
                       "omc-verify", "omc-status", "omc-tmux"}
    expected_underscored = {"omc_new", "omc_plan", "omc_start",
                            "omc_verify", "omc_status", "omc_tmux"}
    assert expected_dashed <= names or expected_underscored <= names, (
        f"missing prompts; got {names}"
    )
