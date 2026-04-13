"""omc CLI. Phase 1: init + run-fake (smoke test). See spec §1 slash commands
for the Phase 3 full command set."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
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
from omc.notify import Notifier
from omc.store.index import IndexStore
from omc.store.md import MDLayout
from omc.store.project import ProjectStore
from omc.verifier import MilestoneVerifier


def _docs_root(args: argparse.Namespace | None = None) -> Path:
    if args and hasattr(args, "docs_root") and args.docs_root:
        return Path(args.docs_root)
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


def cmd_task_add(args: argparse.Namespace) -> int:
    project_id = args.project_id
    task_id = args.task_id
    docs = _docs_root(args)
    project_root = docs / "projects" / project_id
    if not project_root.exists():
        print(f"error: project {project_id} not found", file=sys.stderr)
        return 2
    store = ProjectStore(project_root / "council.sqlite3")
    if store.get_task(task_id) is not None and not args.force:
        print(
            f"error: task {task_id} already exists (use --force to overwrite)",
            file=sys.stderr,
        )
        return 3
    whitelist = [p.strip() for p in args.path_whitelist.split(",") if p.strip()] \
        if args.path_whitelist else []
    now = datetime.now()
    store.upsert_task(
        Task(
            id=task_id,
            project_id=project_id,
            md_path=f"tasks/{task_id}.md",
            status=TaskStatus.PENDING,
            path_whitelist=whitelist,
            created_at=now,
            updated_at=now,
        )
    )
    print(f"seeded task {task_id} in {project_id} (whitelist={whitelist})")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Decompose requirement.md into tasks via Codex and seed them."""
    project_id = args.project_id
    docs = _docs_root(args)
    project_root = docs / "projects" / project_id
    if not project_root.exists():
        print(f"error: project {project_id} not found", file=sys.stderr)
        return 2

    settings = load_settings()
    md = MDLayout(project_root)
    requirement = md.read_requirement()
    if not requirement.strip():
        print(
            f"error: {project_root}/requirement.md is empty; write it first",
            file=sys.stderr,
        )
        return 3

    codex = RealCodexClient(
        cli=CodexCLI(
            bin=settings.codex_bin,
            timeout_s=settings.codex_timeout_s,
            reasoning_effort=settings.codex_reasoning_effort,
        ),
        workspace_root=project_root / "workspace",
    )
    tasks = codex.produce_plan(requirement)

    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime.now()
    seeded: list[str] = []
    skipped: list[str] = []
    for t in tasks:
        tid = t["task_id"]
        if store.get_task(tid) is not None and not args.force:
            skipped.append(tid)
            continue
        store.upsert_task(
            Task(
                id=tid,
                project_id=project_id,
                md_path=f"tasks/{tid}.md",
                status=TaskStatus.PENDING,
                path_whitelist=t["path_whitelist"],
                created_at=now,
                updated_at=now,
            )
        )
        seeded.append(tid)
        print(f"  {tid}: {t['brief']}")
        for p in t["path_whitelist"]:
            print(f"      - {p}")
    print(
        f"planned {len(tasks)} tasks in {project_id} "
        f"(seeded={len(seeded)} skipped={len(skipped)})"
    )
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
            cli=CodexCLI(
                bin=settings.codex_bin,
                timeout_s=settings.codex_timeout_s,
                reasoning_effort=settings.codex_reasoning_effort,
            ),
            workspace_root=workspace,
        ),
        worker=LiteLLMWorker(settings),
        auditor=LiteLLMAuditor(settings),
        budget=BudgetTracker(Limits(), project_id=project_id, notifier=Notifier()),
        project_source_root=workspace,
        notifier=Notifier(),
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


