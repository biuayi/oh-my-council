# Phase 3b — `claude -p` Milestone Verifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** 让 Claude 以非交互子进程 (`claude -p`) 形式做里程碑验收，把 MCP 里的 `omc_verify` 占位从 "Phase 3b" 升级成真调用。PM 角色的 token 消耗由里程碑数决定，而非任务数。

**Architecture:** 新增 `ClaudeCLI` 子进程封装（对标 `CodexCLI`），外包装 `MilestoneVerifier`：读 sqlite + MD 组装摘要 → `claude -p <prompt>` → 解析 `{"decision": "ACCEPT|NEED_DETAIL|REJECT", "summary": ..., "next_actions": [...]}`。`omc verify` CLI + MCP tool 暴露给用户。

**Tech Stack:** Python 3.11+, stdlib `subprocess` / `json`, pytest。

---

## Scope

交付：
- `src/omc/clients/claude_cli.py` — subprocess wrapper
- `src/omc/verifier.py` — `MilestoneVerifier` 组装 prompt + 调 Claude + 解析
- `src/omc/cli.py::cmd_verify` — `omc verify <project_id>` 子命令
- `src/omc/mcp_server.py` — 真 `omc_verify` tool + 升级 prompt
- 单元 + 集成测试（全 mock `subprocess.run`）
- `docs/phase3b-verify-setup.md`

**显式非目标**（γ 再做）：
- CCB (Claude-Codex-Bridge) 协程层
- 多里程碑依赖图 / DB 表（现版本 milestone = "整个项目此刻的 ACCEPTED 任务切片"）
- `claude -p` 重试失败后的升级裁决循环

---

## File Structure

| 路径 | 职责 |
|---|---|
| `src/omc/clients/claude_cli.py`（新）| `claude -p` subprocess 封装，超时/错误处理 |
| `src/omc/verifier.py`（新）| `MilestoneVerifier`：摘要 + prompt + 解析 |
| `src/omc/cli.py`（改）| 加 `cmd_verify` + subparser |
| `src/omc/mcp_server.py`（改）| `_omc_verify_impl` + `@app.tool()` 注册 + prompt 升级 |
| `tests/test_claude_cli.py`（新）| subprocess wrapper 单测 |
| `tests/test_verifier.py`（新）| prompt 组装 + 响应解析 |
| `tests/test_cli_verify.py`（新）| CLI 装配（mock Verifier） |
| `tests/test_mcp_verify.py`（新）| MCP tool 行为 |
| `docs/phase3b-verify-setup.md`（新）| 用户 runbook |

---

## Task 1: `ClaudeCLI` subprocess wrapper

**Files:**
- Create: `src/omc/clients/claude_cli.py`
- Create: `tests/test_claude_cli.py`

- [ ] **Step 1: 测试**（全 mock subprocess）

```python
"""Unit tests for ClaudeCLI subprocess wrapper."""

from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from omc.clients.claude_cli import ClaudeCLI, ClaudeCLIError, ClaudeResult


def test_run_once_success():
    cli = ClaudeCLI(bin="claude", timeout_s=60.0)
    with patch("subprocess.run") as sr:
        sr.return_value = MagicMock(
            returncode=0, stdout="hello\n", stderr="",
        )
        result = cli.run_once("be helpful")
    assert isinstance(result, ClaudeResult)
    assert result.stdout == "hello\n"
    assert result.returncode == 0
    cmd = sr.call_args.args[0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "be helpful" in cmd


def test_run_once_timeout():
    cli = ClaudeCLI(bin="claude", timeout_s=0.1)
    with patch("subprocess.run") as sr:
        sr.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=0.1)
        with pytest.raises(ClaudeCLIError, match="timeout"):
            cli.run_once("x")


def test_run_once_nonzero_exit():
    cli = ClaudeCLI()
    with patch("subprocess.run") as sr:
        sr.return_value = MagicMock(returncode=2, stdout="", stderr="boom")
        with pytest.raises(ClaudeCLIError, match="exit 2"):
            cli.run_once("x")


def test_run_once_spawn_failure():
    cli = ClaudeCLI(bin="nonexistent-binary")
    with patch("subprocess.run") as sr:
        sr.side_effect = FileNotFoundError("nope")
        with pytest.raises(ClaudeCLIError, match="spawn"):
            cli.run_once("x")
```

