from pathlib import Path
from unittest.mock import MagicMock

from omc.clients.codex_cli import CodexResult
from omc.clients.real_codex import RealCodexClient


def _client(cli_mock) -> RealCodexClient:
    return RealCodexClient(cli=cli_mock, workspace_root=Path("/tmp/omc-test"))


def test_escalation_uses_writable_sandbox():
    raw = '{"files": {"src/hello.py": "x=1\\n"}}'
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    c = _client(cli)
    out = c.dispatch_escalation(
        "T001", "# spec", {"src/hello.py": "broken code\n"}
    )
    assert out == {"src/hello.py": "x=1\n"}
    # verify sandbox is workspace-write for escalation
    _, kwargs = cli.run_once.call_args
    assert kwargs.get("sandbox") == "workspace-write"
