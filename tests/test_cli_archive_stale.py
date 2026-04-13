import os
import tarfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from omc.cli import main
from omc.models import Interaction, Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _seed(docs: Path, pid: str, *, recent: bool):
    project_root = docs / "projects" / pid
    MDLayout(project_root).scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    when = datetime.now() if recent else (datetime.now() - timedelta(days=60))
    store.upsert_task(Task(
        id="T1", project_id=pid, md_path="tasks/T1.md",
        status=TaskStatus.ACCEPTED, path_whitelist=[],
        created_at=when, updated_at=when,
    ))
    store.append_interaction(Interaction(
        project_id=pid, task_id="T1", from_agent="glm",
        to_agent="orchestrator", kind="response", content="x",
        tokens_in=None, tokens_out=1, cost_usd=0.01, created_at=when,
    ))
    # Force the directory mtime for the stale case so mtime-based gate aligns
    if not recent:
        old = time.time() - 60 * 86400
        os.utime(project_root, (old, old))


def test_archive_stale_moves_only_old_projects(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    _seed(docs, "2026-01-01-old-one", recent=False)
    _seed(docs, "2026-04-10-fresh", recent=True)

    rc = main(["archive-stale", "--days", "30"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "archived: 2026-01-01-old-one" in out
    assert "skipped:  2026-04-10-fresh" in out

    archive_dir = docs / "_archive"
    assert (archive_dir / "2026-01-01-old-one.tar.gz").exists()
    assert not (archive_dir / "2026-04-10-fresh.tar.gz").exists()


def test_archive_stale_remove_flag_deletes_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    _seed(docs, "2026-01-01-old", recent=False)
    src = docs / "projects" / "2026-01-01-old"
    assert src.exists()

    rc = main(["archive-stale", "--days", "7", "--remove"])
    assert rc == 0
    assert not src.exists()
    tar = docs / "_archive" / "2026-01-01-old.tar.gz"
    assert tar.exists()
    with tarfile.open(tar, "r:gz") as tf:
        names = tf.getnames()
    assert any(n.startswith("2026-01-01-old/") for n in names)


def test_archive_stale_empty_projects_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = main(["archive-stale", "--days", "30"])
    assert rc == 0
    assert "no projects dir" in capsys.readouterr().out