- [ ] **Step 2: 运行**（`uv run pytest tests/test_claude_cli.py -v` → 4 FAIL）

- [ ] **Step 3: 实现 `src/omc/clients/claude_cli.py`**（对标 `codex_cli.py`）

```python
"""Thin subprocess wrapper around the `claude` CLI (`claude -p` non-interactive).

Used by the MilestoneVerifier to delegate milestone acceptance to Claude
with minimal token cost (one short prompt per milestone, not per task).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class ClaudeCLIError(RuntimeError):
    """Claude CLI failed (nonzero exit, timeout, spawn error)."""


@dataclass(slots=True, frozen=True)
class ClaudeResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass(slots=True)
class ClaudeCLI:
    bin: str = "claude"
    timeout_s: float = 120.0

    def run_once(self, prompt: str) -> ClaudeResult:
        cmd = [self.bin, "-p", prompt]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise ClaudeCLIError(f"claude timeout after {self.timeout_s}s") from e
        except (OSError, FileNotFoundError) as e:
            raise ClaudeCLIError(f"claude spawn failed: {e}") from e
        if proc.returncode != 0:
            raise ClaudeCLIError(
                f"claude exit {proc.returncode}: "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        return ClaudeResult(
            stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode,
        )
```

- [ ] **Step 4: 测试通过**
- [ ] **Step 5: Commit** `feat(clients): add claude -p subprocess wrapper`

---

## Task 2: `MilestoneVerifier`

**Files:**
- Create: `src/omc/verifier.py`
- Create: `tests/test_verifier.py`

`MilestoneVerifier` 用 `ClaudeCLI` 做一次短调用：把 requirement + 所有任务 ID/状态 + （可选）近期 review/audit 摘要 塞进 prompt，要求 Claude 返回 JSON `{decision, summary, next_actions}`。

- [ ] **Step 1: 测试**

```python
"""Unit tests for MilestoneVerifier."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from omc.clients.claude_cli import ClaudeResult
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore
from omc.verifier import MilestoneVerifier, VerdictOutput


def _seed(tmp_path: Path, task_status: TaskStatus = TaskStatus.ACCEPTED):
    project_root = tmp_path / "p"
    md = MDLayout(project_root); md.scaffold()
    md.write_requirement("# greet\n\nImplement greet(name).")
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime(2026, 4, 12)
    store.upsert_task(Task(
        id="T1", project_id="p", md_path="tasks/T1.md",
        status=task_status,
        path_whitelist=["src/generated/greet.py"],
        created_at=now, updated_at=now,
    ))
    return project_root, md, store


def test_verifier_accept(tmp_path: Path):
    _, md, store = _seed(tmp_path)
    cli = MagicMock()
    cli.run_once.return_value = ClaudeResult(
        stdout=json.dumps({
            "decision": "ACCEPT",
            "summary": "greet function complete",
            "next_actions": [],
        }),
        stderr="", returncode=0,
    )
    verifier = MilestoneVerifier(cli=cli)
    result = verifier.verify(store=store, md=md, project_id="p")
    assert isinstance(result, VerdictOutput)
    assert result.decision == "ACCEPT"
    assert "greet" in result.summary
    # prompt sent to Claude mentions requirement + task
    prompt = cli.run_once.call_args.args[0]
    assert "greet(name)" in prompt
    assert "T1" in prompt


def test_verifier_need_detail(tmp_path: Path):
    _, md, store = _seed(tmp_path)
    cli = MagicMock()
    cli.run_once.return_value = ClaudeResult(
        stdout=json.dumps({
            "decision": "NEED_DETAIL",
            "summary": "unclear return format",
            "next_actions": ["ask user to clarify return type"],
        }),
        stderr="", returncode=0,
    )
    verifier = MilestoneVerifier(cli=cli)
    result = verifier.verify(store=store, md=md, project_id="p")
    assert result.decision == "NEED_DETAIL"
    assert result.next_actions == ["ask user to clarify return type"]


def test_verifier_unparseable_output_is_reject(tmp_path: Path):
    _, md, store = _seed(tmp_path)
    cli = MagicMock()
    cli.run_once.return_value = ClaudeResult(
        stdout="garbled non-json output", stderr="", returncode=0,
    )
    verifier = MilestoneVerifier(cli=cli)
    result = verifier.verify(store=store, md=md, project_id="p")
    # fail-closed: unparseable = REJECT
    assert result.decision == "REJECT"
    assert "unparseable" in result.summary.lower()


def test_verifier_handles_fence_wrapped_json(tmp_path: Path):
    _, md, store = _seed(tmp_path)
    cli = MagicMock()
    cli.run_once.return_value = ClaudeResult(
        stdout=(
            "Here's my verdict:\n\n```json\n"
            + json.dumps({
                "decision": "ACCEPT",
                "summary": "ok",
                "next_actions": [],
            })
            + "\n```\n"
        ),
        stderr="", returncode=0,
    )
    verifier = MilestoneVerifier(cli=cli)
    result = verifier.verify(store=store, md=md, project_id="p")
    assert result.decision == "ACCEPT"
