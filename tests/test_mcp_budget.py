"""MCP omc_budget tool."""

from __future__ import annotations

from pathlib import Path

from omc.mcp_server import _omc_budget_impl
from omc.models import Interaction
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


def _seed(docs_root: Path) -> None:
    pdir = docs_root / "projects" / "2026-04-12-ex"
    pdir.mkdir(parents=True)
    s = ProjectStore(pdir / "council.sqlite3")
    pid = "2026-04-12-ex"
    s.append_interaction(Interaction(
        project_id=pid, task_id=None, from_agent="glm5", to_agent="orchestrator",
        kind="response", content="x", cost_usd=1.5,
    ))
    MDLayout(pdir).scaffold()


def test_omc_budget_impl_returns_spend_and_limit(tmp_path):
    _seed(tmp_path)
    result = _omc_budget_impl(tmp_path, "ex")
    assert result["slug"] == "ex"  # This will be the title extracted from project_id
    assert abs(result["spend_usd"] - 1.5) < 1e-6
    assert result["limit_usd"] == 5.0
    assert "glm5" in result["by_agent"]


def test_omc_budget_impl_missing_project(tmp_path):
    result = _omc_budget_impl(tmp_path, "nope")
    assert "error" in result
