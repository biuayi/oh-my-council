# Phase 3a — MCP Server + Slash Commands + `omc tmux` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Claude Code 通过 MCP 接入 oh-my-council，暴露 `/omc new / start / status` 等 slash commands，并提供 `omc tmux` 观察面板雏形。

**Architecture:** 基于 `mcp` Python SDK 的 `FastMCP` 框架，stdio 运行。`omc mcp` 子命令启动服务器。CLI 另加 `omc tail`（sqlite 拉最近 N 条 interactions）与 `omc tmux`（tmux 多 pane 启动器）。

**Tech Stack:** Python 3.11+, `mcp>=1.0`（新增依赖），stdlib `sqlite3` / `subprocess`，pytest。

---

## Scope

本子项目交付：
- `src/omc/mcp_server.py`：3 个 tools（`omc_status` / `omc_new` / `omc_start`）+ 6 个 prompts 骨架（new / plan / start / verify / status / tmux）
- `src/omc/cli.py`：新增 `omc mcp`、`omc tail`、`omc tmux` 子命令
- `docs/phase3a-mcp-setup.md`：Claude Code 注册 MCP 的 runbook

**显式非目标**（Phase 3b/c 做）：
- `claude -p` 里程碑验收（`omc verify` 工具现在只返回占位文案）
- CCB Claude-Codex-Bridge 协程
- L4 USD 预算追踪

---

## File Structure

| 路径 | 职责 |
|---|---|
| `src/omc/mcp_server.py`（新增）| FastMCP app；tools + prompts 注册 |
| `src/omc/cli.py`（改）| 新增 `cmd_mcp` / `cmd_tail` / `cmd_tmux` |
| `tests/test_mcp_server.py`（新增）| FastMCP tool 单测（同步调用） |
| `tests/test_cli_tail.py`（新增）| `omc tail` 子命令 |
| `tests/test_cli_tmux.py`（新增）| `omc tmux` 子命令（mock `subprocess.run`） |
| `tests/test_cli_mcp.py`（新增）| `omc mcp` 子命令（只验证入口调度；不启真实 stdio） |
| `docs/phase3a-mcp-setup.md`（新增）| 注册流程 |

---

## Task 1: Add MCP dependency + server scaffold

**Files:**
- Modify: `pyproject.toml`
- Create: `src/omc/mcp_server.py`
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: 加依赖**

`pyproject.toml` 的 `dependencies` 数组加：
```toml
    "mcp>=1.0,<2",
```
运行 `uv sync --extra dev`。

- [ ] **Step 2: 写失败测试 `tests/test_mcp_server.py`**

```python
"""Unit tests for the oh-my-council MCP server tools."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from omc.mcp_server import _omc_status_impl
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def test_status_returns_task_list(tmp_path: Path):
    docs = tmp_path / "docs"
    project_root = docs / "projects" / "p1"
    MDLayout(project_root).scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime(2026, 4, 12)
    store.upsert_task(Task(
        id="T1", project_id="p1", md_path="tasks/T1.md",
        status=TaskStatus.PENDING, path_whitelist=["src/generated/T1.py"],
        created_at=now, updated_at=now,
    ))

    result = _omc_status_impl(docs_root=docs, project_id="p1")
    assert result["project_id"] == "p1"
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["id"] == "T1"
    assert result["tasks"][0]["status"] == "PENDING"


def test_status_missing_project(tmp_path: Path):
    result = _omc_status_impl(docs_root=tmp_path / "docs", project_id="nope")
    assert result == {"error": "project not found: nope"}
```

- [ ] **Step 3: 跑测试确认失败** — `uv run pytest tests/test_mcp_server.py -v` → FAIL（模块不存在）

- [ ] **Step 4: 实现 `src/omc/mcp_server.py`**