```

- [ ] **Step 2: 实现 `src/omc/verifier.py`**

```python
"""MilestoneVerifier: short `claude -p` call deciding ACCEPT/NEED_DETAIL/REJECT
for a project milestone. Fail-closed: unparseable output → REJECT."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from omc.clients.claude_cli import ClaudeCLI
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


Decision = Literal["ACCEPT", "NEED_DETAIL", "REJECT"]


@dataclass(slots=True, frozen=True)
class VerdictOutput:
    decision: Decision
    summary: str
    next_actions: list[str] = field(default_factory=list)


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(raw: str) -> dict | None:
    """Try plain-json → fenced-json → first `{...}` blob. Return None on failure."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = _FENCE_RE.search(raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    # last resort: first { ... } balanced blob
    depth = 0
    start = -1
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


@dataclass(slots=True)
class MilestoneVerifier:
    cli: ClaudeCLI

    def verify(
        self, *, store: ProjectStore, md: MDLayout, project_id: str
    ) -> VerdictOutput:
        requirement = md.read_requirement()
        tasks = store.list_tasks()
        task_lines = "\n".join(
            f"- {t.id}: status={t.status.name} attempts={t.attempts}"
            for t in tasks
        )
        prompt = (
            f"You are acting as the PM verifying a milestone for project "
            f"`{project_id}`. Decide ACCEPT / NEED_DETAIL / REJECT and reply "
            f'with a single JSON object: {{"decision": "...", '
            f'"summary": "...", "next_actions": ["..."]}}.\n\n'
            f"## requirement.md\n{requirement}\n\n"
            f"## task list\n{task_lines or '(none)'}\n"
        )
        result = self.cli.run_once(prompt)
        data = _extract_json(result.stdout)
        if not data or "decision" not in data:
            return VerdictOutput(
                decision="REJECT",
                summary=f"unparseable claude output: {result.stdout[:200]}",
                next_actions=[],
            )
        decision = data.get("decision", "REJECT")
        if decision not in ("ACCEPT", "NEED_DETAIL", "REJECT"):
            decision = "REJECT"
        return VerdictOutput(
            decision=decision,
            summary=str(data.get("summary", "")),
            next_actions=list(data.get("next_actions", [])),
        )
