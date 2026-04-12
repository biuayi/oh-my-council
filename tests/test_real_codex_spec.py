from pathlib import Path
from unittest.mock import MagicMock

from omc.clients.codex_cli import CodexResult
from omc.clients.real_codex import RealCodexClient


def _client(cli_mock) -> RealCodexClient:
    return RealCodexClient(cli=cli_mock, workspace_root=Path("/tmp/omc-test"))


def test_produce_spec_parses_json_output():
    raw = '{"spec_md": "# T001\\nwrite hello", "path_whitelist": ["src/hello.py"]}'
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    out = _client(cli).produce_spec("T001", "print hello")
    assert out.task_id == "T001"
    assert out.spec_md.startswith("# T001")
    assert out.path_whitelist == ["src/hello.py"]
    # verify sandbox is read-only for spec
    _, kwargs = cli.run_once.call_args
    assert kwargs.get("sandbox") == "read-only"


def test_produce_spec_tolerates_fence_and_preamble():
    raw = 'ok:\n```json\n{"spec_md": "# T1", "path_whitelist": ["a.py"]}\n```\n'
    cli = MagicMock()
    cli.run_once.return_value = CodexResult(stdout=raw, stderr="", returncode=0)
    out = _client(cli).produce_spec("T1", "x")
    assert out.path_whitelist == ["a.py"]