```python
"""MCP server for oh-my-council.

Exposes tools (omc_status, omc_new, omc_start) and prompt templates
(new / plan / start / verify / status / tmux) over stdio. Launched via
`omc mcp`.

The `_*_impl` helpers are pure functions so they can be unit-tested
without the MCP transport.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from omc.models import Project, ProjectStatus, Task, TaskStatus
from omc.store.index import IndexStore
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _default_docs_root() -> Path:
    return Path.cwd() / "docs"


def _omc_status_impl(*, docs_root: Path, project_id: str) -> dict:
    project_root = docs_root / "projects" / project_id
    if not project_root.exists():
        return {"error": f"project not found: {project_id}"}
    store = ProjectStore(project_root / "council.sqlite3")
    tasks = []
    for row in store.list_tasks():
        tasks.append({
            "id": row.id,
            "status": row.status.name,
            "attempts": row.attempts,
            "tokens_used": row.tokens_used,
        })
    return {"project_id": project_id, "tasks": tasks}


def build_server(docs_root: Path | None = None) -> FastMCP:
    root = docs_root or _default_docs_root()
    app = FastMCP("oh-my-council")

    @app.tool()
    def omc_status(project_id: str) -> dict:
        """Return the task list + status for a project_id."""
        return _omc_status_impl(docs_root=root, project_id=project_id)

    return app


def run_stdio(docs_root: Path | None = None) -> None:
    """Blocking: run the FastMCP server over stdio."""
    build_server(docs_root).run(transport="stdio")
```

注意：需要 `ProjectStore.list_tasks()` 方法。如果 Phase 1/2 已有就直接用；没有就加一个（单行 `SELECT` 返回 `Task` 列表）。

- [ ] **Step 5: 如果 `list_tasks` 不存在，加到 `src/omc/store/project.py`**

```python
def list_tasks(self) -> list[Task]:
    cur = self._conn.execute("SELECT id FROM tasks ORDER BY id")
    return [self.get_task(row[0]) for row in cur.fetchall() if self.get_task(row[0])]
```

（若已存在且签名不同，调用方改成匹配现有的签名。）

- [ ] **Step 6: 跑测试通过** — `uv run pytest tests/test_mcp_server.py -v`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/omc/mcp_server.py tests/test_mcp_server.py src/omc/store/project.py
git commit -m "feat(mcp): add FastMCP server with omc_status tool"
```

---

## Task 2: Add `omc_new` and `omc_start` tools

**Files:**
- Modify: `src/omc/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

`omc_new` 封装 `cmd_init` 的逻辑（初始化项目目录 + sqlite schema）。
`omc_start` 封装 fake pipeline 跑一次任务（避免 MCP 调用打真实 API；真实 backend 走 CLI `omc run`）。

- [ ] **Step 1: 加测试**

```python
def test_new_creates_project(tmp_path: Path):
    from omc.mcp_server import _omc_new_impl
    docs = tmp_path / "docs"
    result = _omc_new_impl(docs_root=docs, slug="demo")
    assert "project_id" in result
    pid = result["project_id"]
    assert (docs / "projects" / pid / "council.sqlite3").exists()


def test_start_runs_fake_pipeline(tmp_path: Path):
    from omc.mcp_server import _omc_new_impl, _omc_start_impl
    docs = tmp_path / "docs"
    new_result = _omc_new_impl(docs_root=docs, slug="demo")
    pid = new_result["project_id"]

    # Seed a task
    from omc.models import Task, TaskStatus
    from omc.store.project import ProjectStore
    now = datetime(2026, 4, 12)
    store = ProjectStore(docs / "projects" / pid / "council.sqlite3")
    store.upsert_task(Task(
        id="T1", project_id=pid, md_path="tasks/T1.md",
        status=TaskStatus.PENDING,
        path_whitelist=["src/generated/T1.py"],
        created_at=now, updated_at=now,
    ))

    result = _omc_start_impl(docs_root=docs, project_id=pid, task_id="T1")
    assert result["task_id"] == "T1"
    assert result["status"] in ("ACCEPTED", "BLOCKED")
```

- [ ] **Step 2: 实现 `_omc_new_impl` 和 `_omc_start_impl`** 在 `src/omc/mcp_server.py`

