from datetime import datetime

from omc.cli import main
from omc.models import Interaction, Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def test_tail_prints_recent_interactions(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    pid = "p1"
    project_root = docs / "projects" / pid
    MDLayout(project_root).scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime(2026, 4, 12)
    store.upsert_task(Task(id="T1", project_id=pid, md_path="tasks/T1.md",
                           status=TaskStatus.PENDING, path_whitelist=[],
                           created_at=now, updated_at=now))
    store.append_interaction(Interaction(
        project_id=pid, task_id="T1", from_agent="codex", to_agent="orchestrator",
        kind="response", content="hello", tokens_in=None, tokens_out=100,
    ))

    rc = main(["tail", pid, "--limit", "5"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "codex" in captured.out
    assert "hello" in captured.out


def test_tail_missing_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = main(["tail", "nope"])
    assert rc == 2
