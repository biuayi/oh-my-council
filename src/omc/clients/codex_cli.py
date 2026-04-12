"""Thin subprocess wrapper around the `codex` CLI. Higher-level CodexClient
composes spec/review/escalation on top of this primitive."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

Sandbox = str  # "read-only" | "workspace-write" | "danger-full-access"


class CodexCLIError(RuntimeError):
    """Codex CLI failed (nonzero exit, timeout, or spawn error)."""


@dataclass(slots=True, frozen=True)
class CodexResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass(slots=True)
class CodexCLI:
    bin: str = "codex"
    timeout_s: float = 120.0

    def run_once(
        self,
        prompt: str,
        *,
        cwd: Path,
        sandbox: Sandbox = "read-only",
    ) -> CodexResult:
        cmd = [
            self.bin,
            "exec",
            "--sandbox", sandbox,
            "--skip-git-repo-check",
            "--cd", str(cwd),
            prompt,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise CodexCLIError(f"codex timeout after {self.timeout_s}s") from e
        except (OSError, FileNotFoundError) as e:
            raise CodexCLIError(f"codex spawn failed: {e}") from e
        if proc.returncode != 0:
            raise CodexCLIError(
                f"codex exit {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return CodexResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
