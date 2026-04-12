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
        tokens_total = (
            int(getattr(usage, "total_tokens", tokens_in + tokens_out) or 0)
            if usage
            else 0
        )
        cost = compute_cost(
            self.settings.worker_model, tokens_in, tokens_out, load_prices()
        )
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
