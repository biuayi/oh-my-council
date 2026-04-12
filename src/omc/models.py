"""Dataclasses for oh-my-council domain objects.

Mirrors the sqlite schema in spec §5.2. Persistence is handled by
the `store/` package; this module is pure data.
"""

from __future__ import annotations

from dataclasses import dataclass
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
