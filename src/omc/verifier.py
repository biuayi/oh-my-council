"""MilestoneVerifier: short `claude -p` call deciding ACCEPT/NEED_DETAIL/REJECT
for a project milestone. Fail-closed: unparseable output → REJECT."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from omc.clients.claude_cli import ClaudeCLI
from omc.store.md import MDLayout
from omc.store.project import ProjectStore

Decision = Literal["ACCEPT", "NEED_DETAIL", "REJECT"]


@dataclass(slots=True, frozen=True)
class VerdictOutput:
    decision: Decision
    summary: str
    next_actions: list[str] = field(default_factory=list)


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(raw: str) -> dict | None:
    """Try plain-json → fenced-json → first `{...}` blob. Return None on failure."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = _FENCE_RE.search(raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    # last resort: first { ... } balanced blob
    depth = 0
    start = -1
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


@dataclass(slots=True)
class MilestoneVerifier:
    cli: ClaudeCLI

    def verify(
        self, *, store: ProjectStore, md: MDLayout, project_id: str
    ) -> VerdictOutput:
        requirement = md.read_requirement()
        tasks = store.list_tasks()
        task_lines = "\n".join(
            f"- {t.id}: status={t.status.name} attempts={t.attempts}"
            for t in tasks
        )
        prompt = (
            f"You are acting as the PM verifying a milestone for project "
            f"`{project_id}`. Decide ACCEPT / NEED_DETAIL / REJECT and reply "
            f'with a single JSON object: {{"decision": "...", '
            f'"summary": "...", "next_actions": ["..."]}}.\n\n'
            f"## requirement.md\n{requirement}\n\n"
            f"## task list\n{task_lines or '(none)'}\n"
        )
        result = self.cli.run_once(prompt)
        data = _extract_json(result.stdout)
        if not data or "decision" not in data:
            return VerdictOutput(
                decision="REJECT",
                summary=f"unparseable claude output: {result.stdout[:200]}",
                next_actions=[],
            )
        decision = data.get("decision", "REJECT")
        if decision not in ("ACCEPT", "NEED_DETAIL", "REJECT"):
            decision = "REJECT"
        return VerdictOutput(
            decision=decision,
            summary=str(data.get("summary", "")),
            next_actions=list(data.get("next_actions", [])),
        )
