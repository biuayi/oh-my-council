# oh-my-council Phase 1: Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core state machine and persistence layer with fake LLM clients, proving the task lifecycle end-to-end without any real model calls.

**Architecture:** Pure Python stdlib + pytest. Sequential pipeline (async deferred to Phase 2). Fake clients produce deterministic outputs. Focus is on correctness of state transitions, sqlite/MD persistence, path whitelist + syntax gates, and Budgeter *tracking* (enforcement deferred). Real Codex CLI, LiteLLM workers, MCP server, and milestone Claude verification come in later phases.

**Tech Stack:** Python 3.11+, uv (package manager), pytest, ruff (lint), stdlib sqlite3, dataclasses.

**Spec reference:** `docs/superpowers/specs/2026-04-12-oh-my-council-design.md`

---

## File Structure

```
oh-my-council/
├── pyproject.toml
├── .python-version
├── src/
│   └── omc/
│       ├── __init__.py
│       ├── models.py               # dataclasses for Project/Task/Interaction/Checkpoint
│       ├── state.py                # pure state machine
│       ├── store/
│       │   ├── __init__.py
│       │   ├── schema.py           # SQL DDL constants
│       │   ├── index.py            # global index.sqlite3 wrapper
│       │   ├── project.py          # per-project council.sqlite3 wrapper
│       │   └── md.py               # MD layout creation + read/write
│       ├── gates/
│       │   ├── __init__.py
│       │   ├── path_whitelist.py   # enforce spec-declared paths
│       │   └── syntax.py           # fake syntax gate (stub returns OK)
│       ├── clients/
│       │   ├── __init__.py
│       │   ├── base.py             # protocol + types
│       │   ├── fake_codex.py       # deterministic spec + review
│       │   ├── fake_worker.py      # deterministic code output
│       │   └── fake_auditor.py     # deterministic audit verdict
│       ├── budget.py               # L1-L4 tracking (Phase 1: count only)
│       ├── dispatcher.py           # sequential task pipeline
│       └── cli.py                  # omc init / omc run-fake
└── tests/
    ├── conftest.py                 # shared fixtures (tmp_path-based)
    ├── test_models.py
    ├── test_state.py
    ├── test_store_index.py
    ├── test_store_project.py
    ├── test_store_md.py
    ├── test_gates_path.py
    ├── test_gates_syntax.py
    ├── test_clients_fakes.py
    ├── test_budget.py
    ├── test_dispatcher.py
    └── test_e2e_fake.py
```

Each module has one clear responsibility. `clients/fake_*` live beside `clients/base.py` so Phase 2 can add `real_codex.py` etc. without restructuring.

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `src/omc/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `.python-version`**

Create `.python-version`:
```
3.11
```

- [ ] **Step 2: Write `pyproject.toml`**

Create `pyproject.toml`:
```toml
[project]
name = "oh-my-council"
version = "0.1.0"
description = "Multi-agent orchestrator: Claude as PM, Codex as tech lead, GLM5 as worker"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.5",
]

[project.scripts]
omc = "omc.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/omc"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-ra -q"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM"]
```

- [ ] **Step 3: Write `src/omc/__init__.py`**

```python
"""oh-my-council: multi-agent orchestrator."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Write `tests/__init__.py`**

Empty file. Create it with:
```python
```

- [ ] **Step 5: Write `tests/conftest.py`**

```python
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def tmp_docs(tmp_path: Path) -> Iterator[Path]:
    """A temporary docs/ directory for a test run."""
    docs = tmp_path / "docs"
    docs.mkdir()
    yield docs
```

- [ ] **Step 6: Install deps and verify scaffold**

Run:
```bash
uv sync --extra dev
uv run pytest --collect-only
```
Expected: `collected 0 items` (no tests yet, but no errors).

Run:
```bash
uv run ruff check src tests
```
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .python-version src tests
git commit -m "chore: scaffold Python project with uv, pytest, ruff"
```

---

## Task 2: Data Models

**Files:**
- Create: `src/omc/models.py`
- Create: `tests/test_models.py`

Responsibility: Plain Python dataclasses matching spec §5.2 (sqlite schema) and spec §3 (lifecycle). No persistence logic here — just types.

- [ ] **Step 1: Write failing test `tests/test_models.py`**

```python
from datetime import datetime

from omc.models import (
    Interaction,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)


def test_project_minimal():
    p = Project(
        id="2026-04-12-demo",
        title="demo",
        status=ProjectStatus.PLANNING,
        root_path="docs/projects/2026-04-12-demo",
        created_at=datetime(2026, 4, 12, 0, 0, 0),
        updated_at=datetime(2026, 4, 12, 0, 0, 0),
    )
    assert p.id == "2026-04-12-demo"
    assert p.status is ProjectStatus.PLANNING


def test_task_default_counters():
    t = Task(
        id="T001",
        project_id="2026-04-12-demo",
        md_path="tasks/T001-hello.md",
        status=TaskStatus.PENDING,
        path_whitelist=["src/hello.py"],
    )
    assert t.attempts == 0
    assert t.codex_escalated == 0
    assert t.tokens_used == 0
    assert t.cost_usd == 0.0
    assert t.assignee is None


def test_interaction_requires_agents():
    i = Interaction(
        project_id="p",
        from_agent="orchestrator",
        to_agent="glm5",
        kind="request",
        content="hello",
    )
    assert i.from_agent == "orchestrator"
    assert i.tokens_in is None
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
uv run pytest tests/test_models.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'omc.models'`.

- [ ] **Step 3: Write `src/omc/models.py`**

```python
"""Dataclasses for oh-my-council domain objects.

