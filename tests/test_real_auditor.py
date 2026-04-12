from unittest.mock import MagicMock, patch

from omc.clients.real_auditor import LiteLLMAuditor
from omc.config import Settings


def _settings() -> Settings:
    return Settings(worker_vendor="x", worker_model="m", worker_api_base="u", worker_api_key="k")


def _mock(content: str, tokens: int = 42) -> MagicMock:
    r = MagicMock()
    r.choices = [MagicMock(message=MagicMock(content=content))]
    r.usage = MagicMock(total_tokens=tokens)
    return r


def test_audit_passes():
    a = LiteLLMAuditor(_settings())
    with patch("omc.clients.real_auditor.litellm.completion",
               return_value=_mock('{"passed": true, "findings": []}')):
        out = a.audit("T001", {"a.py": "x = 1"})
    assert out.passed is True
    assert "no issues" in out.audit_md.lower() or "passed" in out.audit_md.lower()
    assert out.tokens_used == 42


def test_audit_fails_on_findings():
    a = LiteLLMAuditor(_settings())
    payload = '{"passed": false, "findings": [{"path":"a.py","severity":"high","message":"eval()"}]}'  # noqa: E501
    with patch("omc.clients.real_auditor.litellm.completion", return_value=_mock(payload)):
        out = a.audit("T001", {"a.py": "eval(x)"})
    assert out.passed is False
    assert "eval" in out.audit_md


def test_audit_unparseable_response_defaults_to_fail():
    a = LiteLLMAuditor(_settings())
    with patch("omc.clients.real_auditor.litellm.completion", return_value=_mock("garbage")):
        out = a.audit("T001", {"a.py": "x=1"})
    assert out.passed is False
    assert "unparseable" in out.audit_md.lower()


def test_litellm_auditor_populates_cost_usd(monkeypatch):
    from unittest.mock import MagicMock

    import omc.clients.real_auditor as ra
    from omc.clients.real_auditor import LiteLLMAuditor
    from omc.config import Settings
    from omc.pricing import ModelPrice

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = '{"passed": true, "findings": []}'
    fake_resp.usage.prompt_tokens = 400_000
    fake_resp.usage.completion_tokens = 100_000
    fake_resp.usage.total_tokens = 500_000

    monkeypatch.setattr(ra.litellm, "completion", lambda **_: fake_resp)
    monkeypatch.setattr(ra, "load_prices", lambda: {
        "audit-model": ModelPrice(in_usd_per_mtok=1.0, out_usd_per_mtok=5.0)
    })

    s = Settings(
        worker_vendor="x", worker_model="audit-model",
        worker_api_base="http://x", worker_api_key="x",
    )
    out = LiteLLMAuditor(s).audit("T001", {"a.py": "pass\n"})

    assert out.tokens_in == 400_000
    assert out.tokens_out == 100_000
    # 0.4*1 + 0.1*5 = 0.4 + 0.5 = 0.9
    assert abs(out.cost_usd - 0.9) < 1e-9
    assert out.passed is True
