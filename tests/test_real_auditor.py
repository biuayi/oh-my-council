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
