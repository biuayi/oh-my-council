"""Thin subprocess wrapper around the `codex` CLI. Higher-level CodexClient
composes spec/review/escalation on top of this primitive."""

from __future__ import annotations

import subprocess
import tempfile
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="omc-codex-"
        ) as tf:
            last_msg_path = Path(tf.name)
        cmd = [
            self.bin,
            "exec",
            "--sandbox", sandbox,
            "--skip-git-repo-check",
            "--cd", str(cwd),
            "--output-last-message", str(last_msg_path),
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
            last_msg_path.unlink(missing_ok=True)
            raise CodexCLIError(f"codex timeout after {self.timeout_s}s") from e
        except (OSError, FileNotFoundError) as e:
            last_msg_path.unlink(missing_ok=True)
            raise CodexCLIError(f"codex spawn failed: {e}") from e
        if proc.returncode != 0:
            last_msg_path.unlink(missing_ok=True)
            raise CodexCLIError(
                f"codex exit {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        # Prefer the dedicated last-message file over noisy interleaved stdout
        # (Codex v0.118+ prepends session banner + skill preambles to stdout).
        try:
            last_msg = last_msg_path.read_text(encoding="utf-8")
        except OSError:
            last_msg = proc.stdout
        finally:
            last_msg_path.unlink(missing_ok=True)
        return CodexResult(stdout=last_msg, stderr=proc.stderr, returncode=proc.returncode)
