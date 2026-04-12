# Phase 3c — L4 USD Budget Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire real USD cost computation through worker/auditor/codex calls, persist per-task and per-interaction, enforce the L4=$5 project-wide hard line via the existing `BudgetTracker`, and expose spend via `omc budget` CLI + `omc_budget` MCP tool.

**Architecture:** A tiny `pricing.py` module holds a per-model `$/MTok (in, out)` table, loaded from bundled defaults merged with an optional `~/.config/oh-my-council/prices.toml`. `compute_cost(model, tokens_in, tokens_out)` is called inside `real_worker`/`real_auditor` (the clients that *know* the model name) and the resulting `cost_usd` rides along on the output dataclasses. The `Dispatcher` then records cost to `BudgetTracker`, persists `cost_usd` into `interactions`/`tasks`, and checks `l4_exhausted()` before each expensive call — overrun short-circuits to `BUDGET_EXCEEDED`. CLI + MCP surfaces read aggregate spend from sqlite.

**Tech Stack:** Python 3.11+, tomllib (stdlib), existing litellm/sqlite3/FastMCP stack. No new deps.

---

## File Structure

**New files:**
- `src/omc/pricing.py` — price table + `compute_cost()`
- `tests/test_pricing.py`
- `tests/test_cli_budget.py`
- `tests/test_mcp_budget.py`
- `docs/phase3c-budget-setup.md` — Chinese runbook

