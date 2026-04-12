from datetime import datetime
from unittest.mock import patch

from omc.cli import main
from omc.models import Task, TaskStatus
from omc.store.project import ProjectStore


def test_cli_run_wires_real_clients(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "OMC_WORKER_VENDOR=x\nOMC_WORKER_MODEL=m\n"
        "OMC_WORKER_API_BASE=https://x\nOMC_WORKER_API_KEY=k\n"
    )
    monkeypatch.setenv("OMC_ENV_FILE", str(env))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "projects" / "p1").mkdir(parents=True)

    # Create requirement.md to prevent read errors
    (tmp_path / "docs" / "projects" / "p1" / "requirement.md").write_text(
        "# Test Requirement\n"
    )

    with patch("omc.cli.Dispatcher") as D, \
         patch("omc.cli.RealCodexClient") as RC, \
         patch("omc.cli.LiteLLMWorker") as LW, \
         patch("omc.cli.LiteLLMAuditor") as LA:
        D.return_value.run_once.return_value = None

        s = ProjectStore(tmp_path / "docs" / "projects" / "p1" / "council.sqlite3")
        now = datetime.now()
        s.upsert_task(Task(id="T1", project_id="p1", md_path="tasks/T1.md",
                           status=TaskStatus.PENDING, path_whitelist=["src/generated/T1.py"],
                           created_at=now, updated_at=now))

        rc = main(["run", "p1", "T1"])

    assert rc == 0
    assert RC.called and LW.called and LA.called
    D.return_value.run_once.assert_called_once()
