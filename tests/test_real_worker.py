from unittest.mock import MagicMock, patch

import pytest

from omc.clients.real_worker import LiteLLMWorker
from omc.config import Settings


def _settings() -> Settings:
    return Settings(
        worker_vendor="minimax",
        worker_model="MiniMax-M2.5",
        worker_api_base="https://api.minimaxi.com/v1",
        worker_api_key="sk-test",
    )


def _mock_completion(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    resp.usage = MagicMock(total_tokens=123)
    return resp


def test_parses_valid_json_output():
    w = LiteLLMWorker(_settings())
    payload = '{"files": {"src/generated/T001.py": "x = 1\\n"}}'
    with patch("omc.clients.real_worker.litellm.completion",
               return_value=_mock_completion(payload)):
        out = w.write("T001", "# spec\n\nwrite x=1")
    assert out.task_id == "T001"
    assert out.files == {"src/generated/T001.py": "x = 1\n"}
    assert out.tokens_used == 123


def test_parses_fenced_json_output():
    w = LiteLLMWorker(_settings())
    payload = 'sure:\n```json\n{"files": {"a.py": "y=2\\n"}}\n```\n'
    with patch("omc.clients.real_worker.litellm.completion",
               return_value=_mock_completion(payload)):
        out = w.write("T001", "# spec")
    assert out.files == {"a.py": "y=2\n"}


def test_invalid_json_raises_worker_error():
    from omc.clients.real_worker import WorkerParseError
    w = LiteLLMWorker(_settings())
    with patch("omc.clients.real_worker.litellm.completion",
               return_value=_mock_completion("not json at all")), pytest.raises(WorkerParseError):
        w.write("T001", "# spec")


def test_schema_violation_raises():
    from omc.clients.real_worker import WorkerParseError
    w = LiteLLMWorker(_settings())
    with patch("omc.clients.real_worker.litellm.completion",
               return_value=_mock_completion('{"wrongkey": 1}')), pytest.raises(WorkerParseError):
        w.write("T001", "# spec")
