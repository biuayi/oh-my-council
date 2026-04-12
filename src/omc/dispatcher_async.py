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
