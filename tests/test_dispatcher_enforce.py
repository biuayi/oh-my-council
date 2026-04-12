"""Tests for Phase 2 budget enforcement in Dispatcher (Task 9)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from omc.budget import BudgetTracker, Limits
from omc.clients.base import WorkerOutput
from omc.clients.fake_auditor import FakeAuditor
from omc.clients.fake_codex import FakeCodexClient
from omc.clients.fake_worker import FakeWorkerRunner
from omc.dispatcher import Dispatcher, DispatcherDeps
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _make_task(task_id: str = "T001", whitelist: list[str] | None = None) -> Task:
    return Task(
        id=task_id,
        project_id="p1",
        md_path=f"tasks/{task_id}.md",
        status=TaskStatus.PENDING,
        path_whitelist=whitelist or [f"src/generated/{task_id}.py"],
        created_at=datetime(2026, 4, 12),
        updated_at=datetime(2026, 4, 12),
    )


def _setup(
    tmp_docs: Path,
    *,
    worker: FakeWorkerRunner,
    codex: FakeCodexClient | None = None,
    limits: Limits | None = None,
) -> tuple[Dispatcher, ProjectStore]:
    project_root = tmp_docs / "projects" / "p1"
    md = MDLayout(project_root)
    md.scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    deps = DispatcherDeps(
        store=store,
        md=md,
        codex=codex or FakeCodexClient(),
        worker=worker,
        auditor=FakeAuditor(),
        budget=BudgetTracker(limits or Limits()),
        project_source_root=project_root / "workspace",
    )
    deps.project_source_root.mkdir(parents=True, exist_ok=True)
    return Dispatcher(deps), store


# ---------------------------------------------------------------------------
# Helper: FakeWorkerRunner that always produces a bad-path file
# ---------------------------------------------------------------------------

def _bad_worker(task_id: str = "T001", n: int = 10) -> FakeWorkerRunner:
    """Worker that always writes to an un-whitelisted path."""
    return FakeWorkerRunner(
        outputs={
            task_id: [
                WorkerOutput(task_id=task_id, files={"src/evil.py": "x=1"})
            ]
            * n
        }
    )


# ---------------------------------------------------------------------------
# L1 → Codex escalation → ACCEPTED
# ---------------------------------------------------------------------------

class _EscalatingCodex(FakeCodexClient):
    """FakeCodexClient extended with dispatch_escalation support."""

    def __init__(self, good_file: str, **kwargs):
        super().__init__(**kwargs)
        self.called_escalation = False
        self._good_file = good_file

    def dispatch_escalation(
        self,
        task_id: str,
        spec_md: str,
        files: dict[str, str],
    ) -> dict[str, str]:
        self.called_escalation = True
        # Return a file that satisfies the whitelist
        return {self._good_file: '"""escalated."""\n\nVALUE = 42\n'}


def test_l1_triggers_codex_escalation(tmp_docs: Path):
    """When L1 is exhausted and codex has dispatch_escalation, codex steps in
    and the task should be ACCEPTED with codex_escalated == 1."""
    task_id = "T001"
    good_path = f"src/generated/{task_id}.py"

    escalating_codex = _EscalatingCodex(good_file=good_path)

    # Worker always writes to bad path -> path_whitelist will fail
    worker = _bad_worker(task_id, n=20)

    # Limits: l1 = 3 retries means exhausted after 4 attempts
    limits = Limits(l1_worker_retries=3, l2_codex_retries=1, l3_task_tokens=200_000)

    dispatcher, store = _setup(
        tmp_docs, worker=worker, codex=escalating_codex, limits=limits
    )
    store.upsert_task(_make_task(task_id, whitelist=[good_path]))

    dispatcher.run_once(task_id, requirement="build it")

    got = store.get_task(task_id)
    assert got is not None
    assert got.status is TaskStatus.ACCEPTED
    assert escalating_codex.called_escalation is True
    assert got.codex_escalated == 1


# ---------------------------------------------------------------------------
# L2 exhausted → BLOCKED
# ---------------------------------------------------------------------------

class _FailingEscalationCodex(FakeCodexClient):
    """dispatch_escalation returns files that still fail the whitelist."""

    def dispatch_escalation(
        self,
        task_id: str,
        spec_md: str,
        files: dict[str, str],
    ) -> dict[str, str]:
        # Still writes to the wrong path
        return {"src/evil_escalated.py": "x=1"}


def test_l2_exhausted_blocks_task(tmp_docs: Path):
    """When L1 and L2 are both exhausted (codex escalation also fails),
    the task should end up BLOCKED."""
    task_id = "T001"
    good_path = f"src/generated/{task_id}.py"

    failing_codex = _FailingEscalationCodex()
    worker = _bad_worker(task_id, n=20)

    # l2_codex_retries=0 means l2 is exhausted after the first codex attempt
    limits = Limits(l1_worker_retries=3, l2_codex_retries=0, l3_task_tokens=200_000)

    dispatcher, store = _setup(
        tmp_docs, worker=worker, codex=failing_codex, limits=limits
    )
    store.upsert_task(_make_task(task_id, whitelist=[good_path]))

    dispatcher.run_once(task_id, requirement="build it")

    got = store.get_task(task_id)
    assert got is not None
    assert got.status is TaskStatus.BLOCKED


# ---------------------------------------------------------------------------
# L3 token overrun → OVER_BUDGET
# ---------------------------------------------------------------------------

def test_l3_tokens_exceed_marks_over_budget(tmp_docs: Path):
    """When a worker produces output that pushes total tokens over L3 limit,
    the task should be marked OVER_BUDGET."""
    task_id = "T001"
    good_path = f"src/generated/{task_id}.py"

    # Worker produces a huge token output
    huge_worker = FakeWorkerRunner(
        outputs={
            task_id: [
                WorkerOutput(
                    task_id=task_id,
                    files={good_path: '"""ok."""\n\nVALUE = 1\n'},
                    tokens_used=500_000,  # way over l3 limit
                )
            ]
        }
    )

    # Very tight token budget
    limits = Limits(l1_worker_retries=3, l2_codex_retries=1, l3_task_tokens=1_000)

    dispatcher, store = _setup(tmp_docs, worker=huge_worker, limits=limits)
    store.upsert_task(_make_task(task_id, whitelist=[good_path]))

    dispatcher.run_once(task_id, requirement="build it")

    got = store.get_task(task_id)
    assert got is not None
    assert got.status is TaskStatus.OVER_BUDGET