Mirrors the sqlite schema in spec §5.2. Persistence is handled by
the `store/` package; this module is pure data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ProjectStatus(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ABORTED = "aborted"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    REVIEW = "review"
    AUDIT = "audit"
    BLOCKED = "blocked"
    ACCEPTED = "accepted"
    OVER_BUDGET = "over_budget"


class InteractionKind(StrEnum):
    REQUEST = "request"
    RESPONSE = "response"
    REVIEW = "review"
    AUDIT = "audit"
    HANDOFF = "handoff"
    ESCALATION = "escalation"


@dataclass(slots=True)
class Project:
    id: str
    title: str
    status: ProjectStatus
    root_path: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class Task:
    id: str
    project_id: str
    md_path: str
    status: TaskStatus
    path_whitelist: list[str]
    milestone_id: str | None = None
    assignee: str | None = None
    attempts: int = 0
    codex_escalated: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class Interaction:
    project_id: str
    from_agent: str
    to_agent: str
    kind: str
    content: str
    task_id: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    id: int | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class CompressionCheckpoint:
    project_id: str
    agent: str
    summary: str
    carry_forward: str  # JSON string
    task_id: str | None = None
    reason: str | None = None
    dropped_refs: str | None = None  # JSON string
    id: int | None = None
    created_at: datetime | None = None
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/test_models.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/omc/models.py tests/test_models.py
git commit -m "feat(models): add Project/Task/Interaction/Checkpoint dataclasses"
```

---

## Task 3: State Machine

**Files:**
- Create: `src/omc/state.py`
- Create: `tests/test_state.py`

Responsibility: Pure function `next_state(current, event) -> new_state`. No I/O. Encodes spec §3 lifecycle including escalation paths.

- [ ] **Step 1: Write failing test `tests/test_state.py`**

```python
import pytest

from omc.models import TaskStatus
from omc.state import StateEvent, InvalidTransition, next_state


def test_pending_to_running_on_start():
    assert next_state(TaskStatus.PENDING, StateEvent.WORKER_START) == TaskStatus.RUNNING


def test_running_to_review_on_worker_done():
    assert next_state(TaskStatus.RUNNING, StateEvent.WORKER_DONE) == TaskStatus.REVIEW


def test_review_to_audit_on_review_pass():
    assert next_state(TaskStatus.REVIEW, StateEvent.REVIEW_PASS) == TaskStatus.AUDIT


def test_audit_to_accepted_on_audit_pass():
    assert next_state(TaskStatus.AUDIT, StateEvent.AUDIT_PASS) == TaskStatus.ACCEPTED


def test_review_fail_goes_back_to_pending():
    assert next_state(TaskStatus.REVIEW, StateEvent.REVIEW_FAIL) == TaskStatus.PENDING


def test_running_budget_exceeded_goes_to_over_budget():
    assert (
        next_state(TaskStatus.RUNNING, StateEvent.BUDGET_EXCEEDED)
        == TaskStatus.OVER_BUDGET
    )


def test_running_blocked_on_escalation_exhausted():
    assert (
        next_state(TaskStatus.RUNNING, StateEvent.ESCALATION_EXHAUSTED)
        == TaskStatus.BLOCKED
    )


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransition):
        next_state(TaskStatus.ACCEPTED, StateEvent.WORKER_START)
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
uv run pytest tests/test_state.py -v
```
Expected: FAIL, `No module named 'omc.state'`.

- [ ] **Step 3: Write `src/omc/state.py`**

```python
"""Task state machine (pure). See spec §3."""

from __future__ import annotations

from enum import StrEnum

from omc.models import TaskStatus


class StateEvent(StrEnum):
    WORKER_START = "worker_start"
    WORKER_DONE = "worker_done"
    WORKER_FAIL = "worker_fail"
    REVIEW_PASS = "review_pass"
    REVIEW_FAIL = "review_fail"
    AUDIT_PASS = "audit_pass"
    AUDIT_FAIL = "audit_fail"
    BUDGET_EXCEEDED = "budget_exceeded"
    ESCALATION_EXHAUSTED = "escalation_exhausted"


class InvalidTransition(Exception):
    pass


_TRANSITIONS: dict[tuple[TaskStatus, StateEvent], TaskStatus] = {
    (TaskStatus.PENDING, StateEvent.WORKER_START): TaskStatus.RUNNING,
    (TaskStatus.RUNNING, StateEvent.WORKER_DONE): TaskStatus.REVIEW,
    (TaskStatus.RUNNING, StateEvent.WORKER_FAIL): TaskStatus.PENDING,
    (TaskStatus.RUNNING, StateEvent.BUDGET_EXCEEDED): TaskStatus.OVER_BUDGET,
    (TaskStatus.RUNNING, StateEvent.ESCALATION_EXHAUSTED): TaskStatus.BLOCKED,
    (TaskStatus.REVIEW, StateEvent.REVIEW_PASS): TaskStatus.AUDIT,
    (TaskStatus.REVIEW, StateEvent.REVIEW_FAIL): TaskStatus.PENDING,
    (TaskStatus.REVIEW, StateEvent.ESCALATION_EXHAUSTED): TaskStatus.BLOCKED,
    (TaskStatus.AUDIT, StateEvent.AUDIT_PASS): TaskStatus.ACCEPTED,
    (TaskStatus.AUDIT, StateEvent.AUDIT_FAIL): TaskStatus.PENDING,
    (TaskStatus.AUDIT, StateEvent.ESCALATION_EXHAUSTED): TaskStatus.BLOCKED,
}


def next_state(current: TaskStatus, event: StateEvent) -> TaskStatus:
    key = (current, event)
    if key not in _TRANSITIONS:
        raise InvalidTransition(f"no transition from {current} on {event}")
    return _TRANSITIONS[key]
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/test_state.py -v
```
Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/omc/state.py tests/test_state.py
git commit -m "feat(state): add pure task state machine with escalation events"
```

---

## Task 4: Store — Schema Constants

**Files:**
- Create: `src/omc/store/__init__.py`
- Create: `src/omc/store/schema.py`

Responsibility: Centralize SQL DDL so both index and project stores share it (and tests can reset schemas cleanly).

- [ ] **Step 1: Write `src/omc/store/__init__.py`**

```python
"""Persistence layer: sqlite wrappers + MD layout helpers."""
```

- [ ] **Step 2: Write `src/omc/store/schema.py`**

```python
"""SQL DDL for oh-my-council. See spec §5.2."""

INDEX_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL,
    root_path   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

PROJECT_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    milestone_id    TEXT,
    md_path         TEXT NOT NULL,
    status          TEXT NOT NULL,
    assignee        TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    codex_escalated INTEGER NOT NULL DEFAULT 0,
    tokens_used     INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0.0,
    path_whitelist  TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    task_id     TEXT,
    from_agent  TEXT NOT NULL,
    to_agent    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    content     TEXT NOT NULL,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    cost_usd    REAL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compression_checkpoints (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT NOT NULL,
    task_id       TEXT,
    agent         TEXT NOT NULL,
    reason        TEXT,
    summary       TEXT NOT NULL,
    carry_forward TEXT NOT NULL,
    dropped_refs  TEXT,
    created_at    TEXT NOT NULL
);
"""
```

- [ ] **Step 3: Commit**

```bash
git add src/omc/store/__init__.py src/omc/store/schema.py
git commit -m "feat(store): add DDL constants for index and project schemas"
```

---

## Task 5: Store — Global Index

**Files:**
- Create: `src/omc/store/index.py`
- Create: `tests/test_store_index.py`

Responsibility: `IndexStore` wraps `docs/index.sqlite3` with `upsert_project` and `list_projects`.

- [ ] **Step 1: Write failing test `tests/test_store_index.py`**