def cmd_report(args: argparse.Namespace) -> int:
    """Budget rollup: total spend per period, optionally broken down by task."""
    from datetime import timedelta

    from omc.store.index import IndexStore

    docs = _docs_root()
    idx = IndexStore(docs / "index.sqlite3")
    projects = idx.list_projects()
    period = args.period
    now = datetime.now()
    if period == "day":
        since = now - timedelta(days=1)
    elif period == "week":
        since = now - timedelta(days=7)
    else:
        since = datetime(1970, 1, 1)
    since_iso = since.isoformat()

    total = 0.0
    rows: list[tuple[str, float, dict[str, float] | None]] = []
    for p in projects:
        db = docs / "projects" / p.id / "council.sqlite3"
        if not db.exists():
            continue
        ps = ProjectStore(db)
        cost = ps.cost_since(p.id, since_iso) if period != "all" else ps.project_cost_usd(p.id)
        if cost <= 0 and period != "all":
            continue
        by_task = ps.cost_breakdown_by_task(p.id) if args.by_task else None
        rows.append((p.id, cost, by_task))
        total += cost

    label = {"day": "last 24h", "week": "last 7d", "all": "all time"}[period]
    print(f"# omc cost report ({label})")
    if not rows:
        print("(no spend recorded)")
        return 0
    for pid, cost, by_task in rows:
        print(f"\n## {pid}  ${cost:.6f}")
        if by_task:
            for tid, c in by_task.items():
                if c > 0:
                    print(f"    {tid:<16} ${c:.6f}")
    print(f"\nTOTAL  ${total:.6f}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan a project's workspace for leaked secrets (regex + entropy)."""
    from omc.gates.secrets import scan_paths

    if args.project_id:
        root = _docs_root() / "projects" / args.project_id / "workspace"
        if not root.exists():
            print(f"error: workspace not found for {args.project_id}", file=sys.stderr)
            return 2
    else:
        root = Path(args.path).resolve() if args.path else Path.cwd()

    findings = scan_paths(root)
    if not findings:
        print(f"scan clean: no secrets found under {root}")
        return 0
    for f in findings:
        print(f"{f.path}:{f.line}  [{f.rule}]  {f.snippet}")
    print(f"\n{len(findings)} finding(s) under {root}", file=sys.stderr)
    return 1


def cmd_replay(args: argparse.Namespace) -> int:
    """Print the full chronological interaction chain for a single task."""
    project_root = _docs_root() / "projects" / args.project_id
    if not project_root.exists():
        print(f"error: project {args.project_id} not found", file=sys.stderr)
        return 2
    store = ProjectStore(project_root / "council.sqlite3")
    if store.get_task(args.task_id) is None:
        print(f"error: task {args.task_id} not found", file=sys.stderr)
        return 2
    rows = store.list_interactions(task_id=args.task_id)
    if not rows:
        print(f"(no interactions recorded for {args.task_id})")
        return 0
    max_chars = args.max_chars
    for r in rows:
        ts = r.created_at.isoformat() if r.created_at else "?"
        header = (
            f"--- #{r.id} {ts} {r.from_agent} -> {r.to_agent} "
            f"[{r.kind}] in={r.tokens_in} out={r.tokens_out} "
            f"${(r.cost_usd or 0.0):.6f} ---"
        )
        print(header)
        body = r.content or ""
        if max_chars and len(body) > max_chars:
            body = body[:max_chars] + f"\n... (truncated, {len(r.content)} chars total)"
        print(body)
        print()
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


def _find_project_dir(docs_root: Path, slug: str) -> Path | None:
    """Find project directory matching pattern YYYY-MM-DD-<slug>."""
    projects_dir = docs_root / "projects"
    if not projects_dir.exists():
        return None
    for d in projects_dir.iterdir():
        if d.is_dir() and d.name.endswith(f"-{slug}"):
            return d
    return None


def _project_from_dir(store: ProjectStore, project_dir: Path) -> Project | None:
    """Get project info from a directory by extracting from directory name."""
    # Extract project_id from directory name (format: YYYY-MM-DD-<slug>)
    project_id = project_dir.name
    # Extract title/slug from project_id
    parts = project_id.rsplit("-", 3)
    slug = parts[-1] if len(parts) >= 2 else project_id
    # Create a minimal Project object (we don't need to query the store)
    return Project(
        id=project_id,
        title=slug,
        status=ProjectStatus.PLANNING,
        root_path=str(project_dir),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def cmd_budget(args: argparse.Namespace) -> int:
    from omc.budget import Limits

    docs_root = _docs_root(args)
    project_dir = _find_project_dir(docs_root, args.slug)
    if project_dir is None:
        print(f"project {args.slug!r} not found under {docs_root}", file=sys.stderr)
        return 2
    store = ProjectStore(project_dir / "council.sqlite3")
    project = _project_from_dir(store, project_dir)
    if project is None:
        print(f"project {args.slug!r} not found under {docs_root}", file=sys.stderr)
        return 2
    total = store.project_cost_usd(project.id)
    breakdown = store.cost_breakdown_by_agent(project.id)
    limit = Limits().l4_project_usd

    print(f"project: {project.title}  (id={project.id})")
    print(f"spend:   ${total:.4f}  /  limit ${limit:.2f}  (L4)")
    if breakdown:
        print("by agent:")
        for agent, usd in sorted(breakdown.items(), key=lambda kv: -kv[1]):
            print(f"  {agent:<14} ${usd:.4f}")
    remaining = max(0.0, limit - total)
    print(f"remaining: ${remaining:.4f}")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    """Pack a project directory into a replayable tar.gz."""
    project_id = args.project_id
    docs = _docs_root(args)
    project_root = docs / "projects" / project_id
    if not project_root.exists():
        print(f"error: project {project_id} not found", file=sys.stderr)
        return 2
    out_path = Path(args.output) if args.output else (
        Path.cwd() / f"{project_id}.tar.gz"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, "w:gz") as tf:
        # Pack the project root verbatim; arcname uses project_id as the top
        # directory so `tar xzf` yields `./<project_id>/...`.
        tf.add(project_root, arcname=project_id)
    size = out_path.stat().st_size
    print(f"archived {project_id} -> {out_path} ({size:,} bytes)")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Restore a project from a tar.gz produced by `omc archive`."""
    src = Path(args.tarball)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 2
    docs = _docs_root(args)
    projects_dir = docs / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(src, "r:gz") as tf:
        names = tf.getnames()
        top_levels = {n.split("/", 1)[0] for n in names if n}
        if len(top_levels) != 1:
            print(
                f"error: archive must have a single top-level directory, "
                f"got {sorted(top_levels)!r}",
                file=sys.stderr,
            )
            return 3
        project_id = next(iter(top_levels))
        target = projects_dir / project_id
        if target.exists() and not args.force:
            print(
                f"error: {target} already exists (use --force to overwrite)",
                file=sys.stderr,
            )
            return 4
        # Safety: reject absolute paths and .. traversal
        for m in tf.getmembers():
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                print(
                    f"error: archive contains unsafe path {m.name!r}",
                    file=sys.stderr,
                )
                return 5
        if target.exists():
            import shutil
            shutil.rmtree(target)
        tf.extractall(projects_dir)
    print(f"imported {project_id} -> {target}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Cross-project rollup: task counts by status + USD spend."""
    docs = _docs_root(args)
    idx = IndexStore(docs / "index.sqlite3")
    projects = idx.list_projects()
    if not projects:
        print("no projects found under docs/")
        return 0

    header = f"{'project':<40}  {'status':<10}  {'tasks':>20}  {'cost':>10}"
    print(header)
    print("-" * len(header))
    total_cost = 0.0
    total_tasks = {"pending": 0, "running": 0, "done": 0, "blocked": 0}
    for p in projects:
        project_root = docs / "projects" / p.id
        db = project_root / "council.sqlite3"
        if not db.exists():
            print(f"{p.id:<40}  {p.status.value:<10}  {'(no db yet)':>20}")
            continue
        ps = ProjectStore(db)
        cost = ps.project_cost_usd(p.id)
        total_cost += cost
        counts = {"pending": 0, "running": 0, "done": 0, "blocked": 0}
        for t in ps.list_tasks():
            s = t.status.value
            if s in ("pending", "running"):
                counts[s] += 1
            elif s in ("accepted", "audit_passed", "review_passed"):
                counts["done"] += 1
            else:
                counts["blocked"] += 1
        for k, v in counts.items():
            total_tasks[k] += v
        summary = (
            f"p={counts['pending']} r={counts['running']} "
            f"d={counts['done']} b={counts['blocked']}"
        )
        print(f"{p.id:<40}  {p.status.value:<10}  {summary:>20}  ${cost:>8.4f}")
    print("-" * len(header))
    tot = (
        f"p={total_tasks['pending']} r={total_tasks['running']} "
        f"d={total_tasks['done']} b={total_tasks['blocked']}"
    )
    print(f"{'TOTAL':<40}  {'':<10}  {tot:>20}  ${total_cost:>8.4f}")
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
    parser.add_argument("--docs-root", default=None, help="path to docs root (default: cwd/docs)")
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

    p_plan = sub.add_parser(
        "plan",
        help="decompose requirement.md into tasks via Codex (seeds PENDING tasks)",
    )
    p_plan.add_argument("project_id")
    p_plan.add_argument(
        "--force", action="store_true",
        help="overwrite tasks that already exist",
    )
    p_plan.set_defaults(func=cmd_plan)

    p_task = sub.add_parser("task", help="manage tasks in a project")
    task_sub = p_task.add_subparsers(dest="task_cmd", required=True)
    p_task_add = task_sub.add_parser("add", help="seed a new PENDING task row")
    p_task_add.add_argument("project_id")
    p_task_add.add_argument("task_id")
    p_task_add.add_argument(
        "--path-whitelist",
        default="",
        help="comma-separated relative file paths the worker may touch",
    )
    p_task_add.add_argument(
        "--force", action="store_true", help="overwrite if task already exists"
    )
    p_task_add.set_defaults(func=cmd_task_add)

    p_mcp = sub.add_parser("mcp", help="run MCP stdio server for Claude Code")
    p_mcp.set_defaults(func=cmd_mcp)

    p_tail = sub.add_parser("tail", help="print recent agent interactions")
    p_tail.add_argument("project_id")
    p_tail.add_argument("--limit", type=int, default=20)
    p_tail.set_defaults(func=cmd_tail)

    p_report = sub.add_parser(
        "report", help="daily/weekly cost rollup; use --by-task for per-task attribution",
    )
    p_report.add_argument(
        "--period", choices=("day", "week", "all"), default="day",
    )
    p_report.add_argument("--by-task", action="store_true")
    p_report.set_defaults(func=cmd_report)

    p_scan = sub.add_parser(
        "scan", help="scan workspace for leaked secrets (regex + entropy)"
    )
    p_scan_group = p_scan.add_mutually_exclusive_group()
    p_scan_group.add_argument(
        "project_id", nargs="?", default=None,
        help="project id — scans docs/projects/<id>/workspace",
    )
    p_scan_group.add_argument(
        "--path", default=None,
        help="scan an arbitrary directory instead of a project workspace",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_replay = sub.add_parser(
        "replay", help="print full interaction chain for a single task (debugging)"
    )
    p_replay.add_argument("project_id")
    p_replay.add_argument("task_id")
    p_replay.add_argument(
        "--max-chars", type=int, default=2000,
        help="truncate each interaction body at N chars (0 = no limit)",
    )
    p_replay.set_defaults(func=cmd_replay)

    p_tmux = sub.add_parser("tmux", help="launch tmux observer panel for a project")
    p_tmux.add_argument("project_id")
    p_tmux.set_defaults(func=cmd_tmux)

    p_verify = sub.add_parser("verify", help="run milestone verify via claude -p")
    p_verify.add_argument("project_id")
    p_verify.set_defaults(func=cmd_verify)

    p_budget = sub.add_parser("budget", help="show project USD spend vs L4 limit")
    p_budget.add_argument("slug", help="project slug")
    p_budget.set_defaults(func=cmd_budget)

    p_stats = sub.add_parser(
        "stats", help="cross-project rollup: tasks by status + USD spend"
    )
    p_stats.set_defaults(func=cmd_stats)

    p_archive = sub.add_parser(
        "archive", help="pack a project directory into a replayable tar.gz"
    )
    p_archive.add_argument("project_id")
    p_archive.add_argument(
        "--output", "-o", default=None,
        help="output tarball path (default: ./<project_id>.tar.gz)",
    )
    p_archive.set_defaults(func=cmd_archive)

    p_import = sub.add_parser(
        "import", help="restore a project from a tarball produced by `omc archive`"
    )
    p_import.add_argument("tarball")
    p_import.add_argument(
        "--force", action="store_true",
        help="overwrite if the project directory already exists",
    )
    p_import.set_defaults(func=cmd_import)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
