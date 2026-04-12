"""`omc budget <project>` subcommand — prints spend summary."""

from __future__ import annotations

from pathlib import Path

from omc.cli import main
from omc.models import Interaction
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _seed_project(docs_root: Path, slug: str = "sample") -> str:
    project_id = f"2026-04-12-{slug}"
    project_dir = docs_root / "projects" / project_id
    project_dir.mkdir(parents=True)
    store = ProjectStore(project_dir / "council.sqlite3")
    # Two interactions totaling $1.25
    store.append_interaction(Interaction(
        project_id=project_id, task_id="T001",
        from_agent="glm5", to_agent="orchestrator", kind="response",
        content="ok", tokens_in=1000, tokens_out=500, cost_usd=0.75,
    ))
    store.append_interaction(Interaction(
        project_id=project_id, task_id="T001",
        from_agent="codex", to_agent="orchestrator", kind="review",
        content="ok", tokens_in=500, tokens_out=200, cost_usd=0.50,
    ))
    md = MDLayout(project_dir)
    md.scaffold()
    return project_id


def test_budget_prints_total_and_breakdown(tmp_path, capsys):
    _seed_project(tmp_path)
    rc = main(["--docs-root", str(tmp_path), "budget", "sample"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "$1.25" in out or "1.25" in out
    assert "glm5" in out
    assert "codex" in out
    assert "$5.00" in out or "5.00" in out  # L4 limit shown


def test_budget_missing_project_returns_2(tmp_path, capsys):
    rc = main(["--docs-root", str(tmp_path), "budget", "nope"])
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()