```python
from datetime import datetime
from pathlib import Path

from omc.models import Project, ProjectStatus
from omc.store.index import IndexStore


def test_upsert_and_list(tmp_docs: Path):
    store = IndexStore(tmp_docs / "index.sqlite3")
    now = datetime(2026, 4, 12, 0, 0, 0)
    p = Project(
        id="2026-04-12-alpha",
        title="alpha",
        status=ProjectStatus.PLANNING,
        root_path="docs/projects/2026-04-12-alpha",
        created_at=now,
        updated_at=now,
    )
    store.upsert_project(p)

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0].id == "2026-04-12-alpha"
    assert projects[0].status is ProjectStatus.PLANNING


def test_upsert_replaces_existing(tmp_docs: Path):
    store = IndexStore(tmp_docs / "index.sqlite3")
    now = datetime(2026, 4, 12, 0, 0, 0)
    p = Project(
        id="x",
        title="x",
        status=ProjectStatus.PLANNING,
        root_path="r",
        created_at=now,
        updated_at=now,
    )
    store.upsert_project(p)

    p.status = ProjectStatus.RUNNING
    store.upsert_project(p)

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0].status is ProjectStatus.RUNNING
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
uv run pytest tests/test_store_index.py -v
```
Expected: FAIL.

- [ ] **Step 3: Write `src/omc/store/index.py`**

```python
"""Global project index (docs/index.sqlite3). See spec §5.2."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from omc.models import Project, ProjectStatus
from omc.store.schema import INDEX_DDL


class IndexStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(INDEX_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_project(self, p: Project) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO projects (id, title, status, root_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title      = excluded.title,
                    status     = excluded.status,
                    root_path  = excluded.root_path,
                    updated_at = excluded.updated_at
                """,
                (
                    p.id,
                    p.title,
                    p.status.value,
                    p.root_path,
                    p.created_at.isoformat(),
                    p.updated_at.isoformat(),
                ),
            )

    def list_projects(self) -> list[Project]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, title, status, root_path, created_at, updated_at "
                "FROM projects ORDER BY created_at DESC"
            ).fetchall()
        return [
            Project(
                id=r["id"],
                title=r["title"],
                status=ProjectStatus(r["status"]),
                root_path=r["root_path"],
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
            )
            for r in rows
        ]
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/test_store_index.py -v
```
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/omc/store/index.py tests/test_store_index.py
git commit -m "feat(store): add IndexStore for global project registry"
```

---

## Task 6: Store — Project DB

**Files:**
- Create: `src/omc/store/project.py`
- Create: `tests/test_store_project.py`

Responsibility: `ProjectStore` wraps per-project `council.sqlite3` with task CRUD + interaction append + checkpoint append.

- [ ] **Step 1: Write failing test `tests/test_store_project.py`**

```python
import json
from pathlib import Path

from omc.models import Interaction, Task, TaskStatus
from omc.store.project import ProjectStore


def _make_store(tmp_docs: Path) -> ProjectStore:
    return ProjectStore(tmp_docs / "projects" / "p1" / "council.sqlite3")


def test_upsert_and_get_task(tmp_docs: Path):
    store = _make_store(tmp_docs)
    t = Task(
        id="T001",
        project_id="p1",
        md_path="tasks/T001.md",
        status=TaskStatus.PENDING,
        path_whitelist=["src/a.py"],
    )
    store.upsert_task(t)

    got = store.get_task("T001")
    assert got is not None
    assert got.id == "T001"
    assert got.status is TaskStatus.PENDING
    assert got.path_whitelist == ["src/a.py"]


def test_list_tasks_by_status(tmp_docs: Path):
    store = _make_store(tmp_docs)
    for i, status in enumerate([TaskStatus.PENDING, TaskStatus.PENDING, TaskStatus.ACCEPTED]):
        store.upsert_task(
            Task(
                id=f"T{i:03d}",
                project_id="p1",
                md_path=f"tasks/T{i:03d}.md",
                status=status,
                path_whitelist=[],
            )
        )
    pending = store.list_tasks(status=TaskStatus.PENDING)
    assert len(pending) == 2


def test_append_interaction(tmp_docs: Path):
    store = _make_store(tmp_docs)
    store.append_interaction(
        Interaction(
            project_id="p1",
            task_id="T001",
            from_agent="orchestrator",
            to_agent="glm5",
            kind="request",
            content=json.dumps({"spec": "hello"}),
            tokens_in=42,
            tokens_out=None,
            cost_usd=0.0,
        )
    )
    rows = store.list_interactions(task_id="T001")
    assert len(rows) == 1
    assert rows[0].from_agent == "orchestrator"
    assert rows[0].tokens_in == 42
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
uv run pytest tests/test_store_project.py -v
```
Expected: FAIL.

- [ ] **Step 3: Write `src/omc/store/project.py`**

```python
"""Per-project sqlite store (council.sqlite3). See spec §5.2."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from omc.models import CompressionCheckpoint, Interaction, Task, TaskStatus
from omc.store.schema import PROJECT_DDL


class ProjectStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(PROJECT_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_task(self, t: Task) -> None:
        now_iso = (t.updated_at or datetime.now()).isoformat()
        created_iso = (t.created_at or datetime.now()).isoformat()
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO tasks (
                    id, project_id, milestone_id, md_path, status, assignee,
                    attempts, codex_escalated, tokens_used, cost_usd,
                    path_whitelist, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    milestone_id    = excluded.milestone_id,
                    status          = excluded.status,
                    assignee        = excluded.assignee,
                    attempts        = excluded.attempts,
                    codex_escalated = excluded.codex_escalated,
                    tokens_used     = excluded.tokens_used,
                    cost_usd        = excluded.cost_usd,
                    path_whitelist  = excluded.path_whitelist,
                    updated_at      = excluded.updated_at
                """,
                (
                    t.id,
                    t.project_id,
                    t.milestone_id,
                    t.md_path,
                    t.status.value,
                    t.assignee,
                    t.attempts,
                    t.codex_escalated,
                    t.tokens_used,
                    t.cost_usd,
                    json.dumps(t.path_whitelist),
                    created_iso,
                    now_iso,
                ),
            )

    def get_task(self, task_id: str) -> Task | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        with self._conn() as c:
            if status is None:
                rows = c.execute("SELECT * FROM tasks ORDER BY id").fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY id", (status.value,)
                ).fetchall()
        return [_row_to_task(r) for r in rows]

    def append_interaction(self, i: Interaction) -> None:
        now_iso = (i.created_at or datetime.now()).isoformat()
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO interactions (
                    project_id, task_id, from_agent, to_agent, kind, content,
                    tokens_in, tokens_out, cost_usd, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    i.project_id,
                    i.task_id,
                    i.from_agent,
                    i.to_agent,
                    i.kind,
                    i.content,
                    i.tokens_in,
                    i.tokens_out,
                    i.cost_usd,
                    now_iso,
                ),
            )

    def list_interactions(self, task_id: str | None = None) -> list[Interaction]:
        with self._conn() as c:
            if task_id is None:
                rows = c.execute("SELECT * FROM interactions ORDER BY id").fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM interactions WHERE task_id = ? ORDER BY id",
                    (task_id,),
                ).fetchall()
        return [_row_to_interaction(r) for r in rows]

    def append_checkpoint(self, cp: CompressionCheckpoint) -> None:
        now_iso = (cp.created_at or datetime.now()).isoformat()
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO compression_checkpoints (
                    project_id, task_id, agent, reason, summary,
                    carry_forward, dropped_refs, created_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    cp.project_id,
                    cp.task_id,
                    cp.agent,
                    cp.reason,
                    cp.summary,
                    cp.carry_forward,
                    cp.dropped_refs,
                    now_iso,
                ),
            )


