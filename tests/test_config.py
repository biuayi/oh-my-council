from pathlib import Path

import pytest

from omc.config import Settings, load_settings


def test_loads_from_explicit_path(tmp_path: Path):
    envfile = tmp_path / ".env"
    envfile.write_text(
        "OMC_WORKER_VENDOR=minimax\n"
        "OMC_WORKER_MODEL=MiniMax-M2.5\n"
        "OMC_WORKER_API_BASE=https://api.minimaxi.com/v1/chat/completions\n"
        "OMC_WORKER_API_KEY=sk-test\n"
    )
    s = load_settings(envfile)
    assert isinstance(s, Settings)
    assert s.worker_vendor == "minimax"
    assert s.worker_model == "MiniMax-M2.5"
    assert s.worker_api_base.startswith("https://")
    assert s.worker_api_key == "sk-test"


def test_missing_required_key_raises(tmp_path: Path):
    envfile = tmp_path / ".env"
    envfile.write_text("OMC_WORKER_VENDOR=minimax\n")
    with pytest.raises(KeyError):
        load_settings(envfile)


def test_default_path_fallback(monkeypatch, tmp_path: Path):
    envfile = tmp_path / ".env"
    envfile.write_text(
        "OMC_WORKER_VENDOR=minimax\n"
        "OMC_WORKER_MODEL=m\n"
        "OMC_WORKER_API_BASE=https://x\n"
        "OMC_WORKER_API_KEY=k\n"
    )
    monkeypatch.setenv("OMC_ENV_FILE", str(envfile))
    s = load_settings()
    assert s.worker_model == "m"
