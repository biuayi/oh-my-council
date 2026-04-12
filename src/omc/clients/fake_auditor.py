"""Deterministic FakeAuditor."""

from __future__ import annotations

from omc.clients.base import Auditor, AuditOutput


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
