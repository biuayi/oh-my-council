"""Per-project sqlite store (council.sqlite3). See spec §5.2."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from omc.models import CompressionCheckpoint, Interaction, Task, TaskStatus
from omc.store.schema import PROJECT_DDL


class ProjectStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(PROJECT_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_task(self, t: Task) -> None:
        now_iso = (t.updated_at or datetime.now()).isoformat()
        created_iso = (t.created_at or datetime.now()).isoformat()
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO tasks (
                    id, project_id, milestone_id, md_path, status, assignee,
                    attempts, codex_escalated, tokens_used, cost_usd,
                    path_whitelist, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    milestone_id    = excluded.milestone_id,
                    status          = excluded.status,
                    assignee        = excluded.assignee,
                    attempts        = excluded.attempts,
                    codex_escalated = excluded.codex_escalated,
                    tokens_used     = excluded.tokens_used,
                    cost_usd        = excluded.cost_usd,
                    path_whitelist  = excluded.path_whitelist,
                    updated_at      = excluded.updated_at
                """,
                (
                    t.id,
                    t.project_id,
                    t.milestone_id,
                    t.md_path,
                    t.status.value,
                    t.assignee,
                    t.attempts,
                    t.codex_escalated,
                    t.tokens_used,
                    t.cost_usd,
                    json.dumps(t.path_whitelist),
                    created_iso,
                    now_iso,
                ),
            )

    def get_task(self, task_id: str) -> Task | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        with self._conn() as c:
            if status is None:
                rows = c.execute("SELECT * FROM tasks ORDER BY id").fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY id", (status.value,)
                ).fetchall()
        return [_row_to_task(r) for r in rows]

    def append_interaction(self, i: Interaction) -> None:
        now_iso = (i.created_at or datetime.now()).isoformat()
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO interactions (
                    project_id, task_id, from_agent, to_agent, kind, content,
                    tokens_in, tokens_out, cost_usd, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    i.project_id,
                    i.task_id,
                    i.from_agent,
                    i.to_agent,
                    i.kind,
                    i.content,
                    i.tokens_in,
                    i.tokens_out,
                    i.cost_usd,
                    now_iso,
                ),
            )

    def list_interactions(self, task_id: str | None = None) -> list[Interaction]:
        with self._conn() as c:
            if task_id is None:
                rows = c.execute("SELECT * FROM interactions ORDER BY id").fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM interactions WHERE task_id = ? ORDER BY id",
                    (task_id,),
                ).fetchall()
        return [_row_to_interaction(r) for r in rows]

    def recent_interactions(self, limit: int = 20) -> list[Interaction]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM interactions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_interaction(r) for r in rows]

    def append_checkpoint(self, cp: CompressionCheckpoint) -> None:
        now_iso = (cp.created_at or datetime.now()).isoformat()
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO compression_checkpoints (
                    project_id, task_id, agent, reason, summary,
                    carry_forward, dropped_refs, created_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    cp.project_id,
                    cp.task_id,
                    cp.agent,
                    cp.reason,
                    cp.summary,
                    cp.carry_forward,
                    cp.dropped_refs,
                    now_iso,
                ),
            )


def _row_to_task(r: sqlite3.Row) -> Task:
    return Task(
        id=r["id"],
        project_id=r["project_id"],
        milestone_id=r["milestone_id"],
        md_path=r["md_path"],
        status=TaskStatus(r["status"]),
        assignee=r["assignee"],
        attempts=r["attempts"],
        codex_escalated=r["codex_escalated"],
        tokens_used=r["tokens_used"],
        cost_usd=r["cost_usd"],
        path_whitelist=json.loads(r["path_whitelist"]),
        created_at=datetime.fromisoformat(r["created_at"]),
        updated_at=datetime.fromisoformat(r["updated_at"]),
    )


def _row_to_interaction(r: sqlite3.Row) -> Interaction:
    return Interaction(
        id=r["id"],
        project_id=r["project_id"],
        task_id=r["task_id"],
        from_agent=r["from_agent"],
        to_agent=r["to_agent"],
        kind=r["kind"],
        content=r["content"],
        tokens_in=r["tokens_in"],
        tokens_out=r["tokens_out"],
        cost_usd=r["cost_usd"],
        created_at=datetime.fromisoformat(r["created_at"]),
    )
