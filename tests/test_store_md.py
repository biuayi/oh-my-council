from pathlib import Path

from omc.store.md import MDLayout


def test_scaffold_creates_directories(tmp_docs: Path):
    layout = MDLayout(tmp_docs / "projects" / "2026-04-12-demo")
    layout.scaffold()

    root = layout.root
    for sub in ("design", "tasks", "reviews", "audits", "artifacts"):
        assert (root / sub).is_dir(), f"{sub}/ missing"


def test_write_and_read_requirement(tmp_docs: Path):
    layout = MDLayout(tmp_docs / "projects" / "p")
    layout.scaffold()
    layout.write_requirement("# Req\n\nhello")
    assert layout.read_requirement() == "# Req\n\nhello"


def test_task_md_roundtrip(tmp_docs: Path):
    layout = MDLayout(tmp_docs / "projects" / "p")
    layout.scaffold()
    layout.write_task("T001", "# T001 spec\n\nbody")
    assert layout.read_task("T001") == "# T001 spec\n\nbody"
    assert layout.task_path("T001") == Path("tasks/T001.md")


def test_review_and_audit_md(tmp_docs: Path):
    layout = MDLayout(tmp_docs / "projects" / "p")
    layout.scaffold()
    layout.write_review("T001", "review text")
    layout.write_audit("T001", "audit text")
    assert layout.read_review("T001") == "review text"
    assert layout.read_audit("T001") == "audit text"
