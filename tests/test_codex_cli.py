from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from omc.clients.codex_cli import CodexCLI, CodexCLIError


def test_run_once_returns_stdout():
    cli = CodexCLI(bin="codex", timeout_s=5.0)
    fake = MagicMock(returncode=0, stdout="session banner...\n", stderr="")

    def _side_effect(cmd, **_kwargs):
        # Simulate codex writing the "last message" to the path we gave it
        i = cmd.index("--output-last-message")
        Path(cmd[i + 1]).write_text("hello\n", encoding="utf-8")
        return fake

    with patch(
        "omc.clients.codex_cli.subprocess.run", side_effect=_side_effect
    ) as mr:
        out = cli.run_once("say hello", cwd=Path("/tmp"), sandbox="read-only")
    assert out.stdout == "hello\n"
    assert out.returncode == 0
    args, _kwargs = mr.call_args
    cmd = args[0]
    assert cmd[0] == "codex"
    assert "exec" in cmd
    assert "--sandbox" in cmd and "read-only" in cmd
    assert "--skip-git-repo-check" in cmd
    assert "--ephemeral" in cmd
    assert "--output-last-message" in cmd
    # low reasoning effort by default (speed over depth for spec/review)
    assert any('model_reasoning_effort="low"' in str(x) for x in cmd)


def test_run_once_nonzero_raises():
    cli = CodexCLI(bin="codex", timeout_s=5.0)
    fake = MagicMock(returncode=2, stdout="", stderr="boom")
    with (
        patch("omc.clients.codex_cli.subprocess.run", return_value=fake),
        pytest.raises(CodexCLIError) as e,
    ):
        cli.run_once("x", cwd=Path("/tmp"), sandbox="read-only")
    assert "boom" in str(e.value)


def test_run_once_timeout_raises():
    import subprocess

    cli = CodexCLI(bin="codex", timeout_s=0.01)
    with (
        patch(
            "omc.clients.codex_cli.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["codex"], timeout=0.01),
        ),
        pytest.raises(CodexCLIError) as e,
    ):
        cli.run_once("x", cwd=Path("/tmp"), sandbox="read-only")
    assert "timeout" in str(e.value).lower()
