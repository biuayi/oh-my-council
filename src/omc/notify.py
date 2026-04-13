"""Webhook notifier for unattended mode.

Any endpoint that accepts a Slack-compatible `{"text": "..."}` POST works
(Slack incoming webhook, Discord with `/slack` suffix, 企业微信 robot, etc.).

The module is dependency-free on purpose — uses stdlib urllib only so we
don't drag requests onto the hot path.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class NotifyConfig:
    webhook_url: str | None
    timeout_s: float = 5.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> NotifyConfig:
        src = env if env is not None else os.environ
        return cls(
            webhook_url=(src.get("OMC_NOTIFY_WEBHOOK_URL") or "").strip() or None,
            timeout_s=float(src.get("OMC_NOTIFY_TIMEOUT_S", "5")),
        )


class Notifier:
    """No-op if webhook_url is missing. Safe to call from any code path."""

    def __init__(self, config: NotifyConfig | None = None):
        self.config = config or NotifyConfig.from_env()

    @property
    def enabled(self) -> bool:
        return bool(self.config.webhook_url)

    def notify(self, text: str) -> bool:
        if not self.enabled:
            return False
        payload = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            self.config.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_s) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"[notify] webhook POST failed: {e}", file=sys.stderr, flush=True)
            return False

    def task_terminal(
        self, *, project_id: str, task_id: str, status: str,
        cost_usd: float, attempts: int, reason: str | None = None,
    ) -> bool:
        icon = {"accepted": "✅", "blocked": "❌"}.get(status.lower(), "ℹ️")
        text = (
            f"{icon} omc task *{status}*: `{project_id}` / `{task_id}` "
            f"— attempts={attempts}, cost=${cost_usd:.4f}"
        )
        if reason:
            text += f"\n> {reason}"
        return self.notify(text)

    def budget_warn(
        self, *, project_id: str, spend_usd: float, limit_usd: float, pct: float,
    ) -> bool:
        return self.notify(
            f"⚠️ budget {pct:.0f}% used on `{project_id}`: "
            f"${spend_usd:.4f} / ${limit_usd:.2f}"
        )
