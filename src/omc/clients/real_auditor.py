"""LiteLLM-backed Auditor. Runs a security-focused review on worker files.
Unparseable responses fail closed (passed=False) — safer than skipping audit."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import litellm

from omc.clients.base import Auditor, AuditOutput
from omc.config import Settings

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_SYSTEM_PROMPT = """You are a security auditor. Scan the provided Python files
for: (1) command injection, (2) hardcoded credentials/secrets, (3) eval/exec
use on untrusted input, (4) path traversal (unvalidated ../ / os.path.join on
user input), (5) SQL injection. Respond ONLY as JSON:
{"passed": bool, "findings": [{"path": str, "severity": "low|medium|high", "message": str}]}
Return passed=true iff findings is empty."""


@dataclass(slots=True)
class LiteLLMAuditor:
    settings: Settings

    def audit(self, task_id: str, files: dict[str, str]) -> AuditOutput:
        corpus = "\n\n".join(f"### {p}\n```python\n{c}\n```" for p, c in files.items())
        resp = litellm.completion(
            model=f"openai/{self.settings.worker_model}",
            api_base=self.settings.worker_api_base,
            api_key=self.settings.worker_api_key,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": corpus},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        tokens_val = getattr(resp.usage, "total_tokens", 0) or 0
        tokens = int(tokens_val) if getattr(resp, "usage", None) else 0

        m = _FENCE_RE.search(content)
        if m:
            content = m.group(1).strip()
        try:
            obj = json.loads(content)
            passed = bool(obj.get("passed", False))
            findings = obj.get("findings", [])
        except json.JSONDecodeError:
            return AuditOutput(
                task_id=task_id, passed=False,
                audit_md=f"# audit {task_id}\n\nunparseable auditor response; treating as fail.",
                tokens_used=tokens,
            )
        md = _render_md(task_id, passed, findings)
        return AuditOutput(task_id=task_id, passed=passed, audit_md=md, tokens_used=tokens)


def _render_md(task_id: str, passed: bool, findings: list[dict]) -> str:
    if passed and not findings:
        return f"# audit {task_id}\n\nno issues"
    lines = [f"# audit {task_id}", "", f"passed: {passed}", ""]
    for f in findings:
        lines.append(f"- [{f.get('severity','?')}] {f.get('path','?')}: {f.get('message','')}")
    return "\n".join(lines)


_: Auditor = LiteLLMAuditor(Settings(  # noqa: F841
    worker_vendor="x", worker_model="x", worker_api_base="x", worker_api_key="x",
))
