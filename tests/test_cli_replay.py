from datetime import datetime

from omc.cli import main
from omc.models import Interaction, Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _seed(tmp_path, pid="p1", task_id="T1"):
    docs = tmp_path / "docs"
    project_root = docs / "projects" / pid
    MDLayout(project_root).scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime(2026, 4, 13)
    store.upsert_task(Task(
        id=task_id, project_id=pid, md_path=f"tasks/{task_id}.md",
        status=TaskStatus.PENDING, path_whitelist=[],
        created_at=now, updated_at=now,
    ))
    return docs, store


def test_replay_prints_full_chain_in_order(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    docs, store = _seed(tmp_path)
    for i, (agent, content) in enumerate([
        ("codex", "spec-prompt body"),
        ("glm", "worker output"),
        ("codex", "review verdict"),
    ]):
        store.append_interaction(Interaction(
            project_id="p1", task_id="T1", from_agent=agent,
            to_agent="orchestrator", kind="response",
            content=content, tokens_in=None, tokens_out=10 * (i + 1),
        ))

    rc = main(["replay", "p1", "T1"])
    out = capsys.readouterr().out
    assert rc == 0
    # All three bodies present and in chronological order
    p1 = out.index("spec-prompt body")
    p2 = out.index("worker output")
    p3 = out.index("review verdict")
    assert p1 < p2 < p3


def test_replay_truncates_long_bodies(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    docs, store = _seed(tmp_path)
    big = "x" * 5000
    store.append_interaction(Interaction(
        project_id="p1", task_id="T1", from_agent="glm",
        to_agent="orchestrator", kind="response", content=big,
        tokens_in=None, tokens_out=1,
    ))
    rc = main(["replay", "p1", "T1", "--max-chars", "100"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "truncated, 5000 chars total" in out


def test_replay_missing_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["replay", "nope", "T1"]) == 2


def test_replay_missing_task(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    rc = main(["replay", "p1", "T999"])
    assert rc == 2
    assert "task T999 not found" in capsys.readouterr().err
