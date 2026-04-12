import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from omc.budget import BudgetTracker, Limits
from omc.clients.codex_cli import CodexCLI
from omc.clients.real_auditor import LiteLLMAuditor
from omc.clients.real_codex import RealCodexClient
from omc.clients.real_worker import LiteLLMWorker
from omc.config import load_settings
from omc.dispatcher import Dispatcher, DispatcherDeps
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore

pytestmark = pytest.mark.slow


@pytest.fixture
def settings():
    try:
        return load_settings()
    except (KeyError, FileNotFoundError):
        pytest.skip("no ~/.config/oh-my-council/.env")


def test_greet_end_to_end(tmp_path: Path, settings):
    project_root = tmp_path / "p"
    md = MDLayout(project_root)
    md.scaffold()
    md.write_requirement(
        "# Requirement\n\nImplement `greet(name: str) -> str` in "
        "src/generated/greet.py returning 'hello <name>'. Also write a "
        "pytest in tests/test_greet.py that asserts greet('world') == 'hello world'."
    )
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime.now()
    store.upsert_task(Task(
        id="T001", project_id="p", md_path="tasks/T001.md",
        status=TaskStatus.PENDING,
        path_whitelist=["src/generated/greet.py", "tests/test_greet.py"],
        created_at=now, updated_at=now,
    ))
    workspace = project_root / "ws"
    workspace.mkdir()

    codex = RealCodexClient(
        cli=CodexCLI(bin=settings.codex_bin, timeout_s=settings.codex_timeout_s),
        workspace_root=workspace,
    )
    deps = DispatcherDeps(
        store=store, md=md, codex=codex,
        worker=LiteLLMWorker(settings),
        auditor=LiteLLMAuditor(settings),
        budget=BudgetTracker(Limits()),
        project_source_root=workspace,
    )
    Dispatcher(deps).run_once("T001", requirement=md.read_requirement())

    got = store.get_task("T001")
    assert got.status is TaskStatus.ACCEPTED, f"status={got.status}"
    assert (workspace / "src/generated/greet.py").exists()
    assert (workspace / "tests/test_greet.py").exists()

    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(workspace / "tests"), "-q"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, f"generated tests failed: {r.stdout}{r.stderr}"
