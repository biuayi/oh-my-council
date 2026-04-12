"""Global project index (docs/index.sqlite3). See spec §5.2."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from omc.models import Project, ProjectStatus
from omc.store.schema import INDEX_DDL


class IndexStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(INDEX_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_project(self, p: Project) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO projects (id, title, status, root_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title      = excluded.title,
                    status     = excluded.status,
                    root_path  = excluded.root_path,
                    updated_at = excluded.updated_at
                """,
                (
                    p.id,
                    p.title,
                    p.status.value,
                    p.root_path,
                    p.created_at.isoformat(),
                    p.updated_at.isoformat(),
                ),
            )

    def list_projects(self) -> list[Project]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, title, status, root_path, created_at, updated_at "
                "FROM projects ORDER BY created_at DESC"
            ).fetchall()
        return [
            Project(
                id=r["id"],
                title=r["title"],
                status=ProjectStatus(r["status"]),
                root_path=r["root_path"],
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
            )
            for r in rows
        ]
