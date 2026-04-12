"""Path whitelist gate. See spec §6.2."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class GateResult:
    ok: bool
    offenders: list[str]


def check_paths(produced: list[str], whitelist: list[str]) -> GateResult:
    allowed = set(whitelist)
    offenders = [p for p in produced if p not in allowed]
    return GateResult(ok=not offenders, offenders=offenders)
