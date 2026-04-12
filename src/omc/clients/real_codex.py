"""Real CodexClient backed by the codex CLI. Each mode (spec / review /
escalation) composes on top of CodexCLI.run_once with a mode-specific
sandbox and prompt template."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from omc.clients.base import ReviewOutput, SpecOutput
from omc.clients.codex_cli import CodexCLI

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class CodexParseError(ValueError):
    """Codex output did not match the expected JSON schema."""


@dataclass(slots=True)
class RealCodexClient:
    cli: CodexCLI
    workspace_root: Path

    def produce_spec(self, task_id: str, requirement: str) -> SpecOutput:
        prompt = _SPEC_PROMPT.format(task_id=task_id, requirement=requirement)
        res = self.cli.run_once(prompt, cwd=self.workspace_root, sandbox="read-only")
        obj = _parse_json(res.stdout)
        try:
            spec_md = obj["spec_md"]
            wl = list(obj["path_whitelist"])
        except (KeyError, TypeError) as e:
            raise CodexParseError(f"spec missing required keys: {obj!r}") from e
        return SpecOutput(task_id=task_id, spec_md=spec_md, path_whitelist=wl, tokens_used=0)

    def review(self, task_id: str, files: dict[str, str], spec_md: str) -> ReviewOutput:
        raise NotImplementedError  # Task 6


_SPEC_PROMPT = """You are the technical lead. Produce a per-file implementation
spec for task {task_id}. Requirement: {requirement!r}. Respond ONLY as JSON:
{{"spec_md": "<markdown spec for the worker>",
  "path_whitelist": ["<relative file path>", ...]}}
path_whitelist must list every file the worker is allowed to create or modify."""


def _parse_json(raw: str) -> dict:
    s = raw.strip()
    m = _FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise CodexParseError(f"codex output not valid JSON: {e}") from e
