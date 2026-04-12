"""Syntax gate — Phase 1 uses stdlib `ast.parse` for .py files only.

Phase 2 replaces this with a pluggable checker (ruff/tsc/go vet) chosen by
project language.
"""

from __future__ import annotations

import ast
from pathlib import Path

from omc.gates.path_whitelist import GateResult


def check_syntax(files: list[Path]) -> GateResult:
    offenders: list[str] = []
    for f in files:
        if f.suffix != ".py":
            continue
        try:
            ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as e:
            offenders.append(f"{f}: {e}")
    return GateResult(ok=not offenders, offenders=offenders)
