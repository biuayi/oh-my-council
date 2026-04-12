"""omc CLI. Phase 1: init + run-fake (smoke test). See spec §1 slash commands
for the Phase 3 full command set."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from omc.budget import BudgetTracker, Limits
from omc.clients.claude_cli import ClaudeCLI
from omc.clients.codex_cli import CodexCLI
from omc.clients.fake_auditor import FakeAuditor
from omc.clients.fake_codex import FakeCodexClient
from omc.clients.fake_worker import FakeWorkerRunner
from omc.clients.real_auditor import LiteLLMAuditor
from omc.clients.real_codex import RealCodexClient
from omc.clients.real_worker import LiteLLMWorker
from omc.config import load_settings
from omc.dispatcher import Dispatcher, DispatcherDeps
from omc.mcp_server import run_stdio
from omc.models import Project, ProjectStatus, Task, TaskStatus
from omc.store.index import IndexStore
from omc.store.md import MDLayout
from omc.store.project import ProjectStore
from omc.verifier import MilestoneVerifier


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


def cmd_mcp(args: argparse.Namespace) -> int:
    run_stdio(_docs_root())
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    project_root = _docs_root() / "projects" / args.project_id
    if not project_root.exists():
        print(f"error: project {args.project_id} not found", file=sys.stderr)
        return 2
    store = ProjectStore(project_root / "council.sqlite3")
    rows = store.recent_interactions(limit=args.limit)
    for r in reversed(rows):
        print(f"[{r.task_id}] {r.from_agent} -> {r.to_agent} ({r.kind}): "
              f"{r.content[:80]}")
    return 0


def cmd_tmux(args: argparse.Namespace) -> int:
    project_root = _docs_root() / "projects" / args.project_id
    if not project_root.exists():
        print(f"error: project {args.project_id} not found", file=sys.stderr)
        return 2

    session = f"omc-{args.project_id}"
    db = project_root / "council.sqlite3"
    cmds = [
        ["tmux", "new-session", "-d", "-s", session, "-n", "council"],
        ["tmux", "split-window", "-t", session, "-h",
         f"omc tail {args.project_id}"],
        ["tmux", "split-window", "-t", session, "-v",
         f"watch -n 1 'sqlite3 {db} \"SELECT id,status FROM tasks\"'"],
        ["tmux", "split-window", "-t", session, "-v",
         f"omc tail {args.project_id} --limit 5"],
        ["tmux", "split-window", "-t", session, "-v",
         f"omc tail {args.project_id} --limit 5"],
        ["tmux", "select-layout", "-t", session, "tiled"],
    ]
    for c in cmds:
        r = subprocess.run(c, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"tmux failed: {' '.join(c)}\n{r.stderr}", file=sys.stderr)
            return r.returncode
    print(f"tmux session '{session}' created. attach with: tmux attach -t {session}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    project_root = _docs_root() / "projects" / args.project_id
    if not project_root.exists():
        print(f"error: project {args.project_id} not found", file=sys.stderr)
        return 2
    md = MDLayout(project_root)
    store = ProjectStore(project_root / "council.sqlite3")
    verifier = MilestoneVerifier(cli=ClaudeCLI())
    verdict = verifier.verify(store=store, md=md, project_id=args.project_id)
    print(f"[{verdict.decision}] {verdict.summary}")
    for action in verdict.next_actions:
        print(f"  - {action}")
    return {"ACCEPT": 0, "NEED_DETAIL": 3, "REJECT": 4}.get(verdict.decision, 4)


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

    p_mcp = sub.add_parser("mcp", help="run MCP stdio server for Claude Code")
    p_mcp.set_defaults(func=cmd_mcp)

    p_tail = sub.add_parser("tail", help="print recent agent interactions")
    p_tail.add_argument("project_id")
    p_tail.add_argument("--limit", type=int, default=20)
    p_tail.set_defaults(func=cmd_tail)

    p_tmux = sub.add_parser("tmux", help="launch tmux observer panel for a project")
    p_tmux.add_argument("project_id")
    p_tmux.set_defaults(func=cmd_tmux)

    p_verify = sub.add_parser("verify", help="run milestone verify via claude -p")
    p_verify.add_argument("project_id")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
