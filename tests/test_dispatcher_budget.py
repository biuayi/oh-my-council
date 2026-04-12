"""L4 project-wide USD budget enforcement in Dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from omc.budget import BudgetTracker, Limits
from omc.clients.base import AuditOutput, ReviewOutput, SpecOutput, WorkerOutput
from omc.dispatcher import Dispatcher, DispatcherDeps
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


@dataclass
class _CodexStub:
    spec_cost: float = 0.0
    review_cost: float = 0.0

    def produce_spec(self, task_id, requirement):
        return SpecOutput(
            task_id=task_id, spec_md="# spec\n", path_whitelist=["a.py"],
            tokens_used=0, cost_usd=self.spec_cost,
        )

    def review(self, task_id, files, spec_md):
        return ReviewOutput(
            task_id=task_id, passed=True, review_md="ok",
            tokens_used=0, cost_usd=self.review_cost,
        )


@dataclass
class _WorkerStub:
    cost: float = 0.0
    calls: int = field(default=0)

    def write(self, task_id, spec_md):
        self.calls += 1
        return WorkerOutput(
            task_id=task_id, files={"a.py": "pass\n"},
            tokens_used=1000, tokens_in=500, tokens_out=500, cost_usd=self.cost,
        )


@dataclass
class _AuditorStub:
    cost: float = 0.0

    def audit(self, task_id, files):
        return AuditOutput(
            task_id=task_id, passed=True, audit_md="ok",
            tokens_used=0, cost_usd=self.cost,
        )


def _make_deps(tmp_path: Path, *, codex, worker, auditor, limits):
    store = ProjectStore(tmp_path / "council.sqlite3")
    md = MDLayout(tmp_path)
    md.scaffold()
    src = tmp_path / "src"
    src.mkdir()
    return DispatcherDeps(
        store=store, md=md, codex=codex, worker=worker, auditor=auditor,
        budget=BudgetTracker(limits), project_source_root=src,
    ), store


def _seed_task(store, task_id="T001"):
    store.upsert_task(Task(
        id=task_id, project_id="p1", milestone_id=None,
        md_path=f"tasks/{task_id}.md", status=TaskStatus.PENDING,
        assignee="glm5", attempts=0, codex_escalated=0,
        tokens_used=0, cost_usd=0.0, path_whitelist=["a.py"],
        created_at=datetime.now(), updated_at=datetime.now(),
    ))


def test_worker_cost_recorded_and_persisted(tmp_path):
    deps, store = _make_deps(
        tmp_path, codex=_CodexStub(spec_cost=0.01, review_cost=0.02),
        worker=_WorkerStub(cost=0.50), auditor=_AuditorStub(cost=0.05),
        limits=Limits(),
    )
    _seed_task(store)
    Dispatcher(deps).run_once("T001", "requirement")

    # Task aggregate cost should be spec + worker + review + audit = 0.58
    t = store.get_task("T001")
    assert abs(t.cost_usd - 0.58) < 1e-6
    # Budget tracker saw the same
    assert abs(deps.budget.cost() - 0.58) < 1e-6
    # Interactions table has cost_usd populated
    costs = [i.cost_usd for i in store.recent_interactions(limit=20) if i.cost_usd]
    assert sum(costs) > 0.0


def test_l4_exhausted_halts_before_next_task(tmp_path):
    # Tiny L4 limit, worker burns $6 on first call => should halt immediately
    # after recording the worker output (cost exceeds limit).
    deps, store = _make_deps(
        tmp_path, codex=_CodexStub(), worker=_WorkerStub(cost=6.0),
        auditor=_AuditorStub(),
        limits=Limits(l4_project_usd=5.0),
    )
    _seed_task(store)
    Dispatcher(deps).run_once("T001", "requirement")
    t = store.get_task("T001")
    assert t.status == TaskStatus.OVER_BUDGET
    assert deps.budget.l4_exhausted()