**Modified:**
- `src/omc/clients/base.py` — add `tokens_in`, `tokens_out`, `cost_usd` to `WorkerOutput`, `AuditOutput`, `SpecOutput`, `ReviewOutput`
- `src/omc/clients/real_worker.py` — split in/out tokens, call `compute_cost`, carry `cost_usd`
- `src/omc/clients/real_auditor.py` — same
- `src/omc/clients/fake_worker.py`, `fake_auditor.py`, `fake_codex.py` — add zero cost fields (backward compatibility)
- `src/omc/clients/real_codex.py` — tokens=0, cost=0 (Codex CLI output doesn't expose tokens; tracked separately in γ)
- `src/omc/dispatcher.py` — record cost, L4 guard, propagate to store
- `src/omc/store/project.py` — add `project_cost_usd(project_id)` + `cost_breakdown_by_agent(project_id)` queries
- `src/omc/cli.py` — add `cmd_budget` + subparser
- `src/omc/mcp_server.py` — register `omc_budget` tool + prompt
- `tests/test_worker_real.py`, `tests/test_auditor_real.py` — assert new fields set
- `tests/test_dispatcher*.py` — assert cost persistence + L4 guard
- `pyproject.toml` — bump version minor

---

## Task 1: Price Table + Cost Calculator

**Files:**
- Create: `src/omc/pricing.py`
- Create: `tests/test_pricing.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pricing.py
"""Price table + compute_cost. See plan §Task 1."""

from __future__ import annotations

from pathlib import Path

from omc.pricing import DEFAULT_PRICES, ModelPrice, compute_cost, load_prices


def test_default_prices_include_known_models():
    assert "minimax-text-01" in DEFAULT_PRICES
    assert "glm-4.6" in DEFAULT_PRICES
    assert "gemini-2.5-flash" in DEFAULT_PRICES
    for p in DEFAULT_PRICES.values():
        assert p.in_usd_per_mtok >= 0
        assert p.out_usd_per_mtok >= 0


def test_compute_cost_basic():
    prices = {"m": ModelPrice(in_usd_per_mtok=1.0, out_usd_per_mtok=3.0)}
    # 1M in + 1M out = 1 + 3 = 4 USD
    assert compute_cost("m", 1_000_000, 1_000_000, prices) == 4.0
    # 500k in + 250k out = 0.5 + 0.75 = 1.25
    assert compute_cost("m", 500_000, 250_000, prices) == 1.25


def test_compute_cost_unknown_model_returns_zero():
    assert compute_cost("unknown-xyz", 10_000, 10_000, {}) == 0.0


def test_compute_cost_zero_tokens():
    prices = {"m": ModelPrice(in_usd_per_mtok=5.0, out_usd_per_mtok=5.0)}
    assert compute_cost("m", 0, 0, prices) == 0.0


def test_load_prices_merges_override_file(tmp_path: Path):
    override = tmp_path / "prices.toml"
    override.write_text(
        '[prices."minimax-text-01"]\n'
        'in_usd_per_mtok = 99.0\n'
        'out_usd_per_mtok = 199.0\n'
        '[prices."custom-model"]\n'
        'in_usd_per_mtok = 0.1\n'
        'out_usd_per_mtok = 0.2\n',
        encoding="utf-8",
    )
    prices = load_prices(override)
    # override wins
    assert prices["minimax-text-01"].in_usd_per_mtok == 99.0
    # new entry added
    assert prices["custom-model"].out_usd_per_mtok == 0.2
    # unmerged defaults still present
    assert "glm-4.6" in prices


def test_load_prices_missing_file_returns_defaults(tmp_path: Path):
    prices = load_prices(tmp_path / "nope.toml")
    assert prices == DEFAULT_PRICES
```

Run: `pytest tests/test_pricing.py -v`
Expected: FAIL (module missing).

- [ ] **Step 2: Implement pricing module**

```python
# src/omc/pricing.py
"""Per-model USD price table + cost calculator.

Defaults are hardcoded against public list prices (see docs/phase3c-budget-setup.md
for sources and refresh policy). User can override via
~/.config/oh-my-council/prices.toml with the same shape:

    [prices."minimax-text-01"]
    in_usd_per_mtok = 0.20
    out_usd_per_mtok = 1.10

Unknown models yield zero cost (warned but not fatal) so a new vendor can be
trialled without blocking the run; the user should add the model to the
override file once they confirm the spend pattern.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PRICES_PATH = Path.home() / ".config" / "oh-my-council" / "prices.toml"


@dataclass(slots=True, frozen=True)
class ModelPrice:
    in_usd_per_mtok: float
    out_usd_per_mtok: float


# Public list prices in USD per 1M tokens (in, out). Refresh when vendors change.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    # MiniMax
    "minimax-text-01":        ModelPrice(0.20, 1.10),
    "minimax-m1":             ModelPrice(0.40, 2.20),
    # Zhipu GLM
    "glm-4.6":                ModelPrice(0.60, 2.20),
    "glm-4.5":                ModelPrice(0.50, 2.00),
    "glm-4.5-air":            ModelPrice(0.20, 1.10),
    # Google Gemini
    "gemini-2.5-pro":         ModelPrice(1.25, 10.00),
    "gemini-2.5-flash":       ModelPrice(0.30, 2.50),
    "gemini-2.5-flash-lite":  ModelPrice(0.10, 0.40),
    # OpenAI (reference — Codex CLI doesn't expose usage yet, kept for manual use)
    "gpt-5-codex":            ModelPrice(1.25, 10.00),
    # Anthropic (reference — claude -p usage via API billing, not local meter)
    "claude-opus-4":          ModelPrice(15.00, 75.00),
    "claude-sonnet-4":        ModelPrice(3.00, 15.00),
    "claude-haiku-4":         ModelPrice(1.00, 5.00),
}


def compute_cost(
    model: str,
    tokens_in: int,
    tokens_out: int,
    prices: dict[str, ModelPrice],
) -> float:
    p = prices.get(model)
    if p is None:
        return 0.0
    return (tokens_in / 1_000_000) * p.in_usd_per_mtok + (
        tokens_out / 1_000_000
    ) * p.out_usd_per_mtok


def load_prices(path: Path | None = None) -> dict[str, ModelPrice]:
    target = path if path is not None else DEFAULT_PRICES_PATH
    merged = dict(DEFAULT_PRICES)
    if not target.exists():
        return merged
    with target.open("rb") as f:
        doc = tomllib.load(f)
    overrides = doc.get("prices", {})
    for name, entry in overrides.items():
        merged[name] = ModelPrice(
            in_usd_per_mtok=float(entry["in_usd_per_mtok"]),
            out_usd_per_mtok=float(entry["out_usd_per_mtok"]),
        )
    return merged
```

- [ ] **Step 3: Run tests to verify pass**

Run: `pytest tests/test_pricing.py -v`
Expected: 5 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/omc/pricing.py tests/test_pricing.py
git commit -m "feat(pricing): add model price table and compute_cost helper"
```

---

## Task 2: Token In/Out Breakdown on Client Outputs

**Files:**
- Modify: `src/omc/clients/base.py`
- Modify: `src/omc/clients/real_worker.py`
- Modify: `src/omc/clients/real_auditor.py`
- Modify: `src/omc/clients/fake_worker.py`
- Modify: `src/omc/clients/fake_auditor.py`
- Modify: `src/omc/clients/fake_codex.py`
- Modify: `src/omc/clients/real_codex.py`
- Modify: `tests/test_worker_real.py`
- Modify: `tests/test_auditor_real.py`

- [ ] **Step 1: Write failing test for real_worker cost field**

Append to `tests/test_worker_real.py`:

```python
def test_litellm_worker_populates_cost_usd(monkeypatch):
    """Worker output must include tokens_in/out and computed cost_usd."""
    from unittest.mock import MagicMock
    import omc.clients.real_worker as rw
    from omc.clients.real_worker import LiteLLMWorker
    from omc.config import Settings
    from omc.pricing import ModelPrice

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = '{"files": {"a.py": "pass\\n"}}'
    fake_resp.usage.prompt_tokens = 1_000_000
    fake_resp.usage.completion_tokens = 500_000
    fake_resp.usage.total_tokens = 1_500_000

    monkeypatch.setattr(rw.litellm, "completion", lambda **_: fake_resp)
    monkeypatch.setattr(rw, "load_prices", lambda: {
        "test-model": ModelPrice(in_usd_per_mtok=2.0, out_usd_per_mtok=4.0)
    })

    s = Settings(
        worker_vendor="x", worker_model="test-model",
        worker_api_base="http://x", worker_api_key="x",
    )
    out = LiteLLMWorker(s).write("T001", "dummy spec")

    assert out.tokens_in == 1_000_000
    assert out.tokens_out == 500_000
    assert out.tokens_used == 1_500_000
    # 1M*2 + 0.5M*4 = 2 + 2 = 4.0
    assert out.cost_usd == 4.0
```

Run: `pytest tests/test_worker_real.py::test_litellm_worker_populates_cost_usd -v`
Expected: FAIL (AttributeError: 'WorkerOutput' has no 'tokens_in').

- [ ] **Step 2: Extend output dataclasses**

Replace `src/omc/clients/base.py` contents entirely with:

```python
"""Protocols and shared types for LLM clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True, frozen=True)
class SpecOutput:
    task_id: str
    spec_md: str
    path_whitelist: list[str]
    tokens_used: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass(slots=True, frozen=True)
class WorkerOutput:
    task_id: str
    files: dict[str, str]
    tokens_used: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass(slots=True, frozen=True)
class ReviewOutput:
    task_id: str
    passed: bool
    review_md: str
    tokens_used: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass(slots=True, frozen=True)
class AuditOutput:
    task_id: str
    passed: bool
    audit_md: str
    tokens_used: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


class CodexClient(Protocol):
    def produce_spec(self, task_id: str, requirement: str) -> SpecOutput: ...
    def review(self, task_id: str, files: dict[str, str], spec_md: str) -> ReviewOutput: ...


class WorkerRunner(Protocol):
    def write(self, task_id: str, spec_md: str) -> WorkerOutput: ...


class Auditor(Protocol):
    def audit(self, task_id: str, files: dict[str, str]) -> AuditOutput: ...
```

- [ ] **Step 3: Wire pricing into `real_worker.py`**

Replace the `LiteLLMWorker.write` method body. Full file replacement:

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
from omc.pricing import compute_cost, load_prices

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
        usage = getattr(resp, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        tokens_total = int(getattr(usage, "total_tokens", tokens_in + tokens_out) or 0) if usage else 0
        cost = compute_cost(self.settings.worker_model, tokens_in, tokens_out, load_prices())
        return WorkerOutput(
            task_id=task_id,
            files=files,
            tokens_used=tokens_total,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )


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


_: WorkerRunner = LiteLLMWorker(Settings(  # noqa: F841
    worker_vendor="x", worker_model="x", worker_api_base="x", worker_api_key="x",
))
```

- [ ] **Step 4: Wire pricing into `real_auditor.py`**

Replace the `LiteLLMAuditor.audit` body — full file:

```python
"""LiteLLM-backed Auditor. Runs a security-focused review on worker files.
Unparseable responses fail closed (passed=False) — safer than skipping audit."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import litellm

from omc.clients.base import Auditor, AuditOutput
from omc.config import Settings
from omc.pricing import compute_cost, load_prices

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
        usage = getattr(resp, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        tokens_total = int(getattr(usage, "total_tokens", tokens_in + tokens_out) or 0) if usage else 0
        cost = compute_cost(self.settings.worker_model, tokens_in, tokens_out, load_prices())

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
                tokens_used=tokens_total, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost,
            )
        md = _render_md(task_id, passed, findings)
        return AuditOutput(
            task_id=task_id, passed=passed, audit_md=md,
            tokens_used=tokens_total, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost,
        )


def _render_md(task_id: str, passed: bool, findings: list[dict]) -> str:
    if passed and not findings:
        return f"# audit {task_id}\n\nno issues"
    lines = [f"# audit {task_id}", "", f"passed: {passed}", ""]
    for f in findings:
        lines.append(f"- [{f.get('severity','?')}] {f.get('path','?')}: {f.get('message','')}")
    return "\n".join(lines)


_: Auditor = LiteLLMAuditor(Settings(  # noqa: F841
    worker_vendor="x", worker_model="x", worker_api_base="x", worker_api_key="x",
))
```

- [ ] **Step 5: Add a parallel auditor cost test**

Append to `tests/test_auditor_real.py`:

```python
def test_litellm_auditor_populates_cost_usd(monkeypatch):
    from unittest.mock import MagicMock
    import omc.clients.real_auditor as ra
    from omc.clients.real_auditor import LiteLLMAuditor
    from omc.config import Settings
    from omc.pricing import ModelPrice

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = '{"passed": true, "findings": []}'
    fake_resp.usage.prompt_tokens = 400_000
    fake_resp.usage.completion_tokens = 100_000
    fake_resp.usage.total_tokens = 500_000

    monkeypatch.setattr(ra.litellm, "completion", lambda **_: fake_resp)
    monkeypatch.setattr(ra, "load_prices", lambda: {
        "audit-model": ModelPrice(in_usd_per_mtok=1.0, out_usd_per_mtok=5.0)
    })

    s = Settings(
        worker_vendor="x", worker_model="audit-model",
        worker_api_base="http://x", worker_api_key="x",
    )
    out = LiteLLMAuditor(s).audit("T001", {"a.py": "pass\n"})

    assert out.tokens_in == 400_000
    assert out.tokens_out == 100_000
    # 0.4*1 + 0.1*5 = 0.4 + 0.5 = 0.9
    assert abs(out.cost_usd - 0.9) < 1e-9
    assert out.passed is True
```

- [ ] **Step 6: Run full test suite**

Run: `pytest -q`
Expected: **99 passed** (97 baseline + 2 new). If any older test broke because `WorkerOutput(task_id=..., files=..., tokens_used=N)` now has extra default fields, that's fine — dataclass defaults preserve calls. If any test constructed dataclasses positionally past `tokens_used`, promote those calls to keyword args inline.

- [ ] **Step 7: Commit**

```bash
git add src/omc/clients/base.py src/omc/clients/real_worker.py \
        src/omc/clients/real_auditor.py \
        tests/test_worker_real.py tests/test_auditor_real.py
git commit -m "feat(clients): carry tokens_in/out + cost_usd on outputs"
```

---

## Task 3: Wire Cost Into Dispatcher + L4 Guard

**Files:**
- Modify: `src/omc/dispatcher.py`
- Modify: `src/omc/store/project.py`
- Create: `tests/test_dispatcher_budget.py`

Goal: every output's `cost_usd` feeds `BudgetTracker.record_cost`, rides through `_record` into `interactions.cost_usd`, aggregates onto `tasks.cost_usd`, and `l4_exhausted()` short-circuits the loop before any expensive call.

- [ ] **Step 1: Write failing L4 guard test**

Create `tests/test_dispatcher_budget.py`:

```python
"""L4 project-wide USD budget enforcement in Dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

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
    store.init_schema()
    store.upsert_project(project_id="p1", slug="p", requirement="r", created_at=datetime.now())
    md = MDLayout(tmp_path)
    md.init_skeleton()
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
```

Run: `pytest tests/test_dispatcher_budget.py -v`
Expected: FAIL — `cost_usd` not aggregated + no L4 guard.

- [ ] **Step 2: Extend `_record` + cost propagation in Dispatcher**

Edit `src/omc/dispatcher.py`:

1. Add `cost_usd: float = 0.0` parameter to `_record`, forward to `Interaction(...)`.
2. After every call to `codex.produce_spec` / `worker.write` / `codex.review` / `auditor.audit` / `codex.dispatch_escalation`, call `self.deps.budget.record_cost(output.cost_usd)` and include `cost_usd=output.cost_usd` when calling `_record(...)`.
3. At the top of the `while True` loop (right after `self.deps.budget.record_attempt(task_id)`), add an L4 guard:

```python
if self.deps.budget.l4_exhausted():
    self._transition(task, StateEvent.BUDGET_EXCEEDED)
    return
```

4. Repeat an L4 guard right after each `record_cost` to short-circuit mid-task.
5. In `_transition`, aggregate task cost from the tracker. Since `BudgetTracker._cost` is project-wide, keep task-local cost on the Task model by summing cost_usd from its interactions:

Replace `_transition` with:

```python
def _transition(self, task, event: StateEvent) -> None:
    new_status = next_state(task.status, event)
    task.status = new_status
    task.attempts = self.deps.budget.attempts(task.id)
    task.tokens_used = self.deps.budget.tokens(task.id)
    task.codex_escalated = self.deps.budget.codex_attempts(task.id)
    task.cost_usd = self.deps.store.task_cost_usd(task.id)
    task.updated_at = datetime.now()
    self.deps.store.upsert_task(task)
```

- [ ] **Step 3: Add `task_cost_usd` + `project_cost_usd` queries**

Edit `src/omc/store/project.py`, add methods on `ProjectStore`:

```python
def task_cost_usd(self, task_id: str) -> float:
    with self._conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(cost_usd),0) AS s FROM interactions WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    return float(row["s"] or 0.0)

def project_cost_usd(self, project_id: str) -> float:
    with self._conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(cost_usd),0) AS s FROM interactions WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    return float(row["s"] or 0.0)

def cost_breakdown_by_agent(self, project_id: str) -> dict[str, float]:
    with self._conn() as c:
        rows = c.execute(
            "SELECT from_agent, COALESCE(SUM(cost_usd),0) AS s "
            "FROM interactions WHERE project_id = ? GROUP BY from_agent",
            (project_id,),
        ).fetchall()
    return {r["from_agent"]: float(r["s"] or 0.0) for r in rows}
```

- [ ] **Step 4: Confirm Interaction.cost_usd is written**

Verify `append_interaction` already writes cost_usd (line ~87 in project.py per the pre-Phase 3c code). If not, fix it. The existing schema already has `cost_usd REAL`, and `Interaction.cost_usd: float | None` exists. The only gap is Dispatcher passing it through — handled in Step 2.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_dispatcher_budget.py -v`
Expected: 2 PASS.

Run: `pytest -q`
Expected: **101 passed** (99 + 2 new).

- [ ] **Step 6: Commit**

```bash
git add src/omc/dispatcher.py src/omc/store/project.py tests/test_dispatcher_budget.py
git commit -m "feat(dispatcher): propagate cost_usd and enforce L4 project budget"
```

---

## Task 4: `omc budget` CLI + `omc_budget` MCP Tool

**Files:**
- Modify: `src/omc/cli.py`
- Modify: `src/omc/mcp_server.py`
- Create: `tests/test_cli_budget.py`
- Create: `tests/test_mcp_budget.py`

- [ ] **Step 1: Write failing CLI test**

Create `tests/test_cli_budget.py`:

```python
"""`omc budget <project>` subcommand — prints spend summary."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from omc.cli import main
from omc.models import Interaction
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _seed_project(docs_root: Path, slug: str = "sample") -> str:
    project_id = "p1"
    project_dir = docs_root / "projects" / f"2026-04-12-{slug}"
    project_dir.mkdir(parents=True)
    store = ProjectStore(project_dir / "council.sqlite3")
    store.init_schema()
    store.upsert_project(
        project_id=project_id, slug=slug, requirement="demo",
        created_at=datetime.now(),
    )
    # Two interactions totaling $1.25
    store.append_interaction(Interaction(
        project_id=project_id, task_id="T001",
        from_agent="glm5", to_agent="orchestrator", kind="response",
        content="ok", tokens_in=1000, tokens_out=500, cost_usd=0.75,
    ))
    store.append_interaction(Interaction(
        project_id=project_id, task_id="T001",
        from_agent="codex", to_agent="orchestrator", kind="review",
        content="ok", tokens_in=500, tokens_out=200, cost_usd=0.50,
    ))
    md = MDLayout(project_dir)
    md.init_skeleton()
    return project_id


def test_budget_prints_total_and_breakdown(tmp_path, capsys):
    _seed_project(tmp_path)
    rc = main(["--docs-root", str(tmp_path), "budget", "sample"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "$1.25" in out or "1.25" in out
    assert "glm5" in out
    assert "codex" in out
    assert "$5.00" in out or "5.00" in out  # L4 limit shown


def test_budget_missing_project_returns_2(tmp_path, capsys):
    rc = main(["--docs-root", str(tmp_path), "budget", "nope"])
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()
```

Run: `pytest tests/test_cli_budget.py -v`
Expected: FAIL (no `budget` subcommand).

- [ ] **Step 2: Implement `cmd_budget`**

Edit `src/omc/cli.py`. Add near the other `cmd_*` handlers:

```python
def cmd_budget(args) -> int:
    from omc.budget import Limits

    docs_root = Path(args.docs_root)
    project_dir = _find_project_dir(docs_root, args.slug)
    if project_dir is None:
        print(f"project {args.slug!r} not found under {docs_root}", file=sys.stderr)
        return 2
    store = ProjectStore(project_dir / "council.sqlite3")
    project = _project_from_dir(store, project_dir)
    total = store.project_cost_usd(project.id)
    breakdown = store.cost_breakdown_by_agent(project.id)
    limit = Limits().l4_project_usd

    print(f"project: {project.slug}  (id={project.id})")
    print(f"spend:   ${total:.4f}  /  limit ${limit:.2f}  (L4)")
    if breakdown:
        print("by agent:")
        for agent, usd in sorted(breakdown.items(), key=lambda kv: -kv[1]):
            print(f"  {agent:<14} ${usd:.4f}")
    remaining = max(0.0, limit - total)
    print(f"remaining: ${remaining:.4f}")
    return 0
```

Add the subparser registration next to the other `subparsers.add_parser(...)` calls:

```python
p_budget = subparsers.add_parser("budget", help="show project USD spend vs L4 limit")
p_budget.add_argument("slug", help="project slug")
p_budget.set_defaults(func=cmd_budget)
```

(Use the existing `_find_project_dir` / `_project_from_dir` helpers already present in the file; if `_project_from_dir` doesn't exist yet, inline the project lookup using `store.get_project_by_slug(slug)` if available, or add a small helper that reads `requirement.md` + sqlite for project_id. Match existing patterns in `cmd_tail` / `cmd_verify`.)

- [ ] **Step 3: Run CLI tests**

Run: `pytest tests/test_cli_budget.py -v`
Expected: 2 PASS.

- [ ] **Step 4: Write failing MCP test**

Create `tests/test_mcp_budget.py`:

```python
"""MCP omc_budget tool."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from omc.mcp_server import _omc_budget_impl
from omc.models import Interaction
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _seed(docs_root: Path) -> None:
    pdir = docs_root / "projects" / "2026-04-12-ex"
    pdir.mkdir(parents=True)
    s = ProjectStore(pdir / "council.sqlite3")
    s.init_schema()
    s.upsert_project(project_id="pid", slug="ex", requirement="r", created_at=datetime.now())
    s.append_interaction(Interaction(
        project_id="pid", task_id=None, from_agent="glm5", to_agent="orchestrator",
        kind="response", content="x", cost_usd=1.5,
    ))
    MDLayout(pdir).init_skeleton()


def test_omc_budget_impl_returns_spend_and_limit(tmp_path):
    _seed(tmp_path)
    result = _omc_budget_impl(tmp_path, "ex")
    assert result["slug"] == "ex"
    assert abs(result["spend_usd"] - 1.5) < 1e-6
    assert result["limit_usd"] == 5.0
    assert "glm5" in result["by_agent"]


def test_omc_budget_impl_missing_project(tmp_path):
    result = _omc_budget_impl(tmp_path, "nope")
    assert "error" in result
```

Run: `pytest tests/test_mcp_budget.py -v`
Expected: FAIL (no `_omc_budget_impl`).

- [ ] **Step 5: Register MCP tool + prompt**

Edit `src/omc/mcp_server.py`. Add:

```python
def _omc_budget_impl(docs_root: Path, slug: str) -> dict:
    from omc.budget import Limits

    pdir = _find_project_dir(docs_root, slug)
    if pdir is None:
        return {"error": f"project {slug!r} not found"}
    store = ProjectStore(pdir / "council.sqlite3")
    project = _project_from_dir(store, pdir)
    return {
        "slug": project.slug,
        "project_id": project.id,
        "spend_usd": round(store.project_cost_usd(project.id), 6),
        "limit_usd": Limits().l4_project_usd,
        "remaining_usd": round(
            max(0.0, Limits().l4_project_usd - store.project_cost_usd(project.id)), 6
        ),
        "by_agent": {
            k: round(v, 6) for k, v in store.cost_breakdown_by_agent(project.id).items()
        },
    }
```

Register the tool inside `build_server`:

```python
@app.tool()
def omc_budget(slug: str) -> dict:
    """Return project USD spend vs L4 limit + per-agent breakdown."""
    return _omc_budget_impl(docs_root, slug)
```

And the prompt (mirrors the `omc_verify` pattern with explicit `name=`):

```python
@app.prompt(name="omc_budget")
def _prompt_omc_budget(slug: str) -> str:
    return (
        f"Show me the current USD spend for project {slug!r}. "
        f"Call the omc_budget tool with slug={slug!r} and report "
        f"spend, limit, remaining, and per-agent breakdown."
    )
```

- [ ] **Step 6: Run MCP tests**

Run: `pytest tests/test_mcp_budget.py -v`
Expected: 2 PASS.

Run: `pytest -q`
Expected: **105 passed** (101 + 4 new).

- [ ] **Step 7: Commit**

```bash
git add src/omc/cli.py src/omc/mcp_server.py \
        tests/test_cli_budget.py tests/test_mcp_budget.py
git commit -m "feat(cli,mcp): add omc budget + omc_budget tool"
```

---

## Task 5: Runbook

**Files:**
- Create: `docs/phase3c-budget-setup.md`

- [ ] **Step 1: Write runbook**

Create `docs/phase3c-budget-setup.md` with the following content:

```markdown
# Phase 3c — USD 预算追踪 Runbook

## 背景

- L4 = **$5 USD / 项目** 硬线（spec §Q7）。
- 单次 worker/auditor/codex 调用的实际花销由 `src/omc/pricing.py` 的价格表计算后写入 `interactions.cost_usd`，聚合到 `tasks.cost_usd` 与项目级 `SUM(cost_usd)`。
- 超过 L4 时 Dispatcher 把当前任务转为 `over_budget` 并退出。

## 价格表

默认值位于 `src/omc/pricing.py::DEFAULT_PRICES`（USD / 1M tokens, in/out）。覆盖方式：

1. `~/.config/oh-my-council/prices.toml`（0600）
2. 格式：

```toml
[prices."minimax-text-01"]
in_usd_per_mtok = 0.20
out_usd_per_mtok = 1.10

[prices."glm-4.6"]
in_usd_per_mtok = 0.60
out_usd_per_mtok = 2.20
```

3. 未在表中的模型 → 记 0 成本（不会报错，仅不计入预算）。建议新模型先试跑，确认 token 用量后再加入表。

## 查看当前花销

### CLI

```bash
omc budget <slug>
```

输出样例：

```
project: demo-refactor  (id=2026-04-12-demo-refactor)
spend:   $0.7342  /  limit $5.00  (L4)
by agent:
  glm5           $0.5021
  codex          $0.2000
  orchestrator   $0.0321
remaining: $4.2658
```

退出码：`0` = 正常，`2` = 项目不存在。

### MCP / slash

Claude Code 会话里：`/omc_budget <slug>`，会调用 `omc_budget` 工具返回结构化 dict。

## L4 触发行为

1. 每个 worker/auditor/review 调用后检查 `BudgetTracker.l4_exhausted()`。
2. 超线立即 `BUDGET_EXCEEDED` 事件，任务状态机转 `OVER_BUDGET`。
3. 其它任务不会自动停止 — 需要人工介入。后续 γ 考虑整体 abort。

## 不在 Phase 3c 范围

- Codex CLI 子进程的 token 目前返回 0（Codex CLI 还未暴露 usage），γ 再解决。
- Claude `-p` 调用计费走 Anthropic API 账本，本地表只作参考。
- 没有日/周 budget — 只有项目级 L4。
- 没有通知/报警 — 仅退出码 + 状态。

## 故障排查

| 症状 | 可能原因 |
|---|---|
| `spend=0` 但确认有调用 | 模型名未在价格表中；检查 `OMC_WORKER_MODEL` 与 `prices.toml` |
| 任务突然 `over_budget` | 确认 `prices.toml` 不是小数点错放（0.2 vs 2.0） |
| `omc budget` 找不到项目 | slug 没匹配到 `docs/projects/YYYY-MM-DD-<slug>/` 目录 |
```

- [ ] **Step 2: Commit**

```bash
git add docs/phase3c-budget-setup.md
git commit -m "docs: add Phase 3c budget runbook"
```

---

## Self-Review Notes

**Spec coverage:** L4=$5 (Q7) → Tasks 1+3; `cost_usd` schema (§5) → Task 2+3; `omc_budget` surface → Task 4; docs → Task 5.

**Placeholder scan:** no TBD/TODO strings. Helper `_find_project_dir` / `_project_from_dir` referenced in Task 4 Step 2 — implementer MUST match the existing pattern in `cmd_tail` / `cmd_verify`; do NOT invent new helpers if they already exist.

**Type consistency:** `cost_usd: float` on all outputs, `cost_usd: float | None` on Interaction (unchanged), `cost_usd: float` on Task (unchanged schema default 0.0). `ModelPrice` fields: `in_usd_per_mtok`, `out_usd_per_mtok` — used consistently across all tasks.

**Execution:** Use superpowers:subagent-driven-development. Tasks 1+2 one haiku subagent; Task 3 one haiku subagent; Tasks 4+5 one haiku subagent. Final code-reviewer before merge.
