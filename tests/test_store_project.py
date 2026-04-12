import json
from pathlib import Path

from omc.models import Interaction, Task, TaskStatus
from omc.store.project import ProjectStore


def _make_store(tmp_docs: Path) -> ProjectStore:
    return ProjectStore(tmp_docs / "projects" / "p1" / "council.sqlite3")


def test_upsert_and_get_task(tmp_docs: Path):
    store = _make_store(tmp_docs)
    t = Task(
        id="T001",
        project_id="p1",
        md_path="tasks/T001.md",
        status=TaskStatus.PENDING,
        path_whitelist=["src/a.py"],
    )
    store.upsert_task(t)

    got = store.get_task("T001")
    assert got is not None
    assert got.id == "T001"
    assert got.status is TaskStatus.PENDING
    assert got.path_whitelist == ["src/a.py"]


def test_list_tasks_by_status(tmp_docs: Path):
    store = _make_store(tmp_docs)
    for i, status in enumerate([TaskStatus.PENDING, TaskStatus.PENDING, TaskStatus.ACCEPTED]):
        store.upsert_task(
            Task(
                id=f"T{i:03d}",
                project_id="p1",
                md_path=f"tasks/T{i:03d}.md",
                status=status,
                path_whitelist=[],
            )
        )
    pending = store.list_tasks(status=TaskStatus.PENDING)
    assert len(pending) == 2


def test_append_interaction(tmp_docs: Path):
    store = _make_store(tmp_docs)
    store.append_interaction(
        Interaction(
            project_id="p1",
            task_id="T001",
            from_agent="orchestrator",
            to_agent="glm5",
            kind="request",
            content=json.dumps({"spec": "hello"}),
            tokens_in=42,
            tokens_out=None,
            cost_usd=0.0,
        )
    )
    rows = store.list_interactions(task_id="T001")
    assert len(rows) == 1
    assert rows[0].from_agent == "orchestrator"
    assert rows[0].tokens_in == 42
