from datetime import datetime
from pathlib import Path

from omc.budget import BudgetTracker, Limits
from omc.clients.fake_auditor import FakeAuditor
from omc.clients.fake_codex import FakeCodexClient
from omc.clients.fake_worker import FakeWorkerRunner
from omc.dispatcher import Dispatcher, DispatcherDeps
from omc.models import Project, ProjectStatus, Task, TaskStatus
from omc.store.index import IndexStore
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def test_full_project_lifecycle_with_fakes(tmp_docs: Path):
    # 1. Register project in global index
    idx = IndexStore(tmp_docs / "index.sqlite3")
    now = datetime(2026, 4, 12, 12, 0, 0)
    project_id = "2026-04-12-demo"
    project_root = tmp_docs / "projects" / project_id
    idx.upsert_project(
        Project(
            id=project_id,
            title="demo",
            status=ProjectStatus.RUNNING,
            root_path=str(project_root),
            created_at=now,
            updated_at=now,
        )
    )

    # 2. Scaffold project directory + stores
    md = MDLayout(project_root)
    md.scaffold()
    md.write_requirement("# Requirement\n\nBuild a hello module.")

    store = ProjectStore(project_root / "council.sqlite3")

    # 3. Seed one task
    store.upsert_task(
        Task(
            id="T001",
            project_id=project_id,
            md_path="tasks/T001.md",
            status=TaskStatus.PENDING,
            path_whitelist=["src/generated/T001.py"],
            created_at=now,
            updated_at=now,
        )
    )

    # 4. Dispatch
    workspace = project_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    deps = DispatcherDeps(
        store=store,
        md=md,
        codex=FakeCodexClient(),
        worker=FakeWorkerRunner(),
        auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=workspace,
    )
    Dispatcher(deps).run_once("T001", requirement=md.read_requirement())

    # 5. Assertions: state, files, interactions
    got = store.get_task("T001")
    assert got is not None
    assert got.status is TaskStatus.ACCEPTED
    assert got.attempts == 1

    assert (workspace / "src/generated/T001.py").exists()
    assert (project_root / "reviews" / "T001.md").exists()
    assert (project_root / "audits" / "T001.md").exists()

    interactions = store.list_interactions(task_id="T001")
    kinds = [i.kind for i in interactions]
    assert "response" in kinds  # codex spec
    assert "request" in kinds   # orchestrator -> glm5
    assert "review" in kinds
    assert "audit" in kinds
