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
