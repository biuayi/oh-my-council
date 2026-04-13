from datetime import datetime, timedelta

from omc.cli import main
from omc.models import Interaction, Project, ProjectStatus, Task, TaskStatus
from omc.store.index import IndexStore
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _seed(tmp_path, pid, task_id="T1", cost=0.1234, when: datetime | None = None):
    docs = tmp_path / "docs"
    project_root = docs / "projects" / pid
    MDLayout(project_root).scaffold()
    idx = IndexStore(docs / "index.sqlite3")
    now = when or datetime.now()
    idx.upsert_project(Project(
        id=pid, title=pid, status=ProjectStatus.PLANNING,
        root_path=str(project_root), created_at=now, updated_at=now,
    ))
    store = ProjectStore(project_root / "council.sqlite3")
    store.upsert_task(Task(
        id=task_id, project_id=pid, md_path=f"tasks/{task_id}.md",
        status=TaskStatus.PENDING, path_whitelist=[],
        created_at=now, updated_at=now,
    ))
    store.append_interaction(Interaction(
        project_id=pid, task_id=task_id, from_agent="glm",
        to_agent="orchestrator", kind="response", content="x",
        tokens_in=100, tokens_out=100, cost_usd=cost, created_at=now,
    ))


def test_report_day_totals_recent(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, "p-fresh", cost=0.25, when=datetime.now())
    _seed(tmp_path, "p-old", cost=99.0, when=datetime.now() - timedelta(days=10))
    rc = main(["report", "--period", "day"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "last 24h" in out
    assert "p-fresh" in out
    assert "p-old" not in out  # outside window
    assert "TOTAL  $0.250000" in out


def test_report_week_includes_older_but_not_old(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, "p-3d", cost=0.5, when=datetime.now() - timedelta(days=3))
    _seed(tmp_path, "p-10d", cost=99.0, when=datetime.now() - timedelta(days=10))
    rc = main(["report", "--period", "week"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "p-3d" in out
    assert "p-10d" not in out


def test_report_all_includes_everything(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, "p-ancient", cost=1.0, when=datetime(2020, 1, 1))
    rc = main(["report", "--period", "all"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "p-ancient" in out
    assert "all time" in out


def test_report_by_task_shows_per_task_rows(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, "p1", task_id="T001", cost=0.1)
    # Add another task in same project
    store = ProjectStore(tmp_path / "docs" / "projects" / "p1" / "council.sqlite3")
    now = datetime.now()
    store.upsert_task(Task(
        id="T002", project_id="p1", md_path="tasks/T002.md",
        status=TaskStatus.PENDING, path_whitelist=[],
        created_at=now, updated_at=now,
    ))
    store.append_interaction(Interaction(
        project_id="p1", task_id="T002", from_agent="glm",
        to_agent="orchestrator", kind="response", content="y",
        tokens_in=1, tokens_out=1, cost_usd=0.3, created_at=now,
    ))
    rc = main(["report", "--period", "day", "--by-task"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "T001" in out and "T002" in out


def test_report_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    rc = main(["report", "--period", "day"])
    assert rc == 0
    assert "no spend recorded" in capsys.readouterr().out