```python
def _omc_new_impl(*, docs_root: Path, slug: str) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    project_id = f"{today}-{slug}"
    project_root = docs_root / "projects" / project_id
    idx = IndexStore(docs_root / "index.sqlite3")
    now = datetime.now()
    idx.upsert_project(Project(
        id=project_id, title=slug, status=ProjectStatus.PLANNING,
        root_path=str(project_root), created_at=now, updated_at=now,
    ))
    MDLayout(project_root).scaffold()
    ProjectStore(project_root / "council.sqlite3")
    MDLayout(project_root).write_requirement(f"# {slug}\n\n(fill in the requirement)\n")
    return {"project_id": project_id, "root": str(project_root)}


def _omc_start_impl(*, docs_root: Path, project_id: str, task_id: str) -> dict:
    from omc.budget import BudgetTracker, Limits
    from omc.clients.fake_auditor import FakeAuditor
    from omc.clients.fake_codex import FakeCodexClient
    from omc.clients.fake_worker import FakeWorkerRunner
    from omc.dispatcher import Dispatcher, DispatcherDeps

    project_root = docs_root / "projects" / project_id
    if not project_root.exists():
        return {"error": f"project not found: {project_id}"}
    md = MDLayout(project_root)
    store = ProjectStore(project_root / "council.sqlite3")
    if store.get_task(task_id) is None:
        return {"error": f"task not found: {task_id}"}
    workspace = project_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    deps = DispatcherDeps(
        store=store, md=md,
        codex=FakeCodexClient(), worker=FakeWorkerRunner(), auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=workspace,
    )
    Dispatcher(deps).run_once(task_id, requirement=md.read_requirement())
    got = store.get_task(task_id)
    return {"task_id": task_id, "status": got.status.name if got else "MISSING"}
```

加 `@app.tool()` 包装：
```python
    @app.tool()
    def omc_new(slug: str) -> dict:
        """Create a new oh-my-council project under docs/projects/."""
        return _omc_new_impl(docs_root=root, slug=slug)

    @app.tool()
    def omc_start(project_id: str, task_id: str) -> dict:
        """Run a task through the fake pipeline for smoke testing."""
        return _omc_start_impl(docs_root=root, project_id=project_id, task_id=task_id)
```

- [ ] **Step 3: 测试通过**

- [ ] **Step 4: Commit** `feat(mcp): add omc_new and omc_start tools`

---

## Task 3: `omc mcp` CLI subcommand

**Files:**
- Modify: `src/omc/cli.py`
- Create: `tests/test_cli_mcp.py`

- [ ] **Step 1: 测试**（验证 argparse 装配；不真起 stdio）

```python
from unittest.mock import patch

from omc.cli import main


def test_cli_mcp_dispatches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("omc.cli.run_stdio") as rs:
        rc = main(["mcp"])
    assert rc == 0
    rs.assert_called_once()
```

- [ ] **Step 2: 修改 `src/omc/cli.py`**

顶部 import 加：
```python
from omc.mcp_server import run_stdio
```

加 `cmd_mcp`：
```python
def cmd_mcp(args: argparse.Namespace) -> int:
    run_stdio(_docs_root())
    return 0
```

在 `main()` 注册：
```python
    p_mcp = sub.add_parser("mcp", help="run MCP stdio server for Claude Code")
    p_mcp.set_defaults(func=cmd_mcp)
```

- [ ] **Step 3: 测试通过**
- [ ] **Step 4: Commit** `feat(cli): add omc mcp subcommand for stdio MCP server`

---

## Task 4: `omc tail` — read recent interactions

**Files:**
- Modify: `src/omc/cli.py`
- Modify: `src/omc/store/project.py`（如需加 `recent_interactions`）
- Create: `tests/test_cli_tail.py`

- [ ] **Step 1: 在 `ProjectStore` 加 helper（如已存在则跳过）**

```python
def recent_interactions(self, limit: int = 20) -> list[Interaction]:
    cur = self._conn.execute(
        "SELECT project_id, task_id, from_agent, to_agent, kind, content, tokens_in, tokens_out "
        "FROM interactions ORDER BY rowid DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    return [Interaction(
        project_id=r[0], task_id=r[1], from_agent=r[2], to_agent=r[3],
        kind=r[4], content=r[5], tokens_in=r[6], tokens_out=r[7],
    ) for r in rows]
```

（列顺序需参照 `src/omc/store/project.py` 现有 `append_interaction` 的 SQL；以现有 schema 为准）

- [ ] **Step 2: 测试**

