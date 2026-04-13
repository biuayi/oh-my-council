from unittest.mock import patch

from omc.budget import BudgetTracker, Limits
from omc.notify import Notifier, NotifyConfig


def test_disabled_without_webhook_url():
    n = Notifier(NotifyConfig(webhook_url=None))
    assert n.enabled is False
    assert n.notify("hello") is False  # no-op


def test_enabled_when_url_set():
    n = Notifier(NotifyConfig(webhook_url="http://example.test/hook"))
    assert n.enabled is True


def test_notify_posts_slack_shaped_json():
    n = Notifier(NotifyConfig(webhook_url="http://example.test/hook"))
    with patch("omc.notify.urllib.request.urlopen") as m:
        m.return_value.__enter__.return_value.status = 200
        ok = n.notify("hi")
    assert ok is True
    req = m.call_args[0][0]
    assert req.method == "POST"
    assert req.get_header("Content-type") == "application/json"
    assert b'"text":' in req.data
    assert b"hi" in req.data


def test_task_terminal_formats_message():
    n = Notifier(NotifyConfig(webhook_url="http://example.test/hook"))
    with patch.object(n, "notify", return_value=True) as m:
        n.task_terminal(
            project_id="p1", task_id="T001", status="accepted",
            cost_usd=0.0123, attempts=2, reason="AUDIT_PASS",
        )
    msg = m.call_args[0][0]
    assert "accepted" in msg
    assert "p1" in msg
    assert "T001" in msg
    assert "$0.0123" in msg
    assert "AUDIT_PASS" in msg


def test_budget_warn_fires_notifier_on_80pct_cross():
    events: list[dict] = []

    class Spy:
        enabled = True

        def budget_warn(self, **kw):
            events.append(kw)

    limits = Limits(l4_project_usd=1.0)
    b = BudgetTracker(limits, project_id="demo", notifier=Spy())
    b.record_cost(0.5)
    assert events == []
    b.record_cost(0.4)  # now $0.9 — crossed 80%
    assert len(events) == 1
    assert events[0]["project_id"] == "demo"
    assert events[0]["pct"] >= 80


def test_network_error_is_swallowed():
    n = Notifier(NotifyConfig(webhook_url="http://127.0.0.1:1/does-not-exist"))
    # Should not raise; returns False after urllib.error.URLError
    assert n.notify("hi") is False
