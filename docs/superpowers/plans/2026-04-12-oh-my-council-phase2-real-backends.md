# oh-my-council Phase 2: Real Backends & Enforcement

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Phase 1 的 fake 客户端替换为真实后端（LiteLLM + Codex CLI），启用预算强制 (L1/L2/L3) 与异步并发池，交付能用真实 LLM 走通 1 个 Python 文件 + 1 个 pytest 的 E2E 能力。

**Architecture:** 保留 Phase 1 的 Protocol 边界；在 `src/omc/clients/` 新增 `real_*` 模块实现这些 Protocol。新增 `omc.config` 读 `~/.config/oh-my-council/.env`。Dispatcher 扩展出异步版并加入 L1/L2/L3 强制触发。新增幻觉门禁模块 (`gates/hallucination.py`)，在 Codex review 通过后再跑一次符号存在性校验。设计文档 §3 / §6 / §10.5 是本阶段的权威参考。

**Tech Stack:** LiteLLM (`litellm>=1.50`)、python-dotenv、stdlib subprocess (Codex CLI)、asyncio、pytest-asyncio (已安装)、httpx-responses 或 unittest.mock 对 LiteLLM 打桩。Python 3.11+。

**Non-goals for Phase 2:** MCP server、slash commands、里程碑 `claude -p` 验收、tmux 面板 —— 这些留给 Phase 3。

---

## Preconditions

- Phase 1 已合并入 `main`（`omc.models / state / store / gates / clients.fake_* / budget / dispatcher / cli` 全部就绪，39 测试通过）。
- `~/.config/oh-my-council/.env` 存在且权限 0600，包含 `OMC_WORKER_{VENDOR,MODEL,API_BASE,API_KEY}`。
- `codex` CLI 已安装且可在 `$PATH` 中执行。本地可用 `codex --version` 验证。

## File Structure (new in Phase 2)

Create:
- `src/omc/config.py` — env loader
- `src/omc/clients/real_worker.py` — LiteLLM WorkerRunner
- `src/omc/clients/real_auditor.py` — LiteLLM Auditor
- `src/omc/clients/codex_cli.py` — Codex CLI subprocess 封装（spec/review/escalation 三种子命令）
- `src/omc/gates/hallucination.py` — 引用符号校验门禁
- `src/omc/dispatcher_async.py` — 异步并发 Dispatcher（保留旧的 `dispatcher.py` 不动以便回归测试）

Modify:
- `src/omc/dispatcher.py` — 加入 L2/L3 强制触发（L1 已在 Phase 1 里有）
- `src/omc/cli.py` — 新增 `omc run <project> <task>` 使用真实客户端
- `pyproject.toml` — 加 `litellm` + `python-dotenv` 依赖

Add tests:
- `tests/test_config.py`
- `tests/test_real_worker.py`
- `tests/test_real_auditor.py`
- `tests/test_codex_cli.py`
- `tests/test_gates_hallucination.py`
- `tests/test_dispatcher_enforce.py`
- `tests/test_dispatcher_async.py`
- `tests/test_e2e_real.py` — 标 `@pytest.mark.slow`，默认不跑

---

## Task 1: 依赖 & Config Loader

**Files:**
- Modify: `pyproject.toml`
- Create: `src/omc/config.py`
- Create: `tests/test_config.py`

Responsibility: 新增运行期依赖；集中读取 `~/.config/oh-my-council/.env` 并暴露为 typed dataclass。

- [ ] **Step 1: 写失败测试 `tests/test_config.py`**

```python
import os
from pathlib import Path

import pytest

from omc.config import Settings, load_settings


def test_loads_from_explicit_path(tmp_path: Path):
    envfile = tmp_path / ".env"
    envfile.write_text(
        "OMC_WORKER_VENDOR=minimax\n"
        "OMC_WORKER_MODEL=MiniMax-M2.5\n"
        "OMC_WORKER_API_BASE=https://api.minimaxi.com/v1/chat/completions\n"
        "OMC_WORKER_API_KEY=sk-test\n"
    )
    s = load_settings(envfile)
    assert isinstance(s, Settings)
    assert s.worker_vendor == "minimax"
    assert s.worker_model == "MiniMax-M2.5"
    assert s.worker_api_base.startswith("https://")
    assert s.worker_api_key == "sk-test"


def test_missing_required_key_raises(tmp_path: Path):
    envfile = tmp_path / ".env"
    envfile.write_text("OMC_WORKER_VENDOR=minimax\n")
    with pytest.raises(KeyError):
        load_settings(envfile)


def test_default_path_fallback(monkeypatch, tmp_path: Path):
    envfile = tmp_path / ".env"
    envfile.write_text(
        "OMC_WORKER_VENDOR=minimax\n"
        "OMC_WORKER_MODEL=m\n"
        "OMC_WORKER_API_BASE=https://x\n"
        "OMC_WORKER_API_KEY=k\n"
    )
    monkeypatch.setenv("OMC_ENV_FILE", str(envfile))
    s = load_settings()
    assert s.worker_model == "m"
```

- [ ] **Step 2: 运行测试（应失败）**

```bash
uv run pytest tests/test_config.py -v
```
Expected: `ModuleNotFoundError: omc.config`

- [ ] **Step 3: 改 `pyproject.toml` 加运行期依赖**

`[project]` 的 `dependencies` 追加：
```toml
dependencies = [
  "litellm>=1.50,<2",
  "python-dotenv>=1.0,<2",
]
```

然后 `uv sync --extra dev` 刷新锁文件。

- [ ] **Step 4: 实现 `src/omc/config.py`**

```python
"""Runtime configuration. Reads ~/.config/oh-my-council/.env (or the path in
OMC_ENV_FILE). Secrets never land in the repo — see spec §10.5.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


DEFAULT_ENV_PATH = Path.home() / ".config" / "oh-my-council" / ".env"

_REQUIRED = (
    "OMC_WORKER_VENDOR",
    "OMC_WORKER_MODEL",
    "OMC_WORKER_API_BASE",
    "OMC_WORKER_API_KEY",
)


@dataclass(slots=True, frozen=True)
class Settings:
    worker_vendor: str
    worker_model: str
    worker_api_base: str
    worker_api_key: str
    codex_bin: str = "codex"
    codex_timeout_s: float = 120.0


def load_settings(path: Path | None = None) -> Settings:
    if path is None:
        override = os.environ.get("OMC_ENV_FILE")
        path = Path(override) if override else DEFAULT_ENV_PATH
    values = dict(dotenv_values(path))
    missing = [k for k in _REQUIRED if k not in values or not values[k]]
    if missing:
        raise KeyError(f"missing required env keys: {', '.join(missing)}")
    return Settings(
        worker_vendor=values["OMC_WORKER_VENDOR"],
        worker_model=values["OMC_WORKER_MODEL"],
        worker_api_base=values["OMC_WORKER_API_BASE"],
        worker_api_key=values["OMC_WORKER_API_KEY"],
        codex_bin=values.get("OMC_CODEX_BIN") or "codex",
        codex_timeout_s=float(values.get("OMC_CODEX_TIMEOUT_S") or 120.0),
    )
```

