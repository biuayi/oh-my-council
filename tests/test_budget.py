from omc.budget import BudgetTracker, Limits


def test_tracker_counts_attempts():
    t = BudgetTracker(Limits())
    t.record_attempt("T001")
    t.record_attempt("T001")
    assert t.attempts("T001") == 2


def test_tracker_tokens_accumulate():
    t = BudgetTracker(Limits())
    t.record_tokens("T001", 100)
    t.record_tokens("T001", 50)
    assert t.tokens("T001") == 150


def test_attempts_exceeded_flag():
    t = BudgetTracker(Limits(l1_worker_retries=2))
    t.record_attempt("T001")
    t.record_attempt("T001")
    assert t.l1_exhausted("T001") is False  # exactly at limit, not over
    t.record_attempt("T001")
    assert t.l1_exhausted("T001") is True


def test_tokens_budget_exceeded():
    t = BudgetTracker(Limits(l3_task_tokens=1000))
    t.record_tokens("T001", 1001)
    assert t.l3_exhausted("T001") is True
