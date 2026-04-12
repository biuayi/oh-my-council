"""Runtime configuration. Reads ~/.config/oh-my-council/.env (or the path in
OMC_ENV_FILE). Secrets never land in the repo — see spec §10.5.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_ENV_PATH = Path.home() / ".config" / "oh-my-council" / ".env"

_REQUIRED = (
    "OMC_WORKER_VENDOR",
    "OMC_WORKER_MODEL",
    "OMC_WORKER_API_BASE",
    "OMC_WORKER_API_KEY",
)


@dataclass(slots=True, frozen=True)
class ProviderConfig:
    vendor: str
    model: str
    api_base: str
    api_key: str


@dataclass(slots=True, frozen=True)
class Settings:
    worker_vendor: str
    worker_model: str
    worker_api_base: str
    worker_api_key: str
    codex_bin: str = "codex"
    codex_timeout_s: float = 300.0
    codex_reasoning_effort: str = "low"
    fallback_vendor: str | None = None
    fallback_model: str | None = None
    fallback_api_base: str | None = None
    fallback_api_key: str | None = None

    @property
    def providers(self) -> tuple[ProviderConfig, ...]:
        """Ordered provider chain: primary first, then optional fallback.
        Workers/auditors iterate this on transient failure."""
        chain = [
            ProviderConfig(
                vendor=self.worker_vendor,
                model=self.worker_model,
                api_base=self.worker_api_base,
                api_key=self.worker_api_key,
            )
        ]
        if (
            self.fallback_vendor
            and self.fallback_model
            and self.fallback_api_base
            and self.fallback_api_key
        ):
            chain.append(
                ProviderConfig(
                    vendor=self.fallback_vendor,
                    model=self.fallback_model,
                    api_base=_normalize_api_base(self.fallback_api_base),
                    api_key=self.fallback_api_key,
                )
            )
        return tuple(chain)


def _normalize_api_base(raw: str) -> str:
    """LiteLLM with the `openai/` prefix appends `/v1/chat/completions` itself.
    If the user's env has the full URL (as most vendor docs show), strip the
    suffix so we don't 404 with a double-appended path.
    """
    s = raw.rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s


def load_settings(path: Path | None = None) -> Settings:
    if path is None:
        override = os.environ.get("OMC_ENV_FILE")
        path = Path(override) if override else DEFAULT_ENV_PATH
    values = dict(dotenv_values(path))
    missing = [k for k in _REQUIRED if k not in values or not values[k]]
    if missing:
        raise KeyError(f"missing required env keys: {', '.join(missing)}")
    return Settings(
        worker_vendor=values["OMC_WORKER_VENDOR"],
        worker_model=values["OMC_WORKER_MODEL"],
        worker_api_base=_normalize_api_base(values["OMC_WORKER_API_BASE"]),
        worker_api_key=values["OMC_WORKER_API_KEY"],
        codex_bin=values.get("OMC_CODEX_BIN") or "codex",
        codex_timeout_s=float(values.get("OMC_CODEX_TIMEOUT_S") or 300.0),
        codex_reasoning_effort=(
            values.get("OMC_CODEX_REASONING_EFFORT") or "low"
        ).lower(),
        fallback_vendor=values.get("OMC_WORKER_FALLBACK_VENDOR") or None,
        fallback_model=values.get("OMC_WORKER_FALLBACK_MODEL") or None,
        fallback_api_base=values.get("OMC_WORKER_FALLBACK_API_BASE") or None,
        fallback_api_key=values.get("OMC_WORKER_FALLBACK_API_KEY") or None,
    )
