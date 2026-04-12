from pathlib import Path
from unittest.mock import MagicMock

from omc.clients.codex_cli import CodexResult
from omc.clients.real_codex import RealCodexClient


def _client(cli_mock) -> RealCodexClient:
    return RealCodexClient(cli=cli_mock, workspace_root=Path("/tmp/omc-test"))


def test_review_pass():
    raw = '{"passed": true, "review_md": "looks good", "symbols": []}'
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    c = _client(cli)
    out = c.review("T001", {"a.py": "x=1\n"}, "# spec")
    assert out.passed is True
    assert "looks good" in out.review_md


def test_review_fail_with_findings():
    raw = '{"passed": false, "review_md": "missing error handling", "symbols": []}'
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    c = _client(cli)
    out = c.review("T001", {"a.py": "x=1\n"}, "# spec")
    assert out.passed is False
    assert "missing" in out.review_md


def test_review_symbols_embedded_in_md():
    raw = ('{"passed": true, "review_md": "ok", '
           '"symbols": [{"name":"json.loads","kind":"call","file":"a.py"}]}')
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    c = _client(cli)
    out = c.review("T001", {"a.py": "x=1\n"}, "# spec")
    assert "json.loads" in out.review_md
