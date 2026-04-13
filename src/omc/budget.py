"""Budget tracking. See spec §6.1.

Phase 1: tracks counters only, exposes `*_exhausted()` queries.
Phase 2 wires these into Dispatcher for actual enforcement.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Limits:
    l1_worker_retries: int = 3
    l2_codex_retries: int = 1
    l3_task_tokens: int = 200_000
    l4_project_usd: float = 5.0


class BudgetTracker:
    def __init__(self, limits: Limits, *, project_id: str | None = None, notifier=None):
        self.limits = limits
        self.project_id = project_id
        self.notifier = notifier
        self._attempts: dict[str, int] = defaultdict(int)
        self._codex_attempts: dict[str, int] = defaultdict(int)
        self._tokens: dict[str, int] = defaultdict(int)
        self._cost: float = 0.0
        self._warned_80: bool = False

    def record_attempt(self, task_id: str) -> None:
        self._attempts[task_id] += 1

    def record_codex_attempt(self, task_id: str) -> None:
        self._codex_attempts[task_id] += 1

    def record_tokens(self, task_id: str, n: int) -> None:
        self._tokens[task_id] += n

    def record_cost(self, usd: float) -> None:
        prev = self._cost
        self._cost += usd
        # Emit a one-shot 80% warning when crossing the threshold. Doesn't
        # interrupt the run — purely informational so unattended sessions
        # get a chance to notice spend before L4 hard-stops.
        threshold = 0.8 * self.limits.l4_project_usd
        if prev < threshold <= self._cost and not self._warned_80:
            self._warned_80 = True
            pct = 100 * self._cost / self.limits.l4_project_usd
            print(
                f"[budget] WARNING project cost ${self._cost:.4f} crossed 80% "
                f"of L4 limit ${self.limits.l4_project_usd:.2f} "
                f"(at {pct:.1f}%)",
                file=sys.stderr, flush=True,
            )
            if self.notifier is not None and getattr(self.notifier, "enabled", False):
                self.notifier.budget_warn(
                    project_id=self.project_id or "<unknown>",
                    spend_usd=self._cost,
                    limit_usd=self.limits.l4_project_usd,
                    pct=pct,
                )

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
