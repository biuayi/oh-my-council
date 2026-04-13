"""Sensitive-info scan: regex + entropy to catch secrets before commit.

`scan_text` returns a list of findings (line, rule, snippet). Regexes catch
structured secrets (AWS keys, OpenAI/Anthropic/SK tokens, private keys,
JWT-looking blobs). The entropy check catches base64-ish blobs long enough
to plausibly be a secret.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

# (rule_name, pattern)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_key", re.compile(
        r"\baws_secret_access_key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})",
        re.IGNORECASE,
    )),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("generic_bearer", re.compile(
        r"\bBearer\s+[A-Za-z0-9_\-\.=]{20,}\b"
    )),
    ("private_key_block", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"
    )),
    ("jwt_like", re.compile(
        r"\beyJ[A-Za-z0-9_\-]{10,}\."
        r"[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"
    )),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{30,}\b")),
)

_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?:^|[\s,{;])
    (?P<key>[A-Za-z0-9_\-]*(?:secret|token|password|passwd|api[_\-]?key|apikey)[A-Za-z0-9_\-]*)
    \s*[:=]\s*
    ['"]?(?P<val>[^'"\s,}]{12,})['"]?
    """
)

_ENTROPY_THRESHOLD = 4.0  # bits/char — base64 noise clusters here
_ENTROPY_MIN_LEN = 20

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
              "dist", "build", ".worktrees", ".pytest_cache", ".ruff_cache"}
_SKIP_SUFFIXES = {".sqlite3", ".sqlite3-journal", ".whl", ".tar.gz", ".png",
                  ".jpg", ".jpeg", ".gif", ".pdf", ".lock", ".so", ".pyc"}


@dataclass(slots=True, frozen=True)
class Finding:
    path: str          # relative to scan root
    line: int
    rule: str
    snippet: str       # a short redacted excerpt for logs


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _redact(val: str) -> str:
    if len(val) <= 8:
        return "***"
    return f"{val[:3]}...{val[-3:]}"


def scan_text(text: str, path: str = "<string>") -> list[Finding]:
    findings: list[Finding] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for name, pat in _SECRET_PATTERNS:
            m = pat.search(line)
            if m:
                findings.append(Finding(
                    path=path, line=i, rule=name,
                    snippet=_redact(m.group(0)),
                ))
        for m in _ASSIGNMENT.finditer(line):
            val = m.group("val")
            if len(val) < _ENTROPY_MIN_LEN:
                continue
            # Skip obvious placeholders
            lower = val.lower()
            if any(p in lower for p in (
                "example", "changeme", "your-", "<your", "placeholder",
                "xxxx", "fixme", "todo", "dummy",
            )):
                continue
            if _shannon_entropy(val) >= _ENTROPY_THRESHOLD:
                findings.append(Finding(
                    path=path, line=i, rule="high_entropy_assignment",
                    snippet=f"{m.group('key')}={_redact(val)}",
                ))
    return findings


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & _SKIP_DIRS:
        return True
    return path.suffix.lower() in _SKIP_SUFFIXES


def scan_paths(root: Path, paths: list[Path] | None = None) -> list[Finding]:
    """Walk `paths` (default: all files under `root`) and scan each file."""
    root = root.resolve()
    targets: list[Path]
    if paths is None:
        targets = [p for p in root.rglob("*") if p.is_file()]
    else:
        targets = [p if p.is_absolute() else (root / p) for p in paths]

    findings: list[Finding] = []
    for p in targets:
        if not p.is_file():
            continue
        rel = p.relative_to(root) if p.is_relative_to(root) else p
        if _should_skip(rel):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > 2_000_000:  # skip >2MB files
            continue
        for f in scan_text(text, path=str(rel)):
            findings.append(f)
    return findings
