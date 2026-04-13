"""Real CodexClient backed by the codex CLI. Each mode (spec / review /
escalation) composes on top of CodexCLI.run_once with a mode-specific
sandbox and prompt template."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from omc.clients.base import CodexClient, ReviewOutput, SpecOutput
from omc.clients.codex_cli import CodexCLI

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class CodexParseError(ValueError):
    """Codex output did not match the expected JSON schema."""


@dataclass(slots=True)
class RealCodexClient:
    cli: CodexCLI
    workspace_root: Path
    _last_symbols: list = field(default_factory=list)

    def produce_plan(self, requirement: str) -> list[dict]:
        """Decompose a project requirement into a task list.

        Returns a list of dicts with keys:
          - task_id: "T001", "T002", ... (caller-assigned if missing)
          - brief:    one-line summary
          - path_whitelist: [relative file paths]
        """
        prompt = _PLAN_PROMPT.format(requirement=requirement)
        res = self.cli.run_once(prompt, cwd=self.workspace_root, sandbox="read-only")
        obj = _parse_json(res.stdout)
        raw = obj.get("tasks")
        if not isinstance(raw, list) or not raw:
            raise CodexParseError(f"plan missing 'tasks' list: {obj!r}")
        tasks: list[dict] = []
        for i, t in enumerate(raw, start=1):
            if not isinstance(t, dict):
                raise CodexParseError(f"plan task[{i-1}] not a dict: {t!r}")
            wl = t.get("path_whitelist") or []
            if not isinstance(wl, list) or not all(isinstance(p, str) for p in wl):
                raise CodexParseError(f"plan task[{i-1}] bad path_whitelist: {wl!r}")
            tasks.append(
                {
                    "task_id": t.get("task_id") or f"T{i:03d}",
                    "brief": (t.get("brief") or "").strip(),
                    "path_whitelist": wl,
                }
            )
        return tasks

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
        corpus = "\n\n".join(f"### {p}\n```python\n{c}\n```" for p, c in files.items())
        prompt = _REVIEW_PROMPT.format(spec_md=spec_md, corpus=corpus)
        res = self.cli.run_once(prompt, cwd=self.workspace_root, sandbox="read-only")
        obj = _parse_json(res.stdout)
        passed = bool(obj.get("passed", False))
        review_md = obj.get("review_md") or ""
        symbols = obj.get("symbols") or []
        self._last_symbols = symbols  # available to gates.hallucination
        if symbols:
            review_md += "\n\n## symbols\n" + "\n".join(
                f"- {s.get('kind','?')} `{s.get('name','?')}` in {s.get('file','?')}"
                for s in symbols
            )
        return ReviewOutput(task_id=task_id, passed=passed, review_md=review_md, tokens_used=0)

    def dispatch_escalation(
        self,
        task_id: str,
        spec_md: str,
        failing_files: dict[str, str],
    ) -> dict[str, str]:
        corpus = "\n\n".join(
            f"### {p}\n```python\n{c}\n```" for p, c in failing_files.items()
        )
        prompt = _ESCALATION_PROMPT.format(spec_md=spec_md, corpus=corpus)
        res = self.cli.run_once(prompt, cwd=self.workspace_root, sandbox="workspace-write")
        obj = _parse_json(res.stdout)
        files = obj.get("files")
        if not isinstance(files, dict):
            raise CodexParseError(f"escalation missing 'files': {obj!r}")
        return {k: v for k, v in files.items() if isinstance(k, str) and isinstance(v, str)}


_PLAN_PROMPT = """You are the technical lead decomposing a requirement into
a concrete, minimal task list for cheap worker models to execute. Aim for
2-6 tasks; each task must produce a small set of files that a worker can
write in a single LLM call. Respond ONLY as JSON:
{{"tasks": [
  {{"task_id": "T001",
    "brief": "<one line>",
    "path_whitelist": ["<relative path>", ...]}},
  ...
]}}
Every path must be relative (no leading slash, no ..) and must be a file
the worker should create or modify. Do NOT include directories.

Requirement:
{requirement}"""


_SPEC_PROMPT = """You are the technical lead. Produce a per-file implementation
spec for task {task_id}. Requirement: {requirement!r}. Respond ONLY as JSON:
{{"spec_md": "<markdown spec for the worker>",
  "path_whitelist": ["<relative file path>", ...]}}
path_whitelist must list every file the worker is allowed to create or modify."""

_REVIEW_PROMPT = """Review this task implementation. Spec:
{spec_md}

Files:
{corpus}

Respond ONLY as JSON:
{{"passed": bool,
  "review_md": "<markdown review notes>",
  "symbols": [{{"name": "<dotted name>", "kind": "import|call", "file": "<path>"}}, ...]}}
`symbols` must list EVERY imported name and EVERY external function call that
should exist in the project or its declared dependencies. Downstream validation
will grep the repo to confirm existence."""

_ESCALATION_PROMPT = """Workers failed repeatedly on this task. You now have
workspace-write access. Rewrite the file(s) from scratch to satisfy the spec.
Spec:
{spec_md}

Previous failing attempt:
{corpus}

Respond ONLY as JSON: {{"files": {{"<relpath>": "<contents>"}}}}"""


def _parse_json(raw: str) -> dict:
    s = raw.strip()
    # 1) raw-is-already-JSON happy path.
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # 2) fenced ```json ... ``` block.
    m = _FENCE_RE.search(s)
    if m:
        inner = m.group(1).strip()
        if inner:
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                pass
    # 3) salvage the last balanced {...} chunk in the raw.
    brace = _extract_last_json_object(s)
    if brace:
        try:
            return json.loads(brace)
        except json.JSONDecodeError:
            pass
    raise CodexParseError(
        f"codex output not valid JSON (len={len(raw)}): {raw[:500]!r}"
    )


def _extract_last_json_object(text: str) -> str | None:
    """Scan for the last syntactically balanced `{...}` block in text.

    Handles nested braces inside string literals by tracking quote state.
    """
    best: tuple[int, int] | None = None
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if esc:
            esc = False
            continue
        if ch == "\\" and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                best = (start, i + 1)
    if best is None:
        return None
    return text[best[0]: best[1]]


_: CodexClient = RealCodexClient(cli=CodexCLI(), workspace_root=Path("."))  # noqa: F841