def _row_to_task(r: sqlite3.Row) -> Task:
    return Task(
        id=r["id"],
        project_id=r["project_id"],
        milestone_id=r["milestone_id"],
        md_path=r["md_path"],
        status=TaskStatus(r["status"]),
        assignee=r["assignee"],
        attempts=r["attempts"],
        codex_escalated=r["codex_escalated"],
        tokens_used=r["tokens_used"],
        cost_usd=r["cost_usd"],
        path_whitelist=json.loads(r["path_whitelist"]),
        created_at=datetime.fromisoformat(r["created_at"]),
        updated_at=datetime.fromisoformat(r["updated_at"]),
    )


def _row_to_interaction(r: sqlite3.Row) -> Interaction:
    return Interaction(
        id=r["id"],
        project_id=r["project_id"],
        task_id=r["task_id"],
        from_agent=r["from_agent"],
        to_agent=r["to_agent"],
        kind=r["kind"],
        content=r["content"],
        tokens_in=r["tokens_in"],
        tokens_out=r["tokens_out"],
        cost_usd=r["cost_usd"],
        created_at=datetime.fromisoformat(r["created_at"]),
    )
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/test_store_project.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/omc/store/project.py tests/test_store_project.py
git commit -m "feat(store): add ProjectStore with task/interaction/checkpoint CRUD"
```

---

## Task 7: Store — MD Layout

**Files:**
- Create: `src/omc/store/md.py`
- Create: `tests/test_store_md.py`

Responsibility: Create the `docs/projects/<id>/` directory skeleton and read/write well-known MD files (`requirement.md`, `tasks/<id>.md`, `reviews/<id>.md`, `audits/<id>.md`).

- [ ] **Step 1: Write failing test `tests/test_store_md.py`**

```python
from pathlib import Path

from omc.store.md import MDLayout


def test_scaffold_creates_directories(tmp_docs: Path):
    layout = MDLayout(tmp_docs / "projects" / "2026-04-12-demo")
    layout.scaffold()

    root = layout.root
    for sub in ("design", "tasks", "reviews", "audits", "artifacts"):
        assert (root / sub).is_dir(), f"{sub}/ missing"


def test_write_and_read_requirement(tmp_docs: Path):
    layout = MDLayout(tmp_docs / "projects" / "p")
    layout.scaffold()
    layout.write_requirement("# Req\n\nhello")
    assert layout.read_requirement() == "# Req\n\nhello"


def test_task_md_roundtrip(tmp_docs: Path):
    layout = MDLayout(tmp_docs / "projects" / "p")
    layout.scaffold()
    layout.write_task("T001", "# T001 spec\n\nbody")
    assert layout.read_task("T001") == "# T001 spec\n\nbody"
    assert layout.task_path("T001") == Path("tasks/T001.md")


def test_review_and_audit_md(tmp_docs: Path):
    layout = MDLayout(tmp_docs / "projects" / "p")
    layout.scaffold()
    layout.write_review("T001", "review text")
    layout.write_audit("T001", "audit text")
    assert layout.read_review("T001") == "review text"
    assert layout.read_audit("T001") == "audit text"
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
uv run pytest tests/test_store_md.py -v
```
Expected: FAIL.

- [ ] **Step 3: Write `src/omc/store/md.py`**

```python
"""MD file layout for a single project. See spec §5.1."""

from __future__ import annotations

from pathlib import Path

_SUBDIRS = ("design", "tasks", "reviews", "audits", "artifacts")


