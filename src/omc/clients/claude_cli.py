"""Thin subprocess wrapper around the `claude` CLI (`claude -p` non-interactive).

Used by the MilestoneVerifier to delegate milestone acceptance to Claude
with minimal token cost (one short prompt per milestone, not per task).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class ClaudeCLIError(RuntimeError):
    """Claude CLI failed (nonzero exit, timeout, spawn error)."""


@dataclass(slots=True, frozen=True)
class ClaudeResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass(slots=True)
class ClaudeCLI:
    bin: str = "claude"
    timeout_s: float = 120.0

    def run_once(self, prompt: str) -> ClaudeResult:
        cmd = [self.bin, "-p", prompt]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise ClaudeCLIError(f"claude timeout after {self.timeout_s}s") from e
        except (OSError, FileNotFoundError) as e:
            raise ClaudeCLIError(f"claude spawn failed: {e}") from e
        if proc.returncode != 0:
            raise ClaudeCLIError(
                f"claude exit {proc.returncode}: "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        return ClaudeResult(
            stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode,
        )