```python
from datetime import datetime
from pathlib import Path

from omc.cli import main
from omc.models import Interaction, Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def test_tail_prints_recent_interactions(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    pid = "p1"
    project_root = docs / "projects" / pid
    MDLayout(project_root).scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime(2026, 4, 12)
    store.upsert_task(Task(id="T1", project_id=pid, md_path="tasks/T1.md",
                           status=TaskStatus.PENDING, path_whitelist=[],
                           created_at=now, updated_at=now))
    store.append_interaction(Interaction(
        project_id=pid, task_id="T1", from_agent="codex", to_agent="orchestrator",
        kind="response", content="hello", tokens_in=None, tokens_out=100,
    ))

    rc = main(["tail", pid, "--limit", "5"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "codex" in captured.out
    assert "hello" in captured.out
```

- [ ] **Step 3: 实现 `cmd_tail` in `src/omc/cli.py`**

```python
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
```

注册：
```python
    p_tail = sub.add_parser("tail", help="print recent agent interactions")
    p_tail.add_argument("project_id")
    p_tail.add_argument("--limit", type=int, default=20)
    p_tail.set_defaults(func=cmd_tail)
```

- [ ] **Step 4: 测试通过**
- [ ] **Step 5: Commit** `feat(cli): add omc tail for recent interactions`

---

## Task 5: `omc tmux` — observer panel launcher

**Files:**
- Modify: `src/omc/cli.py`
- Create: `tests/test_cli_tmux.py`

**注：**真实 tmux 不跑在 CI 里；用 `subprocess.run` 且 mock。

- [ ] **Step 1: 测试**

```python
from unittest.mock import patch, call

from omc.cli import main


def test_tmux_builds_session_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "projects" / "p1").mkdir(parents=True)

    with patch("subprocess.run") as sr:
        sr.return_value.returncode = 0
        rc = main(["tmux", "p1"])
    assert rc == 0
    # Expect at least "new-session" and "split-window" calls
    commands = [c.args[0] for c in sr.call_args_list]
    joined = " ".join(" ".join(c) for c in commands)
    assert "new-session" in joined
    assert "split-window" in joined


def test_tmux_missing_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = main(["tmux", "nope"])
    assert rc == 2
```

- [ ] **Step 2: 实现 `cmd_tmux`**（5 pane 按 design spec §7）

```python
def cmd_tmux(args: argparse.Namespace) -> int:
    import subprocess
    project_root = _docs_root() / "projects" / args.project_id
    if not project_root.exists():
        print(f"error: project {args.project_id} not found", file=sys.stderr)
        return 2

    session = f"omc-{args.project_id}"
    db = project_root / "council.sqlite3"

    # Pane 1: empty (placeholder); panes 2-5 run tail / watch commands.
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
```

注册：
```python
    p_tmux = sub.add_parser("tmux", help="launch tmux observer panel for a project")
    p_tmux.add_argument("project_id")
    p_tmux.set_defaults(func=cmd_tmux)
```

- [ ] **Step 3: 测试通过**
- [ ] **Step 4: Commit** `feat(cli): add omc tmux observer panel launcher`

---

## Task 6: MCP prompts (slash commands)

**Files:**
- Modify: `src/omc/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

Claude Code 把 MCP `prompt` 暴露成 slash command（`/mcp__<server>__<prompt>`）。

- [ ] **Step 1: 测试**（`FastMCP` 的 `list_prompts` 存在）

```python
import asyncio

def test_server_registers_six_prompts():
    from omc.mcp_server import build_server
    app = build_server()
    prompts = asyncio.run(app.list_prompts())
    names = {p.name for p in prompts}
    assert {"omc-new", "omc-plan", "omc-start",
            "omc-verify", "omc-status", "omc-tmux"} <= names
```

- [ ] **Step 2: 在 `build_server` 注册 6 个 prompt**

```python
    @app.prompt()
    def omc_new(slug: str) -> str:
        """Start a new oh-my-council project."""
        return (f"Call the `omc_new` tool with slug=`{slug}`. "
                f"Then open `docs/projects/<id>/requirement.md` for the user to edit.")

    @app.prompt()
    def omc_plan() -> str:
        """(Phase 3b) Trigger Codex to produce task specs from requirement.md."""
        return "Not yet implemented — scheduled for Phase 3b (CCB bridge)."

    @app.prompt()
    def omc_start(project_id: str, task_id: str) -> str:
        """Run a task through the fake pipeline."""
        return f"Call `omc_start` with project_id=`{project_id}` task_id=`{task_id}`."

    @app.prompt()
    def omc_verify() -> str:
        """(Phase 3b) Milestone verify via `claude -p`."""
        return "Not yet implemented — scheduled for Phase 3b."

    @app.prompt()
    def omc_status(project_id: str) -> str:
        """Summarize task statuses for a project."""
        return f"Call `omc_status` with project_id=`{project_id}` and summarize the output."

    @app.prompt()
    def omc_tmux(project_id: str) -> str:
        """Launch the observer panel."""
        return f"In a shell, run: `omc tmux {project_id}`."
