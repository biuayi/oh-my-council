"""Regression test: dispatcher must apply hallucination gate to Codex review."""

from __future__ import annotations

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


class CodexWithBogusSymbol(FakeCodexClient):
    """FakeCodexClient that passes review but claims a bogus symbol exists."""

    def __init__(self) -> None:
        super().__init__()
        self._last_symbols = [
            {"name": "definitely_not_real_pkg.foo", "kind": "call", "file": "x.py"}
        ]


def test_hallucination_gate_flips_review_pass_to_fail(tmp_docs: Path) -> None:
    project_root = tmp_docs / "p"
    md = MDLayout(project_root)
    md.scaffold()
    store = ProjectStore(project_root / "c.sqlite3")

    now = datetime(2026, 4, 12)
    store.upsert_task(Task(
        id="T1", project_id="p", md_path="tasks/T1.md",
        status=TaskStatus.PENDING,
        path_whitelist=["src/generated/T1.py"],
        created_at=now, updated_at=now,
    ))

    workspace = project_root / "ws"
    workspace.mkdir()

    deps = DispatcherDeps(
        store=store, md=md,
        codex=CodexWithBogusSymbol(),
        worker=FakeWorkerRunner(),
        auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=workspace,
    )

    Dispatcher(deps).run_once("T1", requirement="x")

    # With a bogus symbol, review is forced to fail; worker retries exhaust L1
    # and (no dispatch_escalation) task ends BLOCKED.
    got = store.get_task("T1")
    assert got.status is TaskStatus.BLOCKED

    review_md = (project_root / "reviews" / "T1.md").read_text(encoding="utf-8")
    assert "hallucination offenders" in review_md
    assert "definitely_not_real_pkg" in review_md


def test_run_review_gate_passes_through_when_no_symbols(tmp_docs: Path) -> None:
    """If codex has no _last_symbols attribute, review is untouched."""
    project_root = tmp_docs / "p"
    md = MDLayout(project_root)
    md.scaffold()
    store = ProjectStore(project_root / "c.sqlite3")
    deps = DispatcherDeps(
        store=store, md=md,
        codex=FakeCodexClient(),  # no _last_symbols attr
        worker=FakeWorkerRunner(),
        auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=project_root / "ws",
    )
    (project_root / "ws").mkdir()
    dispatcher = Dispatcher(deps)
    original = ReviewOutput(task_id="T", passed=True, review_md="ok", tokens_used=10)
    assert dispatcher._run_review_gate(original) is original
