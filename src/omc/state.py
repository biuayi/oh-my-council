"""Task state machine (pure). See spec §3."""

from __future__ import annotations

from enum import StrEnum

from omc.models import TaskStatus


class StateEvent(StrEnum):
    WORKER_START = "worker_start"
    WORKER_DONE = "worker_done"
    WORKER_FAIL = "worker_fail"
    REVIEW_PASS = "review_pass"
    REVIEW_FAIL = "review_fail"
    AUDIT_PASS = "audit_pass"
    AUDIT_FAIL = "audit_fail"
    BUDGET_EXCEEDED = "budget_exceeded"
    ESCALATION_EXHAUSTED = "escalation_exhausted"


class InvalidTransition(Exception):
    pass


_TRANSITIONS: dict[tuple[TaskStatus, StateEvent], TaskStatus] = {
    (TaskStatus.PENDING, StateEvent.WORKER_START): TaskStatus.RUNNING,
    (TaskStatus.RUNNING, StateEvent.WORKER_DONE): TaskStatus.REVIEW,
    (TaskStatus.RUNNING, StateEvent.WORKER_FAIL): TaskStatus.PENDING,
    (TaskStatus.RUNNING, StateEvent.BUDGET_EXCEEDED): TaskStatus.OVER_BUDGET,
    (TaskStatus.RUNNING, StateEvent.ESCALATION_EXHAUSTED): TaskStatus.BLOCKED,
    (TaskStatus.REVIEW, StateEvent.REVIEW_PASS): TaskStatus.AUDIT,
    (TaskStatus.REVIEW, StateEvent.REVIEW_FAIL): TaskStatus.PENDING,
    (TaskStatus.REVIEW, StateEvent.ESCALATION_EXHAUSTED): TaskStatus.BLOCKED,
    (TaskStatus.AUDIT, StateEvent.AUDIT_PASS): TaskStatus.ACCEPTED,
    (TaskStatus.AUDIT, StateEvent.AUDIT_FAIL): TaskStatus.PENDING,
    (TaskStatus.AUDIT, StateEvent.ESCALATION_EXHAUSTED): TaskStatus.BLOCKED,
}


def next_state(current: TaskStatus, event: StateEvent) -> TaskStatus:
    key = (current, event)
    if key not in _TRANSITIONS:
        raise InvalidTransition(f"no transition from {current} on {event}")
    return _TRANSITIONS[key]
