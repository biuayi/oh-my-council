from datetime import datetime
from pathlib import Path

from omc.models import Project, ProjectStatus
from omc.store.index import IndexStore


def test_upsert_and_list(tmp_docs: Path):
    store = IndexStore(tmp_docs / "index.sqlite3")
    now = datetime(2026, 4, 12, 0, 0, 0)
    p = Project(
        id="2026-04-12-alpha",
        title="alpha",
        status=ProjectStatus.PLANNING,
        root_path="docs/projects/2026-04-12-alpha",
        created_at=now,
        updated_at=now,
    )
    store.upsert_project(p)

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0].id == "2026-04-12-alpha"
    assert projects[0].status is ProjectStatus.PLANNING


def test_upsert_replaces_existing(tmp_docs: Path):
    store = IndexStore(tmp_docs / "index.sqlite3")
    now = datetime(2026, 4, 12, 0, 0, 0)
    p = Project(
        id="x",
        title="x",
        status=ProjectStatus.PLANNING,
        root_path="r",
        created_at=now,
        updated_at=now,
    )
    store.upsert_project(p)

    p.status = ProjectStatus.RUNNING
    store.upsert_project(p)

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0].status is ProjectStatus.RUNNING
