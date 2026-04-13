"""Cover the network-free MCP tools added in the plan/stats/task-add wave."""
from datetime import datetime
from pathlib import Path

from omc.mcp_server import (
    _omc_stats_impl,
    _omc_task_add_impl,
)
from omc.models import Project, ProjectStatus, Task, TaskStatus
from omc.store.index import IndexStore
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def test_task_add_missing_project(tmp_path: Path):
    r = _omc_task_add_impl(
        docs_root=tmp_path / "docs",
        project_id="does-not-exist",
        task_id="T1",
        path_whitelist=[],
    )
    assert "error" in r
    assert "not found" in r["error"]


def test_task_add_seeds_and_refuses_duplicate(tmp_path: Path):
    docs = tmp_path / "docs"
    pid = "p1"
    project_root = docs / "projects" / pid
    MDLayout(project_root).scaffold()
    ProjectStore(project_root / "council.sqlite3")

    r1 = _omc_task_add_impl(
        docs_root=docs, project_id=pid, task_id="T001",
        path_whitelist=["src/a.py"],
    )
    assert r1["task_id"] == "T001"
    assert r1["path_whitelist"] == ["src/a.py"]

    # Collision without force is refused
    r2 = _omc_task_add_impl(
        docs_root=docs, project_id=pid, task_id="T001",
        path_whitelist=["src/b.py"],
    )
    assert "error" in r2
    assert "already exists" in r2["error"]

    # With force it overwrites
    r3 = _omc_task_add_impl(
        docs_root=docs, project_id=pid, task_id="T001",
        path_whitelist=["src/c.py"], force=True,
    )
    assert r3["path_whitelist"] == ["src/c.py"]


def test_stats_empty_docs_root(tmp_path: Path):
    r = _omc_stats_impl(docs_root=tmp_path / "docs")
    assert r["projects"] == []
    assert r["total_cost_usd"] == 0.0
    assert r["totals"] == {"pending": 0, "running": 0, "done": 0, "blocked": 0}


def test_stats_aggregates_across_projects(tmp_path: Path):
    docs = tmp_path / "docs"
    idx = IndexStore(docs / "index.sqlite3")
    now = datetime.now()

    for pid, statuses in [
        ("p-a", [TaskStatus.PENDING, TaskStatus.ACCEPTED]),
        ("p-b", [TaskStatus.BLOCKED]),
    ]:
        project_root = docs / "projects" / pid
        MDLayout(project_root).scaffold()
        idx.upsert_project(Project(
            id=pid, title=pid, status=ProjectStatus.PLANNING,
            root_path=str(project_root), created_at=now, updated_at=now,
        ))
        ps = ProjectStore(project_root / "council.sqlite3")
        for i, s in enumerate(statuses, start=1):
            ps.upsert_task(Task(
                id=f"T{i:03d}", project_id=pid, md_path=f"tasks/T{i:03d}.md",
                status=s, path_whitelist=[], created_at=now, updated_at=now,
            ))

    r = _omc_stats_impl(docs_root=docs)
    assert r["totals"]["pending"] == 1
    assert r["totals"]["done"] == 1
    assert r["totals"]["blocked"] == 1
    pids = {row["project_id"] for row in r["projects"]}
    assert pids == {"p-a", "p-b"}
