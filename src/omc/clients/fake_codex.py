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