```

- [ ] **Step 3: 测试通过**
- [ ] **Step 4: Commit** `feat(verifier): add MilestoneVerifier using claude -p`

---

## Task 3: `omc verify` CLI subcommand

**Files:**
- Modify: `src/omc/cli.py`
- Create: `tests/test_cli_verify.py`

- [ ] **Step 1: 测试**

```python
from unittest.mock import patch, MagicMock

from omc.cli import main
from omc.verifier import VerdictOutput


def test_verify_prints_decision(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "projects" / "p1").mkdir(parents=True)
    with patch("omc.cli.MilestoneVerifier") as MV:
        MV.return_value.verify.return_value = VerdictOutput(
            decision="ACCEPT", summary="all good", next_actions=[],
        )
        rc = main(["verify", "p1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ACCEPT" in out
    assert "all good" in out


def test_verify_need_detail_returns_3(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "projects" / "p1").mkdir(parents=True)
    with patch("omc.cli.MilestoneVerifier") as MV:
        MV.return_value.verify.return_value = VerdictOutput(
            decision="NEED_DETAIL", summary="x", next_actions=["ask about y"],
        )
        rc = main(["verify", "p1"])
    assert rc == 3


def test_verify_missing_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = main(["verify", "nope"])
    assert rc == 2
```

- [ ] **Step 2: 修改 `src/omc/cli.py`**

顶部 import：
```python
from omc.clients.claude_cli import ClaudeCLI
from omc.verifier import MilestoneVerifier
```

加 `cmd_verify`：
```python
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
```

注册：
```python
    p_verify = sub.add_parser("verify", help="run milestone verify via claude -p")
    p_verify.add_argument("project_id")
    p_verify.set_defaults(func=cmd_verify)
```

- [ ] **Step 3: 测试通过**
- [ ] **Step 4: Commit** `feat(cli): add omc verify for milestone acceptance`

---

## Task 4: MCP `omc_verify` tool + real prompt

**Files:**
- Modify: `src/omc/mcp_server.py`
- Create: `tests/test_mcp_verify.py`

替换 Phase 3a 的占位 prompt，注册真 tool。MCP tool 不直接起 `claude -p`（怕 MCP client 本身就是 Claude，绕一圈），只返回当前 requirement + 任务列表的摘要，供当前 Claude 会话判断。

- [ ] **Step 1: 测试**

```python
from datetime import datetime
from pathlib import Path

from omc.mcp_server import _omc_verify_impl
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def test_verify_impl_returns_summary(tmp_path: Path):
    docs = tmp_path / "docs"
    project_root = docs / "projects" / "p1"
    MDLayout(project_root).scaffold()
    MDLayout(project_root).write_requirement("# greet\n\nImplement greet(name).")
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime(2026, 4, 12)
    store.upsert_task(Task(
        id="T1", project_id="p1", md_path="tasks/T1.md",
        status=TaskStatus.ACCEPTED, path_whitelist=["src/generated/g.py"],
        created_at=now, updated_at=now,
    ))
    result = _omc_verify_impl(docs_root=docs, project_id="p1")
    assert result["project_id"] == "p1"
    assert "greet(name)" in result["requirement"]
    assert any(t["id"] == "T1" for t in result["tasks"])


def test_verify_impl_missing_project(tmp_path: Path):
    result = _omc_verify_impl(docs_root=tmp_path / "docs", project_id="nope")
    assert "error" in result
```

- [ ] **Step 2: 修改 `src/omc/mcp_server.py`**

加 `_omc_verify_impl`（reuse `_omc_status_impl` 的 store 读取 + `MDLayout.read_requirement`）：

```python
def _omc_verify_impl(*, docs_root: Path, project_id: str) -> dict:
    project_root = docs_root / "projects" / project_id
    if not project_root.exists():
        return {"error": f"project not found: {project_id}"}
    md = MDLayout(project_root)
    store = ProjectStore(project_root / "council.sqlite3")
    tasks = [
        {"id": t.id, "status": t.status.name, "attempts": t.attempts}
        for t in store.list_tasks()
    ]
    return {
        "project_id": project_id,
        "requirement": md.read_requirement(),
        "tasks": tasks,
        "hint": (
            "Decide ACCEPT / NEED_DETAIL / REJECT based on requirement vs "
            "task statuses. Use the `omc verify` CLI if you want a "
            "subprocess-Claude second opinion."
        ),
    }
```

在 `build_server` 加 `@app.tool()`：

```python
    @app.tool()
    def omc_verify(project_id: str) -> dict:
        """Return project summary so the current Claude session can render a
        milestone verdict (ACCEPT / NEED_DETAIL / REJECT)."""
        return _omc_verify_impl(docs_root=root, project_id=project_id)
```

升级原 `omc_verify` prompt（Phase 3a 的占位）：

```python
    @app.prompt(name="omc_verify")
    def omc_verify_prompt(project_id: str) -> str:
        """Milestone verify."""
        return (
            f"Call the `omc_verify` tool with project_id=`{project_id}`. "
            f"Read the requirement + task list it returns, decide ACCEPT / "
            f"NEED_DETAIL / REJECT, and explain briefly. For a subprocess "
            f"second opinion, suggest running `omc verify {project_id}`."
        )
```

注意：Phase 3a 的占位 prompt 函数名可能叫 `omc_verify`（作为 `name` 参数），确保只留一个。

- [ ] **Step 3: 测试通过**
- [ ] **Step 4: Commit** `feat(mcp): register real omc_verify tool + upgrade prompt`

---

## Task 5: Docs

**Files:**
- Create: `docs/phase3b-verify-setup.md`

- [ ] **Step 1: 写 runbook**

内容（~60 行）：
- 前置：`claude` CLI 装好可用（`claude --version`）
- 两种触发方式：
  1. CLI: `omc verify <project_id>` — orchestrator 自起 `claude -p` subprocess
  2. MCP tool: `omc_verify` — 把项目摘要喂给"当前 Claude 会话"
- 返回码：`0=ACCEPT, 3=NEED_DETAIL, 4=REJECT`
- 输出格式：Claude 必须回 `{"decision", "summary", "next_actions"}` JSON；否则 fail-closed = REJECT
- 故障排查：
  - `claude -p` 挂住 → 检查 auth
  - 解析失败 → 看 stdout 原文
- 已知限制：
  - 没有 milestone DB 表，整项目切片当一个里程碑
  - 失败不自动升级 Codex 下场（γ 再做）

- [ ] **Step 2: Commit** `docs: add Phase 3b verify runbook`

---

## Phase 3b Completion Criteria

- [ ] `uv run pytest` — 84（Phase 3a 基线）+ ~12 新测试通过
- [ ] `uv run ruff check .` — 全部通过
- [ ] `omc verify <project>` 在手动测试下能喂假 `claude` 二进制（用 `PATH` 劫持一个打印固定 JSON 的 shell 脚本）返回正确退出码 — 这是手动验证，不是自动 CI
- [ ] MCP `omc_verify` tool / prompt 注册成功并在 `docs/phase3b-verify-setup.md` 里有一段示例

Phase 3b 完成后：Phase 3c — L4 USD 预算追踪 + 模型价格表。

---

## Self-Review Notes

- **Spec coverage**: design spec §3 "里程碑级 Claude 短调用验收" ✓；§2 PM 角色 `claude -p` 短调用 ✓；§11 风险 "`claude -p` 输出解析" 通过 fence-tolerant 解析 + fail-closed REJECT 缓解。
- **No placeholders**: 每个 Step 有完整代码/命令/期望退出。
- **Type consistency**: `VerdictOutput` 与 `Decision` 在测试/CLI/实现三处一致；`ClaudeCLI` / `ClaudeResult` 对标现有 `CodexCLI` / `CodexResult`。
- **Ambiguity**: "milestone" 在 MVP 等于"项目当前所有任务"；DB 表与依赖图推到 γ。