class MDLayout:
    def __init__(self, root: Path):
        self.root = root

    def scaffold(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in _SUBDIRS:
            (self.root / sub).mkdir(exist_ok=True)

    def write_requirement(self, text: str) -> None:
        (self.root / "requirement.md").write_text(text, encoding="utf-8")

    def read_requirement(self) -> str:
        return (self.root / "requirement.md").read_text(encoding="utf-8")

    def task_path(self, task_id: str) -> Path:
        return Path("tasks") / f"{task_id}.md"

    def write_task(self, task_id: str, text: str) -> None:
        (self.root / "tasks" / f"{task_id}.md").write_text(text, encoding="utf-8")

    def read_task(self, task_id: str) -> str:
        return (self.root / "tasks" / f"{task_id}.md").read_text(encoding="utf-8")

    def write_review(self, task_id: str, text: str) -> None:
        (self.root / "reviews" / f"{task_id}.md").write_text(text, encoding="utf-8")

    def read_review(self, task_id: str) -> str:
        return (self.root / "reviews" / f"{task_id}.md").read_text(encoding="utf-8")

    def write_audit(self, task_id: str, text: str) -> None:
        (self.root / "audits" / f"{task_id}.md").write_text(text, encoding="utf-8")

    def read_audit(self, task_id: str) -> str:
        return (self.root / "audits" / f"{task_id}.md").read_text(encoding="utf-8")
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/test_store_md.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/omc/store/md.py tests/test_store_md.py
git commit -m "feat(store): add MDLayout for per-project markdown files"
```

---

## Task 8: Path Whitelist Gate

**Files:**
- Create: `src/omc/gates/__init__.py`
- Create: `src/omc/gates/path_whitelist.py`
- Create: `tests/test_gates_path.py`

Responsibility: Given a list of produced file paths and the task's whitelist, return pass/fail with offending paths listed.

- [ ] **Step 1: Write `src/omc/gates/__init__.py`**

```python
"""Gatekeeper modules. See spec §6.2."""
```

- [ ] **Step 2: Write failing test `tests/test_gates_path.py`**

```python
from omc.gates.path_whitelist import GateResult, check_paths


def test_all_paths_allowed():
    result = check_paths(produced=["src/a.py"], whitelist=["src/a.py"])
    assert result == GateResult(ok=True, offenders=[])


def test_offender_detected():
    result = check_paths(
        produced=["src/a.py", "src/secret.py"], whitelist=["src/a.py"]
    )
    assert result.ok is False
    assert result.offenders == ["src/secret.py"]


def test_empty_produced_is_ok():
    result = check_paths(produced=[], whitelist=["src/a.py"])
    assert result.ok is True
```

- [ ] **Step 3: Run test — expect ImportError**

```bash
uv run pytest tests/test_gates_path.py -v
```
Expected: FAIL.

- [ ] **Step 4: Write `src/omc/gates/path_whitelist.py`**

```python
"""Path whitelist gate. See spec §6.2."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class GateResult:
    ok: bool
    offenders: list[str]


def check_paths(produced: list[str], whitelist: list[str]) -> GateResult:
    allowed = set(whitelist)
    offenders = [p for p in produced if p not in allowed]
    return GateResult(ok=not offenders, offenders=offenders)
```

- [ ] **Step 5: Run test — expect pass**

```bash
uv run pytest tests/test_gates_path.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/omc/gates/__init__.py src/omc/gates/path_whitelist.py tests/test_gates_path.py
git commit -m "feat(gates): add path whitelist gate"
```

---

## Task 9: Syntax Gate (Fake)

**Files:**
- Create: `src/omc/gates/syntax.py`
- Create: `tests/test_gates_syntax.py`

Responsibility: Stub that accepts any `.py` file for Phase 1. Real `ruff --check` runs in Phase 2. We still expose a consistent `GateResult` so Dispatcher can call it.

- [ ] **Step 1: Write failing test `tests/test_gates_syntax.py`**

```python
from pathlib import Path

from omc.gates.syntax import check_syntax


def test_valid_python_passes(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    result = check_syntax([f])
    assert result.ok is True
    assert result.offenders == []


def test_syntax_error_fails(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("def broken(:\n")
    result = check_syntax([f])
    assert result.ok is False
    assert str(f) in result.offenders[0]


def test_non_python_is_skipped(tmp_path: Path):
    f = tmp_path / "README.md"
    f.write_text("not python")
    result = check_syntax([f])
    assert result.ok is True
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
uv run pytest tests/test_gates_syntax.py -v
```
Expected: FAIL.

- [ ] **Step 3: Write `src/omc/gates/syntax.py`**

```python
"""Syntax gate — Phase 1 uses stdlib `ast.parse` for .py files only.

Phase 2 replaces this with a pluggable checker (ruff/tsc/go vet) chosen by
project language.
"""

from __future__ import annotations

import ast
from pathlib import Path

from omc.gates.path_whitelist import GateResult


def check_syntax(files: list[Path]) -> GateResult:
    offenders: list[str] = []
    for f in files:
        if f.suffix != ".py":
            continue
        try:
            ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as e:
            offenders.append(f"{f}: {e}")
    return GateResult(ok=not offenders, offenders=offenders)
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/test_gates_syntax.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/omc/gates/syntax.py tests/test_gates_syntax.py
git commit -m "feat(gates): add python syntax gate using ast.parse"
```

---

## Task 10: Fake Clients

**Files:**
- Create: `src/omc/clients/__init__.py`
- Create: `src/omc/clients/base.py`
- Create: `src/omc/clients/fake_codex.py`
- Create: `src/omc/clients/fake_worker.py`
- Create: `src/omc/clients/fake_auditor.py`
- Create: `tests/test_clients_fakes.py`

Responsibility: Define protocols (`CodexClient`, `WorkerRunner`, `Auditor`) and provide deterministic fakes for tests. Fakes are configured via constructor — a scripted list of responses per task id — so tests can simulate failures.

- [ ] **Step 1: Write `src/omc/clients/__init__.py`**

```python
"""LLM-facing clients (real + fake). Phase 2 adds real implementations."""
```

- [ ] **Step 2: Write `src/omc/clients/base.py`**

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


@dataclass(slots=True, frozen=True)
class WorkerOutput:
    task_id: str
    files: dict[str, str]  # path -> content
    tokens_used: int = 0


@dataclass(slots=True, frozen=True)
class ReviewOutput:
    task_id: str
    passed: bool
    review_md: str
    tokens_used: int = 0


@dataclass(slots=True, frozen=True)
class AuditOutput:
    task_id: str
    passed: bool
    audit_md: str
    tokens_used: int = 0


class CodexClient(Protocol):
    def produce_spec(self, task_id: str, requirement: str) -> SpecOutput: ...
    def review(self, task_id: str, files: dict[str, str], spec_md: str) -> ReviewOutput: ...


class WorkerRunner(Protocol):
    def write(self, task_id: str, spec_md: str) -> WorkerOutput: ...


class Auditor(Protocol):
    def audit(self, task_id: str, files: dict[str, str]) -> AuditOutput: ...
```

- [ ] **Step 3: Write `src/omc/clients/fake_codex.py`**

```python
"""Deterministic FakeCodexClient for tests and Phase 1 E2E."""

from __future__ import annotations

from omc.clients.base import CodexClient, ReviewOutput, SpecOutput


class FakeCodexClient:
    def __init__(
        self,
        specs: dict[str, SpecOutput] | None = None,
        reviews: dict[str, list[ReviewOutput]] | None = None,
    ):
        self._specs = specs or {}
        self._reviews = reviews or {}
        self._review_calls: dict[str, int] = {}

    def produce_spec(self, task_id: str, requirement: str) -> SpecOutput:
        if task_id in self._specs:
            return self._specs[task_id]
        return SpecOutput(
            task_id=task_id,
            spec_md=f"# {task_id} spec\n\nauto-generated for: {requirement[:80]}",
            path_whitelist=[f"src/generated/{task_id}.py"],
            tokens_used=100,
        )

    def review(self, task_id: str, files: dict[str, str], spec_md: str) -> ReviewOutput:
        scripted = self._reviews.get(task_id)
        if scripted:
            idx = self._review_calls.get(task_id, 0)
            result = scripted[min(idx, len(scripted) - 1)]
            self._review_calls[task_id] = idx + 1
            return result
        return ReviewOutput(
            task_id=task_id,
            passed=True,
            review_md=f"# review {task_id}\n\nOK",
            tokens_used=50,
        )


_: CodexClient = FakeCodexClient()  # type-check protocol conformance at import
```

- [ ] **Step 4: Write `src/omc/clients/fake_worker.py`**

```python
"""Deterministic FakeWorkerRunner."""

from __future__ import annotations

from omc.clients.base import WorkerOutput, WorkerRunner


class FakeWorkerRunner:
    def __init__(self, outputs: dict[str, list[WorkerOutput]] | None = None):
        self._outputs = outputs or {}
        self._calls: dict[str, int] = {}

    def write(self, task_id: str, spec_md: str) -> WorkerOutput:
        scripted = self._outputs.get(task_id)
        if scripted:
            idx = self._calls.get(task_id, 0)
            out = scripted[min(idx, len(scripted) - 1)]
            self._calls[task_id] = idx + 1
            return out
        return WorkerOutput(
            task_id=task_id,
            files={f"src/generated/{task_id}.py": f'"""{task_id}."""\n\nVALUE = 1\n'},
            tokens_used=200,
        )


_: WorkerRunner = FakeWorkerRunner()
```

- [ ] **Step 5: Write `src/omc/clients/fake_auditor.py`**

```python
"""Deterministic FakeAuditor."""

from __future__ import annotations

from omc.clients.base import AuditOutput, Auditor


class FakeAuditor:
    def __init__(self, results: dict[str, AuditOutput] | None = None):
        self._results = results or {}

    def audit(self, task_id: str, files: dict[str, str]) -> AuditOutput:
        if task_id in self._results:
            return self._results[task_id]
        return AuditOutput(
            task_id=task_id,
            passed=True,
            audit_md=f"# audit {task_id}\n\nno issues",
            tokens_used=30,
        )


_: Auditor = FakeAuditor()
```

- [ ] **Step 6: Write failing test `tests/test_clients_fakes.py`**

```python
from omc.clients.base import ReviewOutput, WorkerOutput
from omc.clients.fake_auditor import FakeAuditor
from omc.clients.fake_codex import FakeCodexClient
from omc.clients.fake_worker import FakeWorkerRunner


def test_fake_codex_default_spec():
    c = FakeCodexClient()
    s = c.produce_spec("T001", "requirement text")
    assert s.task_id == "T001"
    assert "T001" in s.spec_md
    assert s.path_whitelist == ["src/generated/T001.py"]


def test_fake_codex_scripted_reviews_cycle():
    c = FakeCodexClient(
        reviews={
            "T001": [
                ReviewOutput(task_id="T001", passed=False, review_md="fail1"),
                ReviewOutput(task_id="T001", passed=True, review_md="pass"),
            ]
        }
    )
    assert c.review("T001", {}, "").passed is False
    assert c.review("T001", {}, "").passed is True
    # further calls stick on last
    assert c.review("T001", {}, "").passed is True


def test_fake_worker_default_output():
    w = FakeWorkerRunner()
    out = w.write("T001", "# spec")
    assert "src/generated/T001.py" in out.files


def test_fake_worker_scripted():
    w = FakeWorkerRunner(
        outputs={
            "T001": [
                WorkerOutput(task_id="T001", files={"src/a.py": "broken(:"}),
                WorkerOutput(task_id="T001", files={"src/a.py": "x = 1\n"}),
            ]
        }
    )
    assert "broken(:" in w.write("T001", "").files["src/a.py"]
    assert w.write("T001", "").files["src/a.py"] == "x = 1\n"


def test_fake_auditor_default_passes():
    a = FakeAuditor()
    r = a.audit("T001", {"src/a.py": "x=1"})
    assert r.passed is True
```

- [ ] **Step 7: Run test — expect pass**

```bash
uv run pytest tests/test_clients_fakes.py -v
```
Expected: 5 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/omc/clients tests/test_clients_fakes.py
git commit -m "feat(clients): add protocols + deterministic fake codex/worker/auditor"
```

---

## Task 11: Budgeter (Tracking Only)

**Files:**
- Create: `src/omc/budget.py`
- Create: `tests/test_budget.py`

Responsibility: Track `attempts` and `tokens_used` per task. Phase 1 only reports; enforcement (raising over_budget, triggering escalation) lands in Phase 2 along with real token counts.

- [ ] **Step 1: Write failing test `tests/test_budget.py`**

```python
from omc.budget import BudgetTracker, Limits


def test_tracker_counts_attempts():
    t = BudgetTracker(Limits())
    t.record_attempt("T001")
    t.record_attempt("T001")
    assert t.attempts("T001") == 2


def test_tracker_tokens_accumulate():
    t = BudgetTracker(Limits())
    t.record_tokens("T001", 100)
    t.record_tokens("T001", 50)
    assert t.tokens("T001") == 150


def test_attempts_exceeded_flag():
    t = BudgetTracker(Limits(l1_worker_retries=2))
    t.record_attempt("T001")
    t.record_attempt("T001")
    assert t.l1_exhausted("T001") is False  # exactly at limit, not over
    t.record_attempt("T001")
    assert t.l1_exhausted("T001") is True


def test_tokens_budget_exceeded():
    t = BudgetTracker(Limits(l3_task_tokens=1000))
    t.record_tokens("T001", 1001)
    assert t.l3_exhausted("T001") is True
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
uv run pytest tests/test_budget.py -v
```
Expected: FAIL.

- [ ] **Step 3: Write `src/omc/budget.py`**

```python
"""Budget tracking. See spec §6.1.

Phase 1: tracks counters only, exposes `*_exhausted()` queries.
Phase 2 wires these into Dispatcher for actual enforcement.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Limits:
    l1_worker_retries: int = 3
    l2_codex_retries: int = 1
    l3_task_tokens: int = 200_000
    l4_project_usd: float = 5.0


class BudgetTracker:
    def __init__(self, limits: Limits):
        self.limits = limits
        self._attempts: dict[str, int] = defaultdict(int)
        self._codex_attempts: dict[str, int] = defaultdict(int)
        self._tokens: dict[str, int] = defaultdict(int)
        self._cost: float = 0.0

    def record_attempt(self, task_id: str) -> None:
        self._attempts[task_id] += 1

    def record_codex_attempt(self, task_id: str) -> None:
        self._codex_attempts[task_id] += 1

    def record_tokens(self, task_id: str, n: int) -> None:
        self._tokens[task_id] += n

    def record_cost(self, usd: float) -> None:
        self._cost += usd

    def attempts(self, task_id: str) -> int:
        return self._attempts[task_id]

    def codex_attempts(self, task_id: str) -> int:
        return self._codex_attempts[task_id]

    def tokens(self, task_id: str) -> int:
        return self._tokens[task_id]

    def cost(self) -> float:
        return self._cost

    def l1_exhausted(self, task_id: str) -> bool:
        return self._attempts[task_id] > self.limits.l1_worker_retries

    def l2_exhausted(self, task_id: str) -> bool:
        return self._codex_attempts[task_id] > self.limits.l2_codex_retries

    def l3_exhausted(self, task_id: str) -> bool:
        return self._tokens[task_id] > self.limits.l3_task_tokens

    def l4_exhausted(self) -> bool:
        return self._cost > self.limits.l4_project_usd
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/test_budget.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/omc/budget.py tests/test_budget.py
git commit -m "feat(budget): add BudgetTracker with L1-L4 counters"
```

---

## Task 12: Dispatcher (Sequential Pipeline)

**Files:**
- Create: `src/omc/dispatcher.py`
- Create: `tests/test_dispatcher.py`

Responsibility: Run one task through the full pipeline synchronously using the injected clients/gates. Emits state transitions via the state machine, records interactions, writes artifacts to disk, updates sqlite. **No async / no concurrency in Phase 1.**

- [ ] **Step 1: Write failing test `tests/test_dispatcher.py`**

```python
from datetime import datetime
from pathlib import Path

from omc.budget import BudgetTracker, Limits
from omc.clients.base import ReviewOutput
from omc.clients.fake_auditor import FakeAuditor
from omc.clients.fake_codex import FakeCodexClient
from omc.clients.fake_worker import FakeWorkerRunner
from omc.dispatcher import Dispatcher, DispatcherDeps
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _deps(tmp_docs: Path) -> tuple[Dispatcher, ProjectStore, MDLayout]:
    project_root = tmp_docs / "projects" / "p1"
    md = MDLayout(project_root)
    md.scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    deps = DispatcherDeps(
        store=store,
        md=md,
        codex=FakeCodexClient(),
        worker=FakeWorkerRunner(),
        auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=project_root / "workspace",
    )
    (deps.project_source_root).mkdir(parents=True, exist_ok=True)
    return Dispatcher(deps), store, md


def test_happy_path_accepts_task(tmp_docs: Path):
    dispatcher, store, md = _deps(tmp_docs)
    now = datetime(2026, 4, 12)
    store.upsert_task(
        Task(
            id="T001",
            project_id="p1",
            md_path="tasks/T001.md",
            status=TaskStatus.PENDING,
            path_whitelist=["src/generated/T001.py"],
            created_at=now,
            updated_at=now,
        )
    )

    dispatcher.run_once("T001", requirement="build a hello module")

    got = store.get_task("T001")
    assert got is not None
    assert got.status is TaskStatus.ACCEPTED
    # MD artifacts written
    assert md.read_review("T001").startswith("# review")
    assert md.read_audit("T001").startswith("# audit")
    # task file exists
    assert md.read_task("T001").startswith("# T001 spec")
    # workspace file created
    assert (dispatcher.deps.project_source_root / "src/generated/T001.py").exists()


def test_review_fail_then_pass_retries(tmp_docs: Path):
    project_root = tmp_docs / "projects" / "p1"
    md = MDLayout(project_root)
    md.scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    codex = FakeCodexClient(
        reviews={
            "T001": [
                ReviewOutput(task_id="T001", passed=False, review_md="needs fix"),
                ReviewOutput(task_id="T001", passed=True, review_md="ok"),
            ]
        }
    )
    deps = DispatcherDeps(
        store=store,
        md=md,
        codex=codex,
        worker=FakeWorkerRunner(),
        auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=project_root / "workspace",
    )
    deps.project_source_root.mkdir(parents=True, exist_ok=True)
    dispatcher = Dispatcher(deps)

    now = datetime(2026, 4, 12)
    store.upsert_task(
        Task(
            id="T001",
            project_id="p1",
            md_path="tasks/T001.md",
            status=TaskStatus.PENDING,
            path_whitelist=["src/generated/T001.py"],
            created_at=now,
            updated_at=now,
        )
    )

    dispatcher.run_once("T001", requirement="build it")

    got = store.get_task("T001")
    assert got is not None
    assert got.status is TaskStatus.ACCEPTED
    assert got.attempts == 2  # first review failed, second passed


def test_path_whitelist_violation_blocks_task(tmp_docs: Path):
    from omc.clients.base import WorkerOutput

    project_root = tmp_docs / "projects" / "p1"
    md = MDLayout(project_root)
    md.scaffold()
    store = ProjectStore(project_root / "council.sqlite3")
    worker = FakeWorkerRunner(
        outputs={
            "T001": [
                WorkerOutput(task_id="T001", files={"src/evil.py": "x=1"}),
                WorkerOutput(task_id="T001", files={"src/evil.py": "x=1"}),
                WorkerOutput(task_id="T001", files={"src/evil.py": "x=1"}),
                WorkerOutput(task_id="T001", files={"src/evil.py": "x=1"}),
            ]
        }
    )
    deps = DispatcherDeps(
        store=store,
        md=md,
        codex=FakeCodexClient(),
        worker=worker,
        auditor=FakeAuditor(),
        budget=BudgetTracker(Limits()),
        project_source_root=project_root / "workspace",
    )
    deps.project_source_root.mkdir(parents=True, exist_ok=True)
    dispatcher = Dispatcher(deps)

    now = datetime(2026, 4, 12)
    store.upsert_task(
        Task(
            id="T001",
            project_id="p1",
            md_path="tasks/T001.md",
            status=TaskStatus.PENDING,
            path_whitelist=["src/generated/T001.py"],
            created_at=now,
            updated_at=now,
        )
    )

    dispatcher.run_once("T001", requirement="x")

    got = store.get_task("T001")
    assert got is not None
    assert got.status is TaskStatus.BLOCKED
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
uv run pytest tests/test_dispatcher.py -v
```
Expected: FAIL.

- [ ] **Step 3: Write `src/omc/dispatcher.py`**

```python
"""Sequential Dispatcher for Phase 1. See spec §3 (single task lifecycle).

Phase 2 replaces this with an asyncio-based concurrent pool and adds
real Codex-escalation on L1 exhaustion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from omc.budget import BudgetTracker
from omc.clients.base import Auditor, CodexClient, WorkerRunner
from omc.gates.path_whitelist import check_paths
from omc.gates.syntax import check_syntax
from omc.models import Interaction, TaskStatus
from omc.state import StateEvent, next_state
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


@dataclass(slots=True)
class DispatcherDeps:
    store: ProjectStore
    md: MDLayout
    codex: CodexClient
    worker: WorkerRunner
    auditor: Auditor
    budget: BudgetTracker
    project_source_root: Path  # where worker-produced files actually land


class Dispatcher:
    def __init__(self, deps: DispatcherDeps):
        self.deps = deps

    def run_once(self, task_id: str, requirement: str) -> None:
        """Drive one task from PENDING through to ACCEPTED or BLOCKED."""
        task = self.deps.store.get_task(task_id)
        if task is None:
            raise ValueError(f"task {task_id} not found")

        # 1. Codex produces spec (always once per run_once for simplicity).
        spec = self.deps.codex.produce_spec(task_id, requirement)
        self.deps.md.write_task(task_id, spec.spec_md)
        task.path_whitelist = spec.path_whitelist
        self._record(task_id, task.project_id, "codex", "orchestrator", "response",
                     spec.spec_md, tokens_out=spec.tokens_used)

        # 2. Loop: worker write -> gates -> review -> audit.
        while True:
            self.deps.budget.record_attempt(task_id)

            if self.deps.budget.l1_exhausted(task_id):
                self._transition(task, StateEvent.ESCALATION_EXHAUSTED)
                return

            # Worker
            self._transition(task, StateEvent.WORKER_START)
            worker_out = self.deps.worker.write(task_id, spec.spec_md)
            self.deps.budget.record_tokens(task_id, worker_out.tokens_used)
            self._record(task_id, task.project_id, "orchestrator", "glm5", "request",
                         spec.spec_md, tokens_in=worker_out.tokens_used)

            # Path whitelist (before anything else — cheap reject)
            path_result = check_paths(
                produced=list(worker_out.files.keys()),
                whitelist=task.path_whitelist,
            )
            if not path_result.ok:
                # discard; retry worker
                self._transition(task, StateEvent.WORKER_FAIL)
                continue

            # Materialize files into workspace for syntax check
            written = self._write_files(worker_out.files)

            # Syntax gate
            syn_result = check_syntax(written)
            if not syn_result.ok:
                self._transition(task, StateEvent.WORKER_FAIL)
                continue

            self._transition(task, StateEvent.WORKER_DONE)

            # Codex review
            review = self.deps.codex.review(task_id, worker_out.files, spec.spec_md)
            self.deps.budget.record_tokens(task_id, review.tokens_used)
            self.deps.md.write_review(task_id, review.review_md)
            self._record(task_id, task.project_id, "codex", "orchestrator", "review",
                         review.review_md, tokens_out=review.tokens_used)
            if not review.passed:
                self._transition(task, StateEvent.REVIEW_FAIL)
                continue
            self._transition(task, StateEvent.REVIEW_PASS)

            # Audit
            audit = self.deps.auditor.audit(task_id, worker_out.files)
            self.deps.budget.record_tokens(task_id, audit.tokens_used)
            self.deps.md.write_audit(task_id, audit.audit_md)
            self._record(task_id, task.project_id, "glm5", "orchestrator", "audit",
                         audit.audit_md, tokens_out=audit.tokens_used)
            if not audit.passed:
                self._transition(task, StateEvent.AUDIT_FAIL)
                continue
            self._transition(task, StateEvent.AUDIT_PASS)
            return

    # ----- helpers -----

    def _write_files(self, files: dict[str, str]) -> list[Path]:
        written: list[Path] = []
        for rel, content in files.items():
            target = self.deps.project_source_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(target)
        return written

    def _transition(self, task, event: StateEvent) -> None:
        new_status = next_state(task.status, event)
        task.status = new_status
        task.attempts = self.deps.budget.attempts(task.id)
        task.tokens_used = self.deps.budget.tokens(task.id)
        task.updated_at = datetime.now()
        self.deps.store.upsert_task(task)

    def _record(
        self,
        task_id: str,
        project_id: str,
        from_agent: str,
        to_agent: str,
        kind: str,
        content: str,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> None:
        self.deps.store.append_interaction(
            Interaction(
                project_id=project_id,
                task_id=task_id,
                from_agent=from_agent,
                to_agent=to_agent,
                kind=kind,
                content=content,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        )
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/test_dispatcher.py -v
```
Expected: 3 tests PASS (happy, retry, whitelist-violation-blocks).

- [ ] **Step 5: Commit**

```bash
git add src/omc/dispatcher.py tests/test_dispatcher.py
git commit -m "feat(dispatcher): add sequential single-task pipeline with state transitions"
```

---

## Task 13: End-to-End Fake Pipeline

**Files:**
- Create: `tests/test_e2e_fake.py`

Responsibility: Integration test exercising `IndexStore + ProjectStore + MDLayout + Dispatcher + all fakes`. This is the Phase 1 acceptance criterion.

- [ ] **Step 1: Write E2E test `tests/test_e2e_fake.py`**

```python
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
```

- [ ] **Step 2: Run test — expect pass**

```bash
uv run pytest tests/test_e2e_fake.py -v
```
Expected: 1 test PASS.

- [ ] **Step 3: Run full suite to check for regressions**

```bash
uv run pytest -v
```
Expected: all tests PASS (total = 3 + 8 + 2 + 3 + 4 + 3 + 3 + 5 + 4 + 3 + 1 = 39 tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_fake.py
git commit -m "test(e2e): full project lifecycle with fake clients passes"
```

---

## Task 14: CLI Skeleton

**Files:**
- Create: `src/omc/cli.py`
- Modify: `pyproject.toml` (entry point already declared in Task 1 — verify)

Responsibility: Provide `omc init <slug>` (creates project scaffold + registers in index) and `omc run-fake <project_id> <task_id>` (runs Dispatcher with all fakes — for operator smoke test).

- [ ] **Step 1: Write `src/omc/cli.py`**

```python
"""omc CLI. Phase 1: init + run-fake (smoke test). See spec §1 slash commands
for the Phase 3 full command set."""

from __future__ import annotations

import argparse
import sys
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test CLI manually in a tmp dir**

```bash
cd /tmp && rm -rf omc-smoke && mkdir omc-smoke && cd omc-smoke
uv --project /home/hertz/Project/oh-my-council run omc init hello
uv --project /home/hertz/Project/oh-my-council run omc run-fake "$(date +%Y-%m-%d)-hello" T001
```
Expected output: `initialized project ...` then `task T001 -> accepted`.

- [ ] **Step 3: Verify no regressions**

```bash
cd /home/hertz/Project/oh-my-council
uv run pytest -v
uv run ruff check src tests
```
Expected: all tests PASS, ruff clean.

- [ ] **Step 4: Commit**

```bash
git add src/omc/cli.py
git commit -m "feat(cli): add omc init and omc run-fake for Phase 1 smoke testing"
```

---

## Phase 1 Completion Criteria

- [ ] All 39 tests pass: `uv run pytest -v`
- [ ] Ruff clean: `uv run ruff check src tests`
- [ ] `omc init demo` creates `docs/projects/<date>-demo/` with scaffold + empty sqlite + `requirement.md` template
- [ ] `omc run-fake <project> T001` drives one fake task from `pending` to `accepted`, writing a `.py` file under `workspace/src/generated/`, plus `reviews/T001.md` and `audits/T001.md`
- [ ] 3 sqlite tables in `council.sqlite3` (`tasks`, `interactions`, `compression_checkpoints`) all get rows except `compression_checkpoints` (only schema in Phase 1)

When the above all pass, Phase 1 is done. Next: Phase 2 plan (real Codex CLI, LiteLLM workers, hallucination gate, enforcement, escalation).

---

## Self-Review Notes (post-plan review)

- **Spec coverage**: §1 architecture boxes covered by Dispatcher + Store + Clients + Gates + Budget. §3 lifecycle covered by state machine + Dispatcher loop. §5 persistence covered by IndexStore + ProjectStore + MDLayout. §6.1 L1-L4 counters in BudgetTracker (enforcement deferred per Phase split). §6.2 Gatekeeper: path_whitelist ✓, syntax ✓, hallucination gate deferred to Phase 2 (needs Codex output format). §8 MVP items: orchestrator ✓ (sequential), store ✓, path/syntax gates ✓, budgeter ✓ (tracking only). Deferred items explicitly documented above.
- **Placeholder scan**: no TBD / TODO / "implement later" strings used in task code or commands.
- **Type consistency**: `GateResult` defined once in `gates/path_whitelist.py` and reused in `gates/syntax.py`. `TaskStatus`, `ProjectStatus`, `StateEvent` consistent across state.py / store / dispatcher.
- **Ambiguity**: "project_source_root" is explicitly the workspace where Worker code lands (not the same as MD `artifacts/`, which is for archival copies in later phases).
