"""omc CLI. Phase 1: init + run-fake (smoke test). See spec §1 slash commands
for the Phase 3 full command set."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from omc.budget import BudgetTracker, Limits
from omc.clients.codex_cli import CodexCLI
from omc.clients.fake_auditor import FakeAuditor
from omc.clients.fake_codex import FakeCodexClient
from omc.clients.fake_worker import FakeWorkerRunner
from omc.clients.real_auditor import LiteLLMAuditor
from omc.clients.real_codex import RealCodexClient
from omc.clients.real_worker import LiteLLMWorker
from omc.config import load_settings
from omc.dispatcher import Dispatcher, DispatcherDeps
from omc.models import Project, ProjectStatus, Task, TaskStatus
from omc.store.index import IndexStore
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _docs_root() -> Path:
    return Path.cwd() / "docs"


def cmd_init(args: argparse.Namespace) -> int:
    slug = args.slug
    today = datetime.now().strftime("%Y-%m-%d")
    project_id = f"{today}-{slug}"
    docs = _docs_root()
    project_root = docs / "projects" / project_id

    idx = IndexStore(docs / "index.sqlite3")
    now = datetime.now()
    idx.upsert_project(
        Project(
            id=project_id,
            title=slug,
            status=ProjectStatus.PLANNING,
            root_path=str(project_root),
            created_at=now,
            updated_at=now,
        )
    )
    MDLayout(project_root).scaffold()
    ProjectStore(project_root / "council.sqlite3")  # materializes schema
    MDLayout(project_root).write_requirement(f"# {slug}\n\n(fill in the requirement)\n")

    print(f"initialized project {project_id} at {project_root}")
    return 0


def cmd_run_fake(args: argparse.Namespace) -> int:
    project_id = args.project_id
    task_id = args.task_id
    docs = _docs_root()
    project_root = docs / "projects" / project_id
    if not project_root.exists():
        print(f"error: project {project_id} not found", file=sys.stderr)
        return 2

    md = MDLayout(project_root)
    store = ProjectStore(project_root / "council.sqlite3")

    # If task not present, seed a demo one
    if store.get_task(task_id) is None:
        now = datetime.now()
        store.upsert_task(
            Task(
                id=task_id,
                project_id=project_id,
                md_path=f"tasks/{task_id}.md",
                status=TaskStatus.PENDING,
                path_whitelist=[f"src/generated/{task_id}.py"],
                created_at=now,
                updated_at=now,
            )
        )

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
    Dispatcher(deps).run_once(task_id, requirement=md.read_requirement())

    got = store.get_task(task_id)
    print(f"task {task_id} -> {got.status if got else 'MISSING'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    project_id = args.project_id
    task_id = args.task_id
    docs = _docs_root()
    project_root = docs / "projects" / project_id
    if not project_root.exists():
        print(f"error: project {project_id} not found", file=sys.stderr)
        return 2

    settings = load_settings()
    md = MDLayout(project_root)
    store = ProjectStore(project_root / "council.sqlite3")
    workspace = project_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    deps = DispatcherDeps(
        store=store, md=md,
        codex=RealCodexClient(
            cli=CodexCLI(bin=settings.codex_bin, timeout_s=settings.codex_timeout_s),
            workspace_root=workspace,
        ),
        worker=LiteLLMWorker(settings),
        auditor=LiteLLMAuditor(settings),
        budget=BudgetTracker(Limits()),
        project_source_root=workspace,
    )
    Dispatcher(deps).run_once(task_id, requirement=md.read_requirement())
    got = store.get_task(task_id)
    print(f"task {task_id} -> {got.status if got else 'MISSING'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="omc")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="initialize a new project under docs/")
    p_init.add_argument("slug")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser(
        "run-fake", help="run a task through the fake pipeline (smoke test)"
    )
    p_run.add_argument("project_id")
    p_run.add_argument("task_id")
    p_run.set_defaults(func=cmd_run_fake)

    p_real = sub.add_parser("run", help="run a task using real LLM backends")
    p_real.add_argument("project_id")
    p_real.add_argument("task_id")
    p_real.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