```

Note: FastMCP prompt names default to the function name — hyphens come from replacing `_` → `-` in the list output. Verify in test; if the SDK keeps underscores, update the assertion to use `{"omc_new", ...}`.

- [ ] **Step 3: 测试通过**
- [ ] **Step 4: Commit** `feat(mcp): register six slash-command prompts`

---

## Task 7: Setup docs

**Files:**
- Create: `docs/phase3a-mcp-setup.md`

- [ ] **Step 1: 写 `docs/phase3a-mcp-setup.md`**

内容应涵盖：
- 前置：`uv sync --extra dev` 装 `mcp` 包
- 在 Claude Code 注册：
  ```bash
  claude mcp add oh-my-council -- uv run omc mcp
  ```
  或手写 `~/.config/claude/mcp.json` 片段（给出示例）。
- 可用 tools：`omc_status` / `omc_new` / `omc_start`
- 可用 slash commands：`/mcp__oh-my-council__omc-new` 等（Claude Code UI 里简写成 `/omc-new`）
- 故障排查：`uv run omc mcp` 在终端手动跑 → 如能打印 `"serving stdio"` 类消息就绪
- 已知限制：`omc_verify` / `omc_plan` 是占位，Phase 3b 实装

- [ ] **Step 2: Commit** `docs: add Phase 3a MCP setup runbook`

---

## Task 8: Integration smoke — launch server subprocess, call list_tools

**Files:**
- Create: `tests/test_mcp_integration.py`

目的：证明服务器能真实起来，且 tools 列表非空。用 `mcp` SDK 的 client 去调（同一进程内，避免 subprocess 噪声）。

- [ ] **Step 1: 测试**

```python
import asyncio


def test_server_exposes_three_tools():
    from omc.mcp_server import build_server
    app = build_server()
    tools = asyncio.run(app.list_tools())
    names = {t.name for t in tools}
    assert {"omc_status", "omc_new", "omc_start"} <= names
```

- [ ] **Step 2: 测试通过**
- [ ] **Step 3: Commit** `test(mcp): smoke-test tool registration`

---

## Phase 3a Completion Criteria

- [ ] `uv run pytest` — 72（Phase 2 基线）+ ~10 新测试通过，slow 默认排除
- [ ] `uv run ruff check .` — 全部通过
- [ ] `uv run omc mcp` 能手动启动（退出 Ctrl+C），无异常
- [ ] `docs/phase3a-mcp-setup.md` 足以让新用户接入

Phase 3a 完成后：**Phase 3b 计划** —— `claude -p` 里程碑验收 + CCB bridge。Phase 3c：L4 USD 预算。

---

## Self-Review Notes (post-plan)

- **Scope coverage**: design spec §8 MVP 列表里 `MCP server + slash commands` / `omc tmux` 覆盖；`claude -p 里程碑` 和 `Auditor 独立 prompt` 推到 3b/3c。
- **No placeholders**: 每个 Step 有可执行代码或命令。
- **Type consistency**: `Task` / `TaskStatus` / `Interaction` / `ProjectStore` / `MDLayout` 全部使用 Phase 1/2 既有 API；仅新增 `list_tasks` / `recent_interactions`（小改）。
- **Risks**: 
  - `mcp` Python SDK API 可能与 `FastMCP.list_tools` 签名不完全一致 → 实现时若 `FastMCP` 方法名不同，子 agent 需查 SDK 源并调整。
  - tmux 在 WSL 不一定可用；`cmd_tmux` 测试仅 mock subprocess，不跑真实 tmux。
  - Windows / MacOS 上 `uv run omc mcp` 的 stdio 行为 — 暂不验证，仅 Linux/WSL 要求。

---

## Execution Handoff

Use superpowers:subagent-driven-development. 按 Task 1 → 8 顺序派 haiku 实现器，每 task 跑测试+ ruff。最终跑整 branch 的 review 再合并。