- [ ] **Step 5: 运行测试（应通过）**

```bash
uv run pytest tests/test_config.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/omc/config.py tests/test_config.py
git commit -m "feat(config): add dotenv-based Settings loader for Phase 2"
```

---

## Task 2: Real WorkerRunner (LiteLLM)

**Files:**
- Create: `src/omc/clients/real_worker.py`
- Create: `tests/test_real_worker.py`

Responsibility: 实现 `WorkerRunner` Protocol，调 LiteLLM 让远端模型按 spec 产出 file-per-task 输出。对外仍是 `write(task_id, spec_md) -> WorkerOutput`。LiteLLM 对 MiniMax/GLM 的 OpenAI 兼容接入：`model=f"openai/{settings.worker_model}"`、`api_base=settings.worker_api_base`、`api_key=settings.worker_api_key`。

**输出协议（Worker 必须遵守）：** 模型返回 JSON，形如
```json
{"files": {"src/generated/T001.py": "...python source...", "tests/test_T001.py": "..."}}
```
解析层要容忍 markdown ```json fence，但 schema 不通过就视为 WORKER_FAIL。

- [ ] **Step 1: 写失败测试 `tests/test_real_worker.py`**

```python
from unittest.mock import patch, MagicMock

import pytest

from omc.clients.real_worker import LiteLLMWorker
from omc.config import Settings


def _settings() -> Settings:
    return Settings(
        worker_vendor="minimax",
        worker_model="MiniMax-M2.5",
        worker_api_base="https://api.minimaxi.com/v1",
        worker_api_key="sk-test",
    )


