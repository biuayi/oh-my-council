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
    timeout_s: float = 300.0
    reasoning_effort: str = "low"

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
            "--ephemeral",
            "-c", f'model_reasoning_effort="{self.reasoning_effort}"',
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
        # Empty last-msg has been observed; fall back to stdout's last JSON-ish
        # block rather than returning "" (which would fail with an opaque
        # "Expecting value" downstream).
        try:
            last_msg = last_msg_path.read_text(encoding="utf-8")
        except OSError:
            last_msg = ""
        finally:
            last_msg_path.unlink(missing_ok=True)
        if not last_msg.strip():
            last_msg = _extract_last_message_from_stdout(proc.stdout)
        if not last_msg.strip():
            # Empty is almost certainly a bug we want to see rather than silently
            # pass on to a downstream JSON parser with a cryptic "Expecting value".
            raise CodexCLIError(
                f"codex produced empty output (rc={proc.returncode}, "
                f"stdout_len={len(proc.stdout)}, stderr_tail={proc.stderr[-200:]!r})"
            )
        return CodexResult(stdout=last_msg, stderr=proc.stderr, returncode=proc.returncode)


def _extract_last_message_from_stdout(stdout: str) -> str:
    """Best-effort recovery when --output-last-message file was empty.

    Codex exec stdout contains the session banner, a "tokens used" line, and
    then the final agent message (repeated). Strip the banner/token lines and
    return the tail.
    """
    if not stdout:
        return ""
    lines = stdout.splitlines()
    # Drop the "tokens used\nN" two-line footer if present.
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) >= 2 and lines[-2].strip() == "tokens used":
        lines = lines[:-2]
    # Walk back until we find a block that looks like it could be JSON.
    tail = "\n".join(lines).strip()
    return tail
