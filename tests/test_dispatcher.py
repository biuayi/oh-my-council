from datetime import datetime
from pathlib import Path

from omc.budget import BudgetTracker, Limits
from omc.clients.base import ReviewOutput
from omc.clients.fake_auditor import FakeAuditor
from omc.clients.fake_codex import FakeCodexClient
from omc.clients.fake_worker import FakeWorkerRunner
from omc.dispatcher import Dispatcher, DispatcherDeps
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _deps(tmp_docs: Path) -> tuple[Dispatcher, ProjectStore, MDLayout]:
    project_root = tmp_docs / "projects" / "p1"
    md = MDLayout(project_root)
    md.scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    deps = DispatcherDeps(
        store=store,
        md=md,
        codex=FakeCodexClient(),
        worker=FakeWorkerRunner(),
        auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=project_root / "workspace",
    )
    (deps.project_source_root).mkdir(parents=True, exist_ok=True)
    return Dispatcher(deps), store, md


def test_happy_path_accepts_task(tmp_docs: Path):
    dispatcher, store, md = _deps(tmp_docs)
    now = datetime(2026, 4, 12)
    store.upsert_task(
        Task(
            id="T001",
            project_id="p1",
            md_path="tasks/T001.md",
            status=TaskStatus.PENDING,
            path_whitelist=["src/generated/T001.py"],
            created_at=now,
            updated_at=now,
        )
    )

    dispatcher.run_once("T001", requirement="build a hello module")

    got = store.get_task("T001")
    assert got is not None
    assert got.status is TaskStatus.ACCEPTED
    # MD artifacts written
    assert md.read_review("T001").startswith("# review")
    assert md.read_audit("T001").startswith("# audit")
    # task file exists
    assert md.read_task("T001").startswith("# T001 spec")
    # workspace file created
    assert (dispatcher.deps.project_source_root / "src/generated/T001.py").exists()


def test_review_fail_then_pass_retries(tmp_docs: Path):
    project_root = tmp_docs / "projects" / "p1"
    md = MDLayout(project_root)
    md.scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    codex = FakeCodexClient(
        reviews={
            "T001": [
                ReviewOutput(task_id="T001", passed=False, review_md="needs fix"),
                ReviewOutput(task_id="T001", passed=True, review_md="ok"),
            ]
        }
    )
    deps = DispatcherDeps(
        store=store,
        md=md,
        codex=codex,
        worker=FakeWorkerRunner(),
        auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=project_root / "workspace",
    )
    deps.project_source_root.mkdir(parents=True, exist_ok=True)
    dispatcher = Dispatcher(deps)

    now = datetime(2026, 4, 12)
    store.upsert_task(
        Task(
            id="T001",
            project_id="p1",
            md_path="tasks/T001.md",
            status=TaskStatus.PENDING,
            path_whitelist=["src/generated/T001.py"],
            created_at=now,
            updated_at=now,
        )
    )

    dispatcher.run_once("T001", requirement="build it")

    got = store.get_task("T001")
    assert got is not None
    assert got.status is TaskStatus.ACCEPTED
    assert got.attempts == 2  # first review failed, second passed


def test_path_whitelist_violation_blocks_task(tmp_docs: Path):
    from omc.clients.base import WorkerOutput

    project_root = tmp_docs / "projects" / "p1"
    md = MDLayout(project_root)
    md.scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    worker = FakeWorkerRunner(
        outputs={
            "T001": [
                WorkerOutput(task_id="T001", files={"src/evil.py": "x=1"}),
                WorkerOutput(task_id="T001", files={"src/evil.py": "x=1"}),
                WorkerOutput(task_id="T001", files={"src/evil.py": "x=1"}),
                WorkerOutput(task_id="T001", files={"src/evil.py": "x=1"}),
            ]
        }
    )
    deps = DispatcherDeps(
        store=store,
        md=md,
        codex=FakeCodexClient(),
        worker=worker,
        auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=project_root / "workspace",
    )
    deps.project_source_root.mkdir(parents=True, exist_ok=True)
    dispatcher = Dispatcher(deps)

    now = datetime(2026, 4, 12)
    store.upsert_task(
        Task(
            id="T001",
            project_id="p1",
            md_path="tasks/T001.md",
            status=TaskStatus.PENDING,
            path_whitelist=["src/generated/T001.py"],
            created_at=now,
            updated_at=now,
        )
    )

    dispatcher.run_once("T001", requirement="x")

    got = store.get_task("T001")
    assert got is not None
    assert got.status is TaskStatus.BLOCKED
