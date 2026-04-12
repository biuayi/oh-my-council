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


def test_accepts_bare_path_map_without_files_envelope():
    """Workers often drop the `{"files": ...}` wrapper. If the root object is
    itself a str->str map, treat it as the files map."""
    w = LiteLLMWorker(_settings())
    payload = '{"src/a.py": "x = 1\\n", "tests/test_a.py": "# test\\n"}'
    with patch("omc.clients.real_worker.litellm.completion",
               return_value=_mock_completion(payload)):
        out = w.write("T001", "# spec")
    assert out.files == {"src/a.py": "x = 1\n", "tests/test_a.py": "# test\n"}


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


def test_worker_falls_back_on_primary_failure():
    """Primary provider raises → worker retries on fallback provider."""
    s = Settings(
        worker_vendor="glm5", worker_model="primary-model",
        worker_api_base="http://primary", worker_api_key="k1",
        fallback_vendor="minimax", fallback_model="fallback-model",
        fallback_api_base="http://fallback", fallback_api_key="k2",
    )
    w = LiteLLMWorker(s)
    fallback_resp = _mock_completion('{"files": {"a.py": "pass\\n"}}')
    calls: list[str] = []

    def fake_completion(**kw):
        calls.append(kw["api_base"])
        if kw["api_base"] == "http://primary":
            raise RuntimeError("primary 500")
        return fallback_resp

    with patch("omc.clients.real_worker.litellm.completion", side_effect=fake_completion):
        out = w.write("T001", "# spec")
    assert out.files == {"a.py": "pass\n"}
    assert calls == ["http://primary", "http://fallback"]


def test_worker_raises_when_all_providers_fail():
    s = Settings(
        worker_vendor="glm5", worker_model="p",
        worker_api_base="http://primary", worker_api_key="k1",
        fallback_vendor="minimax", fallback_model="f",
        fallback_api_base="http://fallback", fallback_api_key="k2",
    )
    w = LiteLLMWorker(s)
    with patch(
        "omc.clients.real_worker.litellm.completion",
        side_effect=RuntimeError("boom"),
    ), pytest.raises(RuntimeError, match="boom"):
        w.write("T001", "# spec")


def test_litellm_worker_populates_cost_usd(monkeypatch):
    """Worker output must include tokens_in/out and computed cost_usd."""
    from unittest.mock import MagicMock

    import omc.clients.real_worker as rw
    from omc.clients.real_worker import LiteLLMWorker
    from omc.config import Settings
    from omc.pricing import ModelPrice

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = '{"files": {"a.py": "pass\\n"}}'
    fake_resp.usage.prompt_tokens = 1_000_000
    fake_resp.usage.completion_tokens = 500_000
    fake_resp.usage.total_tokens = 1_500_000

    monkeypatch.setattr(rw.litellm, "completion", lambda **_: fake_resp)
    monkeypatch.setattr(rw, "load_prices", lambda: {
        "test-model": ModelPrice(in_usd_per_mtok=2.0, out_usd_per_mtok=4.0)
    })

    s = Settings(
        worker_vendor="x", worker_model="test-model",
        worker_api_base="http://x", worker_api_key="x",
    )
    out = LiteLLMWorker(s).write("T001", "dummy spec")

    assert out.tokens_in == 1_000_000
    assert out.tokens_out == 500_000
    assert out.tokens_used == 1_500_000
    # 1M*2 + 0.5M*4 = 2 + 2 = 4.0
    assert out.cost_usd == 4.0
