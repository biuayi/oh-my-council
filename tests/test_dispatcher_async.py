from datetime import datetime
from pathlib import Path

import pytest

from omc.budget import BudgetTracker, Limits
from omc.clients.fake_auditor import FakeAuditor
from omc.clients.fake_codex import FakeCodexClient
from omc.clients.fake_worker import FakeWorkerRunner
from omc.dispatcher import DispatcherDeps
from omc.dispatcher_async import AsyncDispatcher
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _seed(store, ids):
    now = datetime(2026, 4, 12)
    for tid in ids:
        store.upsert_task(Task(
            id=tid, project_id="p", md_path=f"tasks/{tid}.md",
            status=TaskStatus.PENDING,
            path_whitelist=[f"src/generated/{tid}.py"],
            created_at=now, updated_at=now,
        ))


@pytest.mark.asyncio
async def test_runs_multiple_tasks_concurrently(tmp_docs: Path):
    project_root = tmp_docs / "p"
    md = MDLayout(project_root)
    md.scaffold()
    store = ProjectStore(project_root / "c.sqlite3")
    _seed(store, ["T1", "T2", "T3"])
    deps = DispatcherDeps(
        store=store, md=md, codex=FakeCodexClient(), worker=FakeWorkerRunner(),
        auditor=FakeAuditor(), budget=BudgetTracker(Limits()),
        project_source_root=project_root / "ws",
    )
    deps.project_source_root.mkdir(parents=True, exist_ok=True)
    ad = AsyncDispatcher(deps, concurrency=2)
    await ad.run_batch(["T1", "T2", "T3"], requirement="build")
    for tid in ("T1", "T2", "T3"):
        assert store.get_task(tid).status is TaskStatus.ACCEPTED
