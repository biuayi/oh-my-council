from datetime import datetime

from omc.models import (
    Interaction,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)


def test_project_minimal():
    p = Project(
        id="2026-04-12-demo",
        title="demo",
        status=ProjectStatus.PLANNING,
        root_path="docs/projects/2026-04-12-demo",
        created_at=datetime(2026, 4, 12, 0, 0, 0),
        updated_at=datetime(2026, 4, 12, 0, 0, 0),
    )
    assert p.id == "2026-04-12-demo"
    assert p.status is ProjectStatus.PLANNING


def test_task_default_counters():
    t = Task(
        id="T001",
        project_id="2026-04-12-demo",
        md_path="tasks/T001-hello.md",
        status=TaskStatus.PENDING,
        path_whitelist=["src/hello.py"],
    )
    assert t.attempts == 0
    assert t.codex_escalated == 0
    assert t.tokens_used == 0
    assert t.cost_usd == 0.0
    assert t.assignee is None


def test_interaction_requires_agents():
    i = Interaction(
        project_id="p",
        from_agent="orchestrator",
        to_agent="glm5",
        kind="request",
        content="hello",
    )
    assert i.from_agent == "orchestrator"
    assert i.tokens_in is None
