"""MD file layout for a single project. See spec §5.1."""

from __future__ import annotations

from pathlib import Path

_SUBDIRS = ("design", "tasks", "reviews", "audits", "artifacts")


class MDLayout:
    def __init__(self, root: Path):
        self.root = root

    def scaffold(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in _SUBDIRS:
            (self.root / sub).mkdir(exist_ok=True)

    def write_requirement(self, text: str) -> None:
        (self.root / "requirement.md").write_text(text, encoding="utf-8")

    def read_requirement(self) -> str:
        return (self.root / "requirement.md").read_text(encoding="utf-8")

    def task_path(self, task_id: str) -> Path:
        return Path("tasks") / f"{task_id}.md"

    def write_task(self, task_id: str, text: str) -> None:
        (self.root / "tasks" / f"{task_id}.md").write_text(text, encoding="utf-8")

    def read_task(self, task_id: str) -> str:
        return (self.root / "tasks" / f"{task_id}.md").read_text(encoding="utf-8")

    def write_review(self, task_id: str, text: str) -> None:
        (self.root / "reviews" / f"{task_id}.md").write_text(text, encoding="utf-8")

    def read_review(self, task_id: str) -> str:
        return (self.root / "reviews" / f"{task_id}.md").read_text(encoding="utf-8")

    def write_audit(self, task_id: str, text: str) -> None:
        (self.root / "audits" / f"{task_id}.md").write_text(text, encoding="utf-8")

    def read_audit(self, task_id: str) -> str:
        return (self.root / "audits" / f"{task_id}.md").read_text(encoding="utf-8")
