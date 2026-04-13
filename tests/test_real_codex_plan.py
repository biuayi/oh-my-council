from pathlib import Path
from unittest.mock import MagicMock

import pytest

from omc.clients.codex_cli import CodexResult
from omc.clients.real_codex import CodexParseError, RealCodexClient


def _client(cli_mock) -> RealCodexClient:
    return RealCodexClient(cli=cli_mock, workspace_root=Path("/tmp/omc-test"))


def _res(raw: str) -> CodexResult:
    return CodexResult(stdout=raw, stderr="", returncode=0)


def test_produce_plan_returns_tasks():
    raw = (
        '{"tasks": ['
        '{"task_id": "T001", "brief": "add greet fn", '
        '"path_whitelist": ["src/smoke/greet.py", "tests/test_greet.py"]},'
        '{"task_id": "T002", "brief": "add cli", '
        '"path_whitelist": ["src/smoke/cli.py"]}'
        ']}'
    )
    cli = MagicMock()
    cli.run_once.return_value = _res(raw)
    out = _client(cli).produce_plan("build a tiny utility")
    assert len(out) == 2
    assert out[0]["task_id"] == "T001"
    assert out[0]["path_whitelist"] == ["src/smoke/greet.py", "tests/test_greet.py"]
    assert out[1]["task_id"] == "T002"
    # read-only sandbox for planning
    _, kwargs = cli.run_once.call_args
    assert kwargs.get("sandbox") == "read-only"


def test_produce_plan_auto_ids_when_missing():
    raw = (
        '{"tasks": ['
        '{"brief": "a", "path_whitelist": ["a.py"]},'
        '{"brief": "b", "path_whitelist": ["b.py"]}'
        ']}'
    )
    cli = MagicMock()
    cli.run_once.return_value = _res(raw)
    out = _client(cli).produce_plan("x")
    assert [t["task_id"] for t in out] == ["T001", "T002"]


def test_produce_plan_rejects_missing_tasks_key():
    cli = MagicMock()
    cli.run_once.return_value = _res('{"foo": []}')
    with pytest.raises(CodexParseError):
        _client(cli).produce_plan("x")


def test_produce_plan_rejects_bad_path_whitelist():
    raw = '{"tasks": [{"task_id": "T001", "path_whitelist": "src/a.py"}]}'
    cli = MagicMock()
    cli.run_once.return_value = _res(raw)
    with pytest.raises(CodexParseError):
        _client(cli).produce_plan("x")
