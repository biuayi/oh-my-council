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
