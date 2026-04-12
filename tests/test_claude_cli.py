"""Unit tests for ClaudeCLI subprocess wrapper."""

from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from omc.clients.claude_cli import ClaudeCLI, ClaudeCLIError, ClaudeResult


def test_run_once_success():
    cli = ClaudeCLI(bin="claude", timeout_s=60.0)
    with patch("subprocess.run") as sr:
        sr.return_value = MagicMock(
            returncode=0, stdout="hello\n", stderr="",
        )
        result = cli.run_once("be helpful")
    assert isinstance(result, ClaudeResult)
    assert result.stdout == "hello\n"
    assert result.returncode == 0
    cmd = sr.call_args.args[0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "be helpful" in cmd


def test_run_once_timeout():
    cli = ClaudeCLI(bin="claude", timeout_s=0.1)
    with patch("subprocess.run") as sr:
        sr.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=0.1)
        with pytest.raises(ClaudeCLIError, match="timeout"):
            cli.run_once("x")


def test_run_once_nonzero_exit():
    cli = ClaudeCLI()
    with patch("subprocess.run") as sr:
        sr.return_value = MagicMock(returncode=2, stdout="", stderr="boom")
        with pytest.raises(ClaudeCLIError, match="exit 2"):
            cli.run_once("x")


def test_run_once_spawn_failure():
    cli = ClaudeCLI(bin="nonexistent-binary")
    with patch("subprocess.run") as sr:
        sr.side_effect = FileNotFoundError("nope")
        with pytest.raises(ClaudeCLIError, match="spawn"):
            cli.run_once("x")
