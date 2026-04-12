"""SQL DDL for oh-my-council. See spec §5.2."""

INDEX_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL,
    root_path   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

PROJECT_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    milestone_id    TEXT,
    md_path         TEXT NOT NULL,
    status          TEXT NOT NULL,
    assignee        TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    codex_escalated INTEGER NOT NULL DEFAULT 0,
    tokens_used     INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0.0,
    path_whitelist  TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    task_id     TEXT,
    from_agent  TEXT NOT NULL,
    to_agent    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    content     TEXT NOT NULL,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    cost_usd    REAL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compression_checkpoints (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT NOT NULL,
    task_id       TEXT,
    agent         TEXT NOT NULL,
    reason        TEXT,
    summary       TEXT NOT NULL,
    carry_forward TEXT NOT NULL,
    dropped_refs  TEXT,
    created_at    TEXT NOT NULL
);
"""
