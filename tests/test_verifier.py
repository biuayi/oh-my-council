"""Unit tests for MilestoneVerifier."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from omc.clients.claude_cli import ClaudeResult
from omc.models import Task, TaskStatus
from omc.store.md import MDLayout
from omc.store.project import ProjectStore
from omc.verifier import MilestoneVerifier, VerdictOutput


def _seed(tmp_path: Path, task_status: TaskStatus = TaskStatus.ACCEPTED):
    project_root = tmp_path / "p"
    md = MDLayout(project_root)
    md.scaffold()
    md.write_requirement("# greet\n\nImplement greet(name).")
    store = ProjectStore(project_root / "council.sqlite3")
    now = datetime(2026, 4, 12)
    store.upsert_task(Task(
        id="T1", project_id="p", md_path="tasks/T1.md",
        status=task_status,
        path_whitelist=["src/generated/greet.py"],
        created_at=now, updated_at=now,
    ))
    return project_root, md, store


def test_verifier_accept(tmp_path: Path):
    _, md, store = _seed(tmp_path)
    cli = MagicMock()
    cli.run_once.return_value = ClaudeResult(
        stdout=json.dumps({
            "decision": "ACCEPT",
            "summary": "greet function complete",
            "next_actions": [],
        }),
        stderr="", returncode=0,
    )
    verifier = MilestoneVerifier(cli=cli)
    result = verifier.verify(store=store, md=md, project_id="p")
    assert isinstance(result, VerdictOutput)
    assert result.decision == "ACCEPT"
    assert "greet" in result.summary
    # prompt sent to Claude mentions requirement + task
    prompt = cli.run_once.call_args.args[0]
    assert "greet(name)" in prompt
    assert "T1" in prompt


def test_verifier_need_detail(tmp_path: Path):
    _, md, store = _seed(tmp_path)
    cli = MagicMock()
    cli.run_once.return_value = ClaudeResult(
        stdout=json.dumps({
            "decision": "NEED_DETAIL",
            "summary": "unclear return format",
            "next_actions": ["ask user to clarify return type"],
        }),
        stderr="", returncode=0,
    )
    verifier = MilestoneVerifier(cli=cli)
    result = verifier.verify(store=store, md=md, project_id="p")
    assert result.decision == "NEED_DETAIL"
    assert result.next_actions == ["ask user to clarify return type"]


def test_verifier_unparseable_output_is_reject(tmp_path: Path):
    _, md, store = _seed(tmp_path)
    cli = MagicMock()
    cli.run_once.return_value = ClaudeResult(
        stdout="garbled non-json output", stderr="", returncode=0,
    )
    verifier = MilestoneVerifier(cli=cli)
    result = verifier.verify(store=store, md=md, project_id="p")
    # fail-closed: unparseable = REJECT
    assert result.decision == "REJECT"
    assert "unparseable" in result.summary.lower()


def test_verifier_handles_fence_wrapped_json(tmp_path: Path):
    _, md, store = _seed(tmp_path)
    cli = MagicMock()
    cli.run_once.return_value = ClaudeResult(
        stdout=(
            "Here's my verdict:\n\n```json\n"
            + json.dumps({
                "decision": "ACCEPT",
                "summary": "ok",
                "next_actions": [],
            })
            + "\n```\n"
        ),
        stderr="", returncode=0,
    )
    verifier = MilestoneVerifier(cli=cli)
    result = verifier.verify(store=store, md=md, project_id="p")
    assert result.decision == "ACCEPT"