def _mock_completion(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    resp.usage = MagicMock(total_tokens=123)
    return resp


def test_parses_valid_json_output():
    w = LiteLLMWorker(_settings())
    payload = '{"files": {"src/generated/T001.py": "x = 1\\n"}}'
    with patch("omc.clients.real_worker.litellm.completion",
               return_value=_mock_completion(payload)):
        out = w.write("T001", "# spec\n\nwrite x=1")
    assert out.task_id == "T001"
    assert out.files == {"src/generated/T001.py": "x = 1\n"}
    assert out.tokens_used == 123


def test_parses_fenced_json_output():
    w = LiteLLMWorker(_settings())
    payload = 'sure:\n```json\n{"files": {"a.py": "y=2\\n"}}\n```\n'
    with patch("omc.clients.real_worker.litellm.completion",
               return_value=_mock_completion(payload)):
        out = w.write("T001", "# spec")
    assert out.files == {"a.py": "y=2\n"}


def test_invalid_json_raises_worker_error():
    from omc.clients.real_worker import WorkerParseError
    w = LiteLLMWorker(_settings())
    with patch("omc.clients.real_worker.litellm.completion",
               return_value=_mock_completion("not json at all")):
        with pytest.raises(WorkerParseError):
            w.write("T001", "# spec")


def test_schema_violation_raises():
    from omc.clients.real_worker import WorkerParseError
    w = LiteLLMWorker(_settings())
    with patch("omc.clients.real_worker.litellm.completion",
               return_value=_mock_completion('{"wrongkey": 1}')):
        with pytest.raises(WorkerParseError):
            w.write("T001", "# spec")
```

- [ ] **Step 2: 运行测试（应失败）**

```bash
uv run pytest tests/test_real_worker.py -v
```
Expected: import errors.

- [ ] **Step 3: 实现 `src/omc/clients/real_worker.py`**

```python
"""LiteLLM-backed WorkerRunner. Talks to an OpenAI-compatible endpoint
(MiniMax / GLM / Gemini) through litellm. Output protocol: JSON object
with a top-level `files` map of relpath -> content."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import litellm

from omc.clients.base import WorkerOutput, WorkerRunner
from omc.config import Settings

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_SYSTEM_PROMPT = """You are a senior Python engineer executing one task in a
larger project. Respond ONLY with a single JSON object of the form
{"files": {"<relpath>": "<full file contents>", ...}}
Do not wrap your answer in prose; if you must, use a ```json fenced block.
Paths must stay within the task's path_whitelist. Write complete files, not diffs."""


class WorkerParseError(ValueError):
    """Worker produced a response we could not parse into a WorkerOutput."""


@dataclass(slots=True)
class LiteLLMWorker:
    settings: Settings

    def write(self, task_id: str, spec_md: str) -> WorkerOutput:
        resp = litellm.completion(
            model=f"openai/{self.settings.worker_model}",
            api_base=self.settings.worker_api_base,
            api_key=self.settings.worker_api_key,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": spec_md},
            ],
        )
        content = resp.choices[0].message.content or ""
        files = _extract_files(content)
        tokens = int(getattr(resp, "usage", None).total_tokens or 0) if getattr(resp, "usage", None) else 0
        return WorkerOutput(task_id=task_id, files=files, tokens_used=tokens)


def _extract_files(raw: str) -> dict[str, str]:
    candidate = raw.strip()
    m = _FENCE_RE.search(candidate)
    if m:
        candidate = m.group(1).strip()
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise WorkerParseError(f"worker output not valid JSON: {e}") from e
    files = obj.get("files")
    if not isinstance(files, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in files.items()
    ):
        raise WorkerParseError(f"worker output missing or wrong-shape 'files': {obj!r}")
    return files


_: WorkerRunner = LiteLLMWorker(Settings(  # Protocol conformance check
    worker_vendor="x", worker_model="x", worker_api_base="x", worker_api_key="x",
))
```

- [ ] **Step 4: 运行测试（应通过）**

```bash
uv run pytest tests/test_real_worker.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/omc/clients/real_worker.py tests/test_real_worker.py
git commit -m "feat(clients): add LiteLLM-backed WorkerRunner with JSON output protocol"
```

---

## Task 3: Real Auditor (LiteLLM)

**Files:**
- Create: `src/omc/clients/real_auditor.py`
- Create: `tests/test_real_auditor.py`

Responsibility: 实现 `Auditor` Protocol。对 worker 产出的 files map 做安全扫描（命令注入、硬编码密钥、eval/exec、路径穿越）。调同一个 LiteLLM endpoint（复用 WORKER credentials；Phase 3 再拆独立 AUDITOR_ 密钥）。输出也是 JSON：`{"passed": bool, "findings": [{...}]}`。

- [ ] **Step 1: 写失败测试 `tests/test_real_auditor.py`**

```python
from unittest.mock import patch, MagicMock

from omc.clients.real_auditor import LiteLLMAuditor
from omc.config import Settings


def _settings() -> Settings:
    return Settings(worker_vendor="x", worker_model="m", worker_api_base="u", worker_api_key="k")


def _mock(content: str, tokens: int = 42) -> MagicMock:
    r = MagicMock()
    r.choices = [MagicMock(message=MagicMock(content=content))]
    r.usage = MagicMock(total_tokens=tokens)
    return r


def test_audit_passes():
    a = LiteLLMAuditor(_settings())
    with patch("omc.clients.real_auditor.litellm.completion",
               return_value=_mock('{"passed": true, "findings": []}')):
        out = a.audit("T001", {"a.py": "x = 1"})
    assert out.passed is True
    assert "no issues" in out.audit_md.lower() or "passed" in out.audit_md.lower()
    assert out.tokens_used == 42


def test_audit_fails_on_findings():
    a = LiteLLMAuditor(_settings())
    payload = '{"passed": false, "findings": [{"path":"a.py","severity":"high","message":"eval()"}]}'
    with patch("omc.clients.real_auditor.litellm.completion", return_value=_mock(payload)):
        out = a.audit("T001", {"a.py": "eval(x)"})
    assert out.passed is False
    assert "eval" in out.audit_md


def test_audit_unparseable_response_defaults_to_fail():
    a = LiteLLMAuditor(_settings())
    with patch("omc.clients.real_auditor.litellm.completion", return_value=_mock("garbage")):
        out = a.audit("T001", {"a.py": "x=1"})
    assert out.passed is False
    assert "unparseable" in out.audit_md.lower()
```

- [ ] **Step 2: 运行测试（应失败）**

- [ ] **Step 3: 实现 `src/omc/clients/real_auditor.py`**

```python
"""LiteLLM-backed Auditor. Runs a security-focused review on worker files.
Unparseable responses fail closed (passed=False) — safer than skipping audit."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import litellm

from omc.clients.base import AuditOutput, Auditor
from omc.config import Settings

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_SYSTEM_PROMPT = """You are a security auditor. Scan the provided Python files
for: (1) command injection, (2) hardcoded credentials/secrets, (3) eval/exec
use on untrusted input, (4) path traversal (unvalidated ../ / os.path.join on
user input), (5) SQL injection. Respond ONLY as JSON:
{"passed": bool, "findings": [{"path": str, "severity": "low|medium|high", "message": str}]}
Return passed=true iff findings is empty."""


@dataclass(slots=True)
class LiteLLMAuditor:
    settings: Settings

    def audit(self, task_id: str, files: dict[str, str]) -> AuditOutput:
        corpus = "\n\n".join(f"### {p}\n```python\n{c}\n```" for p, c in files.items())
        resp = litellm.completion(
            model=f"openai/{self.settings.worker_model}",
            api_base=self.settings.worker_api_base,
            api_key=self.settings.worker_api_key,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": corpus},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        tokens = int(getattr(resp.usage, "total_tokens", 0) or 0) if getattr(resp, "usage", None) else 0

        m = _FENCE_RE.search(content)
        if m:
            content = m.group(1).strip()
        try:
            obj = json.loads(content)
            passed = bool(obj.get("passed", False))
            findings = obj.get("findings", [])
        except json.JSONDecodeError:
            return AuditOutput(
                task_id=task_id, passed=False,
                audit_md=f"# audit {task_id}\n\nunparseable auditor response; treating as fail.",
                tokens_used=tokens,
            )
        md = _render_md(task_id, passed, findings)
        return AuditOutput(task_id=task_id, passed=passed, audit_md=md, tokens_used=tokens)


def _render_md(task_id: str, passed: bool, findings: list[dict]) -> str:
    if passed and not findings:
        return f"# audit {task_id}\n\nno issues"
    lines = [f"# audit {task_id}", "", f"passed: {passed}", ""]
    for f in findings:
        lines.append(f"- [{f.get('severity','?')}] {f.get('path','?')}: {f.get('message','')}")
    return "\n".join(lines)


_: Auditor = LiteLLMAuditor(Settings(
    worker_vendor="x", worker_model="x", worker_api_base="x", worker_api_key="x",
))
```

- [ ] **Step 4: 运行测试（应通过）**
- [ ] **Step 5: Commit** `feat(clients): add LiteLLM-backed Auditor with fail-closed parsing`

---

## Task 4: Codex CLI Subprocess Wrapper (base)

**Files:**
- Create: `src/omc/clients/codex_cli.py`
- Create: `tests/test_codex_cli.py`

Responsibility: 把 `codex` 命令行封装为 `CodexCLI` 类，提供 `run_once(prompt, cwd, sandbox, timeout_s)` 方法；返回 stdout + returncode + duration。不解析业务语义，只做 subprocess 层。

Codex CLI 调用样例（参考 openai/codex 仓库）：
```
codex exec --sandbox read-only --approval-policy never "<prompt>"
codex exec --sandbox workspace-write --approval-policy never --cd <path> "<prompt>"
```

这一任务只封装 exec 调用与超时/错误处理；上层 `CodexClient` 的三种模式（spec/review/escalation）在后续 Task 5/6/8 里基于此构建。

- [ ] **Step 1: 写失败测试 `tests/test_codex_cli.py`**

```python
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from omc.clients.codex_cli import CodexCLI, CodexCLIError


def test_run_once_returns_stdout():
    cli = CodexCLI(bin="codex", timeout_s=5.0)
    fake = MagicMock(returncode=0, stdout="hello\n", stderr="")
    with patch("omc.clients.codex_cli.subprocess.run", return_value=fake) as mr:
        out = cli.run_once("say hello", cwd=Path("/tmp"), sandbox="read-only")
    assert out.stdout == "hello\n"
    assert out.returncode == 0
    # Assert the command shape
    args, kwargs = mr.call_args
    cmd = args[0]
    assert cmd[0] == "codex"
    assert "exec" in cmd
    assert "--sandbox" in cmd and "read-only" in cmd
    assert "--approval-policy" in cmd and "never" in cmd


def test_run_once_nonzero_raises():
    cli = CodexCLI(bin="codex", timeout_s=5.0)
    fake = MagicMock(returncode=2, stdout="", stderr="boom")
    with patch("omc.clients.codex_cli.subprocess.run", return_value=fake):
        with pytest.raises(CodexCLIError) as e:
            cli.run_once("x", cwd=Path("/tmp"), sandbox="read-only")
    assert "boom" in str(e.value)


def test_run_once_timeout_raises():
    import subprocess
    cli = CodexCLI(bin="codex", timeout_s=0.01)
    with patch("omc.clients.codex_cli.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd=["codex"], timeout=0.01)):
        with pytest.raises(CodexCLIError) as e:
            cli.run_once("x", cwd=Path("/tmp"), sandbox="read-only")
    assert "timeout" in str(e.value).lower()
```

- [ ] **Step 2: 运行测试（应失败）**
- [ ] **Step 3: 实现 `src/omc/clients/codex_cli.py`**

```python
"""Thin subprocess wrapper around the `codex` CLI. Higher-level CodexClient
composes spec/review/escalation on top of this primitive."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

Sandbox = str  # "read-only" | "workspace-write" | "danger-full-access"


class CodexCLIError(RuntimeError):
    """Codex CLI failed (nonzero exit, timeout, or spawn error)."""


@dataclass(slots=True, frozen=True)
class CodexResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass(slots=True)
class CodexCLI:
    bin: str = "codex"
    timeout_s: float = 120.0

    def run_once(
        self,
        prompt: str,
        *,
        cwd: Path,
        sandbox: Sandbox = "read-only",
    ) -> CodexResult:
        cmd = [
            self.bin, "exec",
            "--sandbox", sandbox,
            "--approval-policy", "never",
            "--cd", str(cwd),
            prompt,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise CodexCLIError(f"codex timeout after {self.timeout_s}s") from e
        except (OSError, FileNotFoundError) as e:
            raise CodexCLIError(f"codex spawn failed: {e}") from e
        if proc.returncode != 0:
            raise CodexCLIError(
                f"codex exit {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return CodexResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
```

- [ ] **Step 4: 测试通过**
- [ ] **Step 5: Commit** `feat(clients): add subprocess wrapper for codex CLI`

---

## Task 5: CodexClient.produce_spec (real)

**Files:**
- Create: `src/omc/clients/real_codex.py`
- Create: `tests/test_real_codex_spec.py`

Responsibility: `RealCodexClient.produce_spec(task_id, requirement) -> SpecOutput`。Prompt Codex 让它输出 `{"spec_md": "...", "path_whitelist": ["..."]}` JSON。用 Task 4 的 `CodexCLI.run_once`，sandbox=read-only。

- [ ] **Step 1: 写失败测试 `tests/test_real_codex_spec.py`**

```python
from pathlib import Path
from unittest.mock import MagicMock

from omc.clients.codex_cli import CodexResult
from omc.clients.real_codex import RealCodexClient


def _client(cli_mock) -> RealCodexClient:
    return RealCodexClient(cli=cli_mock, workspace_root=Path("/tmp/omc-test"))


def test_produce_spec_parses_json_output():
    raw = '{"spec_md": "# T001\\nwrite hello", "path_whitelist": ["src/hello.py"]}'
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    out = _client(cli).produce_spec("T001", "print hello")
    assert out.task_id == "T001"
    assert out.spec_md.startswith("# T001")
    assert out.path_whitelist == ["src/hello.py"]
    # verify sandbox is read-only for spec
    _, kwargs = cli.run_once.call_args
    assert kwargs.get("sandbox") == "read-only"


def test_produce_spec_tolerates_fence_and_preamble():
    raw = 'ok:\n```json\n{"spec_md": "# T1", "path_whitelist": ["a.py"]}\n```\n'
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    out = _client(cli).produce_spec("T1", "x")
    assert out.path_whitelist == ["a.py"]
```

- [ ] **Step 2-3-4: 运行 → 实现 → 再运行**

`src/omc/clients/real_codex.py`（本任务只实现 produce_spec 部分；review 与 escalation 在 Task 6/8 追加）：

```python
"""Real CodexClient backed by the codex CLI. Each mode (spec / review /
escalation) composes on top of CodexCLI.run_once with a mode-specific
sandbox and prompt template."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from omc.clients.base import CodexClient, ReviewOutput, SpecOutput
from omc.clients.codex_cli import CodexCLI

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class CodexParseError(ValueError):
    """Codex output did not match the expected JSON schema."""


@dataclass(slots=True)
class RealCodexClient:
    cli: CodexCLI
    workspace_root: Path

    def produce_spec(self, task_id: str, requirement: str) -> SpecOutput:
        prompt = _SPEC_PROMPT.format(task_id=task_id, requirement=requirement)
        res = self.cli.run_once(prompt, cwd=self.workspace_root, sandbox="read-only")
        obj = _parse_json(res.stdout)
        try:
            spec_md = obj["spec_md"]
            wl = list(obj["path_whitelist"])
        except (KeyError, TypeError) as e:
            raise CodexParseError(f"spec missing required keys: {obj!r}") from e
        return SpecOutput(task_id=task_id, spec_md=spec_md, path_whitelist=wl, tokens_used=0)

    def review(self, task_id: str, files: dict[str, str], spec_md: str) -> ReviewOutput:
        raise NotImplementedError  # Task 6

    # escalation (下场) added in Task 8


_SPEC_PROMPT = """You are the technical lead. Produce a per-file implementation
spec for task {task_id}. Requirement: {requirement!r}. Respond ONLY as JSON:
{{"spec_md": "<markdown spec for the worker>",
  "path_whitelist": ["<relative file path>", ...]}}
path_whitelist must list every file the worker is allowed to create or modify."""


def _parse_json(raw: str) -> dict:
    s = raw.strip()
    m = _FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise CodexParseError(f"codex output not valid JSON: {e}") from e
```

（末尾不加 Protocol conformance 检查，因为 `review` 还是 NotImplementedError；Task 7 追加后再挂 `_: CodexClient = ...`。）

- [ ] **Step 5: Commit** `feat(clients): add RealCodexClient.produce_spec via codex CLI`

---

## Task 6: CodexClient.review (real)

**Files:**
- Modify: `src/omc/clients/real_codex.py`
- Create: `tests/test_real_codex_review.py`

Responsibility: 实现 `RealCodexClient.review(task_id, files, spec_md) -> ReviewOutput`。Prompt 里附上 files 内容，要求 Codex 输出 `{"passed": bool, "review_md": "...", "symbols": [{"name": "...", "kind": "import"|"call", "file": "..."}]}`。`symbols` 字段给后续幻觉门禁用（Task 7），本任务只负责解析并存进 ReviewOutput 的 review_md（幻觉门禁清单作为 review_md 的一部分呈现）。

- [ ] **Step 1: 写测试**

```python
# tests/test_real_codex_review.py
from pathlib import Path
from unittest.mock import MagicMock

from omc.clients.codex_cli import CodexResult
from omc.clients.real_codex import RealCodexClient


def test_review_pass():
    raw = '{"passed": true, "review_md": "looks good", "symbols": []}'
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    c = RealCodexClient(cli=cli, workspace_root=Path("/tmp"))
    out = c.review("T001", {"a.py": "x=1\n"}, "# spec")
    assert out.passed is True
    assert "looks good" in out.review_md


def test_review_fail_with_findings():
    raw = '{"passed": false, "review_md": "missing error handling", "symbols": []}'
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    c = RealCodexClient(cli=cli, workspace_root=Path("/tmp"))
    out = c.review("T001", {"a.py": "x=1\n"}, "# spec")
    assert out.passed is False
    assert "missing" in out.review_md


def test_review_symbols_embedded_in_md():
    raw = ('{"passed": true, "review_md": "ok", '
           '"symbols": [{"name":"json.loads","kind":"call","file":"a.py"}]}')
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    c = RealCodexClient(cli=cli, workspace_root=Path("/tmp"))
    out = c.review("T001", {"a.py": "x=1\n"}, "# spec")
    assert "json.loads" in out.review_md
```

- [ ] **Step 2-3: 运行 → 实现**

把 `real_codex.py` 的 `review` 实现替换为：

```python
    def review(self, task_id: str, files: dict[str, str], spec_md: str) -> ReviewOutput:
        corpus = "\n\n".join(f"### {p}\n```python\n{c}\n```" for p, c in files.items())
        prompt = _REVIEW_PROMPT.format(spec_md=spec_md, corpus=corpus)
        res = self.cli.run_once(prompt, cwd=self.workspace_root, sandbox="read-only")
        obj = _parse_json(res.stdout)
        passed = bool(obj.get("passed", False))
        review_md = obj.get("review_md") or ""
        symbols = obj.get("symbols") or []
        self._last_symbols = symbols  # available to gates.hallucination
        if symbols:
            review_md += "\n\n## symbols\n" + "\n".join(
                f"- {s.get('kind','?')} `{s.get('name','?')}` in {s.get('file','?')}"
                for s in symbols
            )
        return ReviewOutput(task_id=task_id, passed=passed, review_md=review_md, tokens_used=0)
```

并在 `real_codex.py` 顶部给 `_REVIEW_PROMPT` 加定义：

```python
_REVIEW_PROMPT = """Review this task implementation. Spec:
{spec_md}

Files:
{corpus}

Respond ONLY as JSON:
{{"passed": bool,
  "review_md": "<markdown review notes>",
  "symbols": [{{"name": "<dotted name>", "kind": "import|call", "file": "<path>"}}, ...]}}
`symbols` must list EVERY imported name and EVERY external function call that
should exist in the project or its declared dependencies. Downstream validation
will grep the repo to confirm existence."""
```

然后在文件末尾（`_parse_json` 之下）加 Protocol conformance 检查：

```python
_: CodexClient = RealCodexClient(cli=CodexCLI(), workspace_root=Path("."))  # type-check at import
```

并在 `RealCodexClient` dataclass 里加 `_last_symbols: list = dataclass_field(default_factory=list)` — 或改用 `__post_init__`。最干净的办法是在 `__init__` 里手动初始化：

```python
@dataclass(slots=True)
class RealCodexClient:
    cli: CodexCLI
    workspace_root: Path
    _last_symbols: list = None  # overwritten in __post_init__

    def __post_init__(self) -> None:
        self._last_symbols = []
```

（或等价地用 `field(default_factory=list)` —— 选任一即可，确保类型 check 通过。）

- [ ] **Step 4: 测试通过**
- [ ] **Step 5: Commit** `feat(clients): add RealCodexClient.review with symbols payload`

---

## Task 7: Hallucination Gate

**Files:**
- Create: `src/omc/gates/hallucination.py`
- Create: `tests/test_gates_hallucination.py`

Responsibility: 对 Codex review 返回的 `symbols` 列表，逐条验证是否真实存在。验证策略：
- `kind == "import"`：检查该名字是否是 Python 内置 stdlib（用 `sys.stdlib_module_names`）、或在 `pyproject.toml` 的 `dependencies` / `optional-dependencies` 中、或在 repo 本地 `src/` 下能 import。
- `kind == "call"`：把 dotted name 拆成 module + attr，检查 module 可被解析且 attr 存在。（Phase 2 简化：只做第一层校验；递归更深的属性访问留给 Phase 3。）

返回与其他 gate 同构的 `GateResult(ok, offenders)`。

- [ ] **Step 1: 写测试**

```python
# tests/test_gates_hallucination.py
from pathlib import Path

from omc.gates.hallucination import check_symbols


def test_known_stdlib_import_ok(tmp_path: Path):
    res = check_symbols(
        [{"name": "json", "kind": "import", "file": "a.py"}],
        project_root=tmp_path,
    )
    assert res.ok is True


def test_unknown_import_flagged(tmp_path: Path):
    res = check_symbols(
        [{"name": "zzz_not_a_real_pkg", "kind": "import", "file": "a.py"}],
        project_root=tmp_path,
    )
    assert res.ok is False
    assert any("zzz_not_a_real_pkg" in o for o in res.offenders)


def test_known_call_ok(tmp_path: Path):
    res = check_symbols(
        [{"name": "json.loads", "kind": "call", "file": "a.py"}],
        project_root=tmp_path,
    )
    assert res.ok is True


def test_hallucinated_call_flagged(tmp_path: Path):
    res = check_symbols(
        [{"name": "json.nonexistent_fn", "kind": "call", "file": "a.py"}],
        project_root=tmp_path,
    )
    assert res.ok is False
    assert any("nonexistent_fn" in o for o in res.offenders)


def test_declared_dependency_counts_as_known(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["rich>=13"]\n'
    )
    res = check_symbols(
        [{"name": "rich", "kind": "import", "file": "a.py"}],
        project_root=tmp_path,
    )
    # We don't require `rich` to be installed in the test venv; declared dep = ok.
    assert res.ok is True
```

- [ ] **Step 2-3: 实现 `src/omc/gates/hallucination.py`**

```python
"""Hallucination gate: verify every symbol Codex claims exists actually does.

A symbol is "known" if one of:
  - kind == "import": matches sys.stdlib_module_names, or is declared in
    pyproject.toml [project].dependencies / optional-dependencies, or its
    top-level name resolves under project src/
  - kind == "call":  dotted form module.attr where module resolves as above
                     AND attr exists on the imported module (best-effort)
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import tomllib
from pathlib import Path

from omc.gates.path_whitelist import GateResult


def check_symbols(symbols: list[dict], project_root: Path) -> GateResult:
    declared = _declared_packages(project_root)
    stdlib = set(sys.stdlib_module_names)
    offenders: list[str] = []
    for s in symbols:
        kind = s.get("kind")
        name = s.get("name", "")
        if not name:
            offenders.append(f"empty symbol: {s!r}")
            continue
        top = name.split(".", 1)[0]
        if top in stdlib or top in declared:
            if kind == "call":
                if not _attr_exists(name):
                    offenders.append(f"call {name!r} attr missing")
            continue
        # not stdlib, not declared — try importing (covers local src/ packages)
        spec = importlib.util.find_spec(top)
        if spec is None:
            offenders.append(f"{kind} {name!r}: module {top!r} not found")
            continue
        if kind == "call" and not _attr_exists(name):
            offenders.append(f"call {name!r} attr missing")
    return GateResult(ok=not offenders, offenders=offenders)


def _declared_packages(root: Path) -> set[str]:
    pj = root / "pyproject.toml"
    if not pj.exists():
        return set()
    try:
        data = tomllib.loads(pj.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return set()
    proj = data.get("project", {})
    deps: list[str] = list(proj.get("dependencies", []))
    for group in proj.get("optional-dependencies", {}).values():
        deps.extend(group)
    out: set[str] = set()
    for raw in deps:
        # strip version specifiers
        token = raw.split(";", 1)[0]
        for sep in (">=", "<=", "==", "~=", ">", "<", "!="):
            if sep in token:
                token = token.split(sep, 1)[0]
                break
        out.add(token.strip().split("[", 1)[0])
    return out


def _attr_exists(dotted: str) -> bool:
    parts = dotted.split(".")
    if len(parts) < 2:
        return True  # bare module name already validated by caller
    module_name, attr = ".".join(parts[:-1]), parts[-1]
    try:
        mod = importlib.import_module(module_name)
    except ImportError:
        return False
    return hasattr(mod, attr)
```

- [ ] **Step 4: 测试通过**
- [ ] **Step 5: Commit** `feat(gates): add hallucination gate validating codex-reported symbols`

---

## Task 8: Codex Escalation (下场模式)

**Files:**
- Modify: `src/omc/clients/real_codex.py`
- Create: `tests/test_real_codex_escalation.py`

Responsibility: 给 `RealCodexClient` 加 `dispatch_escalation(task_id, spec_md, failing_files) -> dict[str, str]`：当 worker 连续失败 L1 次后，Codex 以 `workspace-write` sandbox 身份直接写代码，返回新 files 字典。

- [ ] **Step 1: 测试**

```python
# tests/test_real_codex_escalation.py
from pathlib import Path
from unittest.mock import MagicMock

from omc.clients.codex_cli import CodexResult
from omc.clients.real_codex import RealCodexClient


def test_escalation_uses_writable_sandbox():
    raw = '{"files": {"src/hello.py": "x=1\\n"}}'
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    c = RealCodexClient(cli=cli, workspace_root=Path("/tmp/omc-test"))
    out = c.dispatch_escalation("T001", "# spec", {"src/hello.py": "broken("})
    assert out == {"src/hello.py": "x=1\n"}
    _, kwargs = cli.run_once.call_args
    assert kwargs["sandbox"] == "workspace-write"
```

- [ ] **Step 2-3: 实现**

在 `real_codex.py` 里加：

```python
    def dispatch_escalation(
        self,
        task_id: str,
        spec_md: str,
        failing_files: dict[str, str],
    ) -> dict[str, str]:
        corpus = "\n\n".join(
            f"### {p}\n```python\n{c}\n```" for p, c in failing_files.items()
        )
        prompt = _ESCALATION_PROMPT.format(spec_md=spec_md, corpus=corpus)
        res = self.cli.run_once(prompt, cwd=self.workspace_root, sandbox="workspace-write")
        obj = _parse_json(res.stdout)
        files = obj.get("files")
        if not isinstance(files, dict):
            raise CodexParseError(f"escalation missing 'files': {obj!r}")
        return {k: v for k, v in files.items() if isinstance(k, str) and isinstance(v, str)}
```

并加 prompt 常量：

```python
_ESCALATION_PROMPT = """Workers failed repeatedly on this task. You now have
workspace-write access. Rewrite the file(s) from scratch to satisfy the spec.
Spec:
{spec_md}

Previous failing attempt:
{corpus}

Respond ONLY as JSON: {{"files": {{"<relpath>": "<contents>"}}}}"""
```

- [ ] **Step 4-5: 测试通过 + commit** `feat(clients): add codex dispatch_escalation (下场模式)`

---

## Task 9: Budget Enforcement in Dispatcher

**Files:**
- Modify: `src/omc/dispatcher.py`
- Create: `tests/test_dispatcher_enforce.py`

Responsibility: 把 Phase 1 只做追踪的 BudgetTracker 真正接进 Dispatcher 的决策：

| 触发 | 动作 |
|------|------|
| L1 耗尽（worker 重试 > 3） | 调 `CodexClient.dispatch_escalation`；记录 `record_codex_attempt` |
| L2 耗尽（escalation 也失败） | `StateEvent.ESCALATION_EXHAUSTED` → BLOCKED |
| L3 耗尽（task tokens > 限额） | `StateEvent.BUDGET_EXCEEDED` → OVER_BUDGET |
| 幻觉门禁失败 | `StateEvent.REVIEW_FAIL`（复用现有通路） |

Dispatcher 接受一个新的 `CodexClient` 扩展接口（`dispatch_escalation`）— 我们通过 `hasattr` 检测，fake 客户端不必提供。

- [ ] **Step 1: 测试 `tests/test_dispatcher_enforce.py`**

```python
from datetime import datetime
from pathlib import Path

from omc.budget import BudgetTracker, Limits
from omc.clients.base import SpecOutput, WorkerOutput
from omc.clients.fake_auditor import FakeAuditor
from omc.clients.fake_codex import FakeCodexClient
from omc.clients.fake_worker import FakeWorkerRunner
from omc.dispatcher import Dispatcher, DispatcherDeps
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _seed_task(store, tid="T1"):
    now = datetime(2026, 4, 12)
    store.upsert_task(Task(
        id=tid, project_id="p", md_path=f"tasks/{tid}.md",
        status=TaskStatus.PENDING, path_whitelist=["src/generated/T1.py"],
        created_at=now, updated_at=now,
    ))


class _EscalatingCodex(FakeCodexClient):
    """FakeCodexClient + dispatch_escalation method."""
    def __init__(self, escalation_files: dict[str, str]):
        super().__init__()
        self._esc = escalation_files
        self.called_escalation = False
    def dispatch_escalation(self, task_id, spec_md, failing_files):
        self.called_escalation = True
        return self._esc


def test_l1_triggers_codex_escalation(tmp_docs: Path):
    project_root = tmp_docs / "p"
    md = MDLayout(project_root); md.scaffold()
    store = ProjectStore(project_root / "c.sqlite3")
    # worker always produces wrong path → path gate always fails
    worker = FakeWorkerRunner(outputs={"T1": [
        WorkerOutput(task_id="T1", files={"src/evil.py": "x=1"})
    ]})
    codex = _EscalatingCodex(escalation_files={"src/generated/T1.py": "y=1\n"})
    deps = DispatcherDeps(
        store=store, md=md, codex=codex, worker=worker,
        auditor=FakeAuditor(), budget=BudgetTracker(Limits(l1_worker_retries=2)),
        project_source_root=project_root / "ws",
    )
    deps.project_source_root.mkdir(parents=True, exist_ok=True)
    _seed_task(store)

    Dispatcher(deps).run_once("T1", requirement="x")

    got = store.get_task("T1")
    assert codex.called_escalation is True
    assert got.status is TaskStatus.ACCEPTED  # escalation provided valid file
    assert got.codex_escalated == 1


def test_l2_exhausted_blocks_task(tmp_docs: Path):
    project_root = tmp_docs / "p"
    md = MDLayout(project_root); md.scaffold()
    store = ProjectStore(project_root / "c.sqlite3")
    worker = FakeWorkerRunner(outputs={"T1": [
        WorkerOutput(task_id="T1", files={"src/evil.py": "x=1"})
    ]})
    # escalation also produces wrong path → still fails path gate
    codex = _EscalatingCodex(escalation_files={"src/evil.py": "z=1\n"})
    deps = DispatcherDeps(
        store=store, md=md, codex=codex, worker=worker,
        auditor=FakeAuditor(),
        budget=BudgetTracker(Limits(l1_worker_retries=1, l2_codex_retries=1)),
        project_source_root=project_root / "ws",
    )
    deps.project_source_root.mkdir(parents=True, exist_ok=True)
    _seed_task(store)

    Dispatcher(deps).run_once("T1", requirement="x")

    got = store.get_task("T1")
    assert got.status is TaskStatus.BLOCKED


def test_l3_tokens_exceed_marks_over_budget(tmp_docs: Path):
    project_root = tmp_docs / "p"
    md = MDLayout(project_root); md.scaffold()
    store = ProjectStore(project_root / "c.sqlite3")
    # Worker reports huge token count on first call
    big = WorkerOutput(task_id="T1", files={"src/generated/T1.py": "x=1\n"}, tokens_used=10_000)
    worker = FakeWorkerRunner(outputs={"T1": [big]})
    codex = FakeCodexClient(specs={"T1": SpecOutput(
        task_id="T1", spec_md="# s", path_whitelist=["src/generated/T1.py"], tokens_used=0,
    )})
    deps = DispatcherDeps(
        store=store, md=md, codex=codex, worker=worker,
        auditor=FakeAuditor(), budget=BudgetTracker(Limits(l3_task_tokens=5_000)),
        project_source_root=project_root / "ws",
    )
    deps.project_source_root.mkdir(parents=True, exist_ok=True)
    _seed_task(store)

    Dispatcher(deps).run_once("T1", requirement="x")

    got = store.get_task("T1")
    assert got.status is TaskStatus.OVER_BUDGET
```

- [ ] **Step 2-3: 修改 `src/omc/dispatcher.py`**

关键变更（在现有 worker 循环内）：
1. 在每次 worker_out 之后，加 `if self.deps.budget.l3_exhausted(task_id): transition(BUDGET_EXCEEDED); return`.
2. path_whitelist 失败或 syntax 失败后：如果 `l1_exhausted` 且 `hasattr(codex, "dispatch_escalation")`，调用 escalation 把 worker_out.files 替换为 codex 的输出，`budget.record_codex_attempt`，`task.codex_escalated += 1`，然后用这份新 files 再走一次 path+syntax 检测。若仍失败且 `l2_exhausted` → `ESCALATION_EXHAUSTED` → BLOCKED。
3. 状态机：当前 `WORKER_FAIL` 从 RUNNING 回到 PENDING；增加 `BUDGET_EXCEEDED` 从任一 non-terminal 到 OVER_BUDGET 的转移（若 state.py 里还没有，要加）。

**先检查 state.py**：Phase 1 已定义 `BUDGET_EXCEEDED` 事件，但是不是对所有状态都有转移？在实施前用 `rg BUDGET_EXCEEDED src/omc/state.py` 确认；若仅 RUNNING→OVER_BUDGET，需要补 PENDING/REVIEW/AUDIT 到 OVER_BUDGET 的转移。在改 state.py 前写 pytest 覆盖。

- [ ] **Step 4: 运行 `uv run pytest` —— 所有 Phase 1 测试 + 新测试都通过。**
- [ ] **Step 5: Commit** `feat(dispatcher): enforce L1 escalation, L2 blocked, L3 over_budget`

---

## Task 10: Async Dispatcher Pool

**Files:**
- Create: `src/omc/dispatcher_async.py`
- Create: `tests/test_dispatcher_async.py`

Responsibility: 提供 `AsyncDispatcher` 用 asyncio.Semaphore 控制并发（默认 2）。包装 Phase 1 的同步 `Dispatcher.run_once` 到线程池以不阻塞（`asyncio.to_thread`）。客户端循环从 DB 拉 pending tasks，分配 worker，写回 DB。

- [ ] **Step 1: 测试**（只测并发语义，不跑真实 LLM）

```python
# tests/test_dispatcher_async.py
import asyncio
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
    md = MDLayout(project_root); md.scaffold()
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
```

- [ ] **Step 2-3: 实现 `src/omc/dispatcher_async.py`**

```python
"""Asyncio wrapper around the synchronous Dispatcher. Runs up to
`concurrency` tasks in parallel via asyncio.to_thread."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from omc.dispatcher import Dispatcher, DispatcherDeps


@dataclass(slots=True)
class AsyncDispatcher:
    deps: DispatcherDeps
    concurrency: int = 2

    async def run_batch(self, task_ids: list[str], requirement: str) -> None:
        sem = asyncio.Semaphore(self.concurrency)
        sync = Dispatcher(self.deps)

        async def _one(tid: str) -> None:
            async with sem:
                await asyncio.to_thread(sync.run_once, tid, requirement)

        await asyncio.gather(*[_one(t) for t in task_ids])
```

- [ ] **Step 4: 测试通过**
- [ ] **Step 5: Commit** `feat(dispatcher): add AsyncDispatcher with asyncio.to_thread + semaphore`

---

## Task 11: CLI `omc run` (real backends)

**Files:**
- Modify: `src/omc/cli.py`
- Create: `tests/test_cli_run.py`（只测装配，不打真实 API）

Responsibility: 新增 `omc run <project_id> <task_id>` subcommand：从 `omc.config.load_settings()` 读凭据，构造 `LiteLLMWorker` / `LiteLLMAuditor` / `RealCodexClient(CodexCLI(...))`，用 Phase 1 的同步 `Dispatcher` 跑一次。保留 `run-fake` 供烟测。

- [ ] **Step 1: 测试**（monkeypatch Dispatcher 以避免真实调用）

```python
# tests/test_cli_run.py
from pathlib import Path
from unittest.mock import patch

from omc.cli import main


def test_cli_run_wires_real_clients(tmp_path, monkeypatch):
    # Fake env file
    env = tmp_path / ".env"
    env.write_text(
        "OMC_WORKER_VENDOR=x\nOMC_WORKER_MODEL=m\n"
        "OMC_WORKER_API_BASE=https://x\nOMC_WORKER_API_KEY=k\n"
    )
    monkeypatch.setenv("OMC_ENV_FILE", str(env))

    # Set cwd so _docs_root() points somewhere writable
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "projects" / "p1").mkdir(parents=True)

    with patch("omc.cli.Dispatcher") as D, \
         patch("omc.cli.RealCodexClient") as RC, \
         patch("omc.cli.LiteLLMWorker") as LW, \
         patch("omc.cli.LiteLLMAuditor") as LA:
        D.return_value.run_once.return_value = None
        # pre-create task so cli.cmd_run doesn't bail
        from datetime import datetime
        from omc.models import Task, TaskStatus
        from omc.store.project import ProjectStore
        s = ProjectStore(tmp_path / "docs" / "projects" / "p1" / "council.sqlite3")
        now = datetime.now()
        s.upsert_task(Task(id="T1", project_id="p1", md_path="tasks/T1.md",
                           status=TaskStatus.PENDING, path_whitelist=["src/generated/T1.py"],
                           created_at=now, updated_at=now))

        rc = main(["run", "p1", "T1"])
    assert rc == 0
    assert RC.called and LW.called and LA.called
    D.return_value.run_once.assert_called_once()
```

- [ ] **Step 2-3: 修改 `src/omc/cli.py`**

在文件顶部 import：

```python
from omc.clients.codex_cli import CodexCLI
from omc.clients.real_codex import RealCodexClient
from omc.clients.real_worker import LiteLLMWorker
from omc.clients.real_auditor import LiteLLMAuditor
from omc.config import load_settings
```

加 `cmd_run`：

```python
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
        codex=RealCodexClient(cli=CodexCLI(bin=settings.codex_bin,
                                          timeout_s=settings.codex_timeout_s),
                              workspace_root=workspace),
        worker=LiteLLMWorker(settings),
        auditor=LiteLLMAuditor(settings),
        budget=BudgetTracker(Limits()),
        project_source_root=workspace,
    )
    Dispatcher(deps).run_once(task_id, requirement=md.read_requirement())
    got = store.get_task(task_id)
    print(f"task {task_id} -> {got.status if got else 'MISSING'}")
    return 0
```

在 `main` 的 subparser 注册：

```python
    p_real = sub.add_parser("run", help="run a task using real LLM backends")
    p_real.add_argument("project_id")
    p_real.add_argument("task_id")
    p_real.set_defaults(func=cmd_run)
```

- [ ] **Step 4-5: 测试通过 + commit** `feat(cli): add omc run with real LiteLLM + Codex backends`

---

## Task 12: E2E with Real API (marked slow)

**Files:**
- Create: `tests/test_e2e_real.py`
- Modify: `pyproject.toml` (add `slow` marker)

Responsibility: 默认不跑；用 `pytest -m slow` 才触发。环境里有 `~/.config/oh-my-council/.env` 时，走完整 pipeline：`omc init demo-e2e` → 手写 `requirement.md`（如 "实现 greet(name) 打印 hello 的函数并写 pytest"）→ `omc run ... T001` → 断言生成物存在且 `omc test` 通过。

为了避免写入真实 docs 目录，测试使用 tmp dir；不调用 CLI，而是直接构造 Dispatcher（便于断言）。

- [ ] **Step 1: 给 pyproject.toml 增加 marker**

```toml
[tool.pytest.ini_options]
markers = [
  "slow: tests that require real API keys and network access",
]
```

- [ ] **Step 2: 写测试 `tests/test_e2e_real.py`**

```python
import os
from datetime import datetime
from pathlib import Path

import pytest

from omc.budget import BudgetTracker, Limits
from omc.clients.codex_cli import CodexCLI
from omc.clients.real_codex import RealCodexClient
from omc.clients.real_worker import LiteLLMWorker
from omc.clients.real_auditor import LiteLLMAuditor
from omc.config import load_settings
from omc.dispatcher import Dispatcher, DispatcherDeps
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


pytestmark = pytest.mark.slow


@pytest.fixture
def settings():
    try:
        return load_settings()
    except (KeyError, FileNotFoundError):
        pytest.skip("no ~/.config/oh-my-council/.env")


def test_greet_end_to_end(tmp_path: Path, settings):
    project_root = tmp_path / "p"
    md = MDLayout(project_root); md.scaffold()
    md.write_requirement(
        "# Requirement\n\nImplement `greet(name: str) -> str` in "
        "src/generated/greet.py returning 'hello <name>'. Also write a "
        "pytest in tests/test_greet.py that asserts greet('world') == 'hello world'."
    )
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime.now()
    store.upsert_task(Task(
        id="T001", project_id="p", md_path="tasks/T001.md",
        status=TaskStatus.PENDING,
        path_whitelist=["src/generated/greet.py", "tests/test_greet.py"],
        created_at=now, updated_at=now,
    ))
    workspace = project_root / "ws"
    workspace.mkdir()

    codex = RealCodexClient(
        cli=CodexCLI(bin=settings.codex_bin, timeout_s=settings.codex_timeout_s),
        workspace_root=workspace,
    )
    deps = DispatcherDeps(
        store=store, md=md, codex=codex,
        worker=LiteLLMWorker(settings),
        auditor=LiteLLMAuditor(settings),
        budget=BudgetTracker(Limits()),
        project_source_root=workspace,
    )
    Dispatcher(deps).run_once("T001", requirement=md.read_requirement())

    got = store.get_task("T001")
    assert got.status is TaskStatus.ACCEPTED, f"status={got.status}"
    assert (workspace / "src/generated/greet.py").exists()
    assert (workspace / "tests/test_greet.py").exists()

    # Smoke-run the generated pytest
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(workspace / "tests"), "-q"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, f"generated tests failed: {r.stdout}{r.stderr}"
```

- [ ] **Step 3: 运行**

```bash
# 默认不跑 slow：
uv run pytest -q
# 跑真实 E2E（需要 .env + codex CLI + network）：
uv run pytest -m slow -v
```

- [ ] **Step 4: Commit** `test(e2e): add real-backend E2E gated by @slow marker`

---

## Task 13: Docs & Finalization

**Files:**
- Create: `docs/phase2-runbook.md`
- Modify: `docs/TODO.md`（如有 Phase 2 条目打勾）

Responsibility: 写一份简短 runbook：如何装依赖、如何填 `.env`、如何跑 `omc init / omc run / pytest -m slow`、已知限制（LiteLLM 对某些 provider 需要加 `openai/` 前缀等）。

- [ ] **Step 1: 写 `docs/phase2-runbook.md`**（～100 行；列出准备环境、触发命令、故障排查）。
- [ ] **Step 2: 更新 `docs/TODO.md`** 把 "Phase 2 真实 backends" 对应项删去或标记 done；保留 γ 条目不动。
- [ ] **Step 3: Commit** `docs: add Phase 2 runbook; update TODO`

---

## Phase 2 Completion Criteria

- [ ] 全部新增单测通过；Phase 1 的 39 个测试无回归：`uv run pytest`
- [ ] Ruff clean: `uv run ruff check src tests`
- [ ] `uv run pytest -m slow -v` 在有 `.env` 的机器上跑通（至少 1 次绿）
- [ ] `omc run <project> <task>` 用真实 LLM 把一个小需求生成 .py + test，并在 workspace 里跑通 pytest
- [ ] 状态机扩展项有覆盖：L1 触发 codex escalation、L2 耗尽转 BLOCKED、L3 token 超限转 OVER_BUDGET
- [ ] 幻觉门禁能在 Codex 写出假符号时 reject，并在 review.md 里列出 offenders

Phase 2 完成后：Phase 3 计划 —— MCP server + slash commands + `claude -p` 里程碑验收 + tmux 面板 + 多项目调度。

---

## Self-Review Notes (post-plan)

- **Spec coverage**: §3 单任务生命周期里所有环节（Codex spec / worker / gates / review / audit / budget 强制 / escalation）均有任务覆盖。§6.1 L1-L4 里 L1/L2/L3 全部接入 Dispatcher；L4（项目级 USD）留到有成本追踪后再做（Phase 3）。§6.2 幻觉门禁 ✓。§10.5 凭据加载 ✓。§11 风险里"Codex CLI 输出不稳"通过 `_parse_json` 的 fence-tolerant 解析 + NotImplemented 起步方式缓解。
- **Placeholder scan**: 无 TBD / fill in later / "similar to above"。
- **Type consistency**: 所有 `SpecOutput / ReviewOutput / WorkerOutput / AuditOutput` 字段沿用 Phase 1 的定义。`CodexClient` Protocol 在 Phase 1 只要求 `produce_spec + review`；`dispatch_escalation` 用 `hasattr` 动态探测，避免强迫 fake 客户端也要实现。
- **Ambiguity**: "LiteLLM for MiniMax" 明确用 `openai/` 前缀走 OpenAI 兼容接口；真·LiteLLM provider 形式（比如 `minimax/MiniMax-M2.5`）在 Phase 3 评估再切。
- **Deferred to Phase 3**: MCP server、slash commands、tmux、`claude -p` 验收、L4 USD 追踪、Worker A/B 比分、跨项目调度。

---

## Execution Handoff

Plan saved at `docs/superpowers/plans/2026-04-12-oh-my-council-phase2-real-backends.md`.

Two execution options:

1. **Subagent-Driven** — controller dispatches a fresh subagent per task, with combined spec+quality review after each; fast iteration, fits unattended mode.
2. **Inline Execution** — executing-plans in-session.

Default: **Subagent-Driven**（沿用 Phase 1 的做法）。
