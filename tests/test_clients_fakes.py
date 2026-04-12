from omc.clients.base import ReviewOutput, WorkerOutput
from omc.clients.fake_auditor import FakeAuditor
from omc.clients.fake_codex import FakeCodexClient
from omc.clients.fake_worker import FakeWorkerRunner


def test_fake_codex_default_spec():
    c = FakeCodexClient()
    s = c.produce_spec("T001", "requirement text")
    assert s.task_id == "T001"
    assert "T001" in s.spec_md
    assert s.path_whitelist == ["src/generated/T001.py"]


def test_fake_codex_scripted_reviews_cycle():
    c = FakeCodexClient(
        reviews={
            "T001": [
                ReviewOutput(task_id="T001", passed=False, review_md="fail1"),
                ReviewOutput(task_id="T001", passed=True, review_md="pass"),
            ]
        }
    )
    assert c.review("T001", {}, "").passed is False
    assert c.review("T001", {}, "").passed is True
    # further calls stick on last
    assert c.review("T001", {}, "").passed is True


def test_fake_worker_default_output():
    w = FakeWorkerRunner()
    out = w.write("T001", "# spec")
    assert "src/generated/T001.py" in out.files


def test_fake_worker_scripted():
    w = FakeWorkerRunner(
        outputs={
            "T001": [
                WorkerOutput(task_id="T001", files={"src/a.py": "broken(:"}),
                WorkerOutput(task_id="T001", files={"src/a.py": "x = 1\n"}),
            ]
        }
    )
    assert "broken(:" in w.write("T001", "").files["src/a.py"]
    assert w.write("T001", "").files["src/a.py"] == "x = 1\n"


def test_fake_auditor_default_passes():
    a = FakeAuditor()
    r = a.audit("T001", {"src/a.py": "x=1"})
    assert r.passed is True
