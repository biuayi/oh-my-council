import pytest

from omc.models import TaskStatus
from omc.state import InvalidTransition, StateEvent, next_state


def test_pending_to_running_on_start():
    assert next_state(TaskStatus.PENDING, StateEvent.WORKER_START) == TaskStatus.RUNNING


def test_running_to_review_on_worker_done():
    assert next_state(TaskStatus.RUNNING, StateEvent.WORKER_DONE) == TaskStatus.REVIEW


def test_review_to_audit_on_review_pass():
    assert next_state(TaskStatus.REVIEW, StateEvent.REVIEW_PASS) == TaskStatus.AUDIT


def test_audit_to_accepted_on_audit_pass():
    assert next_state(TaskStatus.AUDIT, StateEvent.AUDIT_PASS) == TaskStatus.ACCEPTED


def test_review_fail_goes_back_to_pending():
    assert next_state(TaskStatus.REVIEW, StateEvent.REVIEW_FAIL) == TaskStatus.PENDING


def test_running_budget_exceeded_goes_to_over_budget():
    assert (
        next_state(TaskStatus.RUNNING, StateEvent.BUDGET_EXCEEDED)
        == TaskStatus.OVER_BUDGET
    )


def test_running_blocked_on_escalation_exhausted():
    assert (
        next_state(TaskStatus.RUNNING, StateEvent.ESCALATION_EXHAUSTED)
        == TaskStatus.BLOCKED
    )


def test_review_budget_exceeded_goes_to_over_budget():
    assert (
        next_state(TaskStatus.REVIEW, StateEvent.BUDGET_EXCEEDED)
        == TaskStatus.OVER_BUDGET
    )


def test_audit_budget_exceeded_goes_to_over_budget():
    assert (
        next_state(TaskStatus.AUDIT, StateEvent.BUDGET_EXCEEDED)
        == TaskStatus.OVER_BUDGET
    )


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransition):
        next_state(TaskStatus.ACCEPTED, StateEvent.WORKER_START)
