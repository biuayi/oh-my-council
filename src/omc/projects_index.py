from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")


@dataclass(slots=True, frozen=True)
class ProjectSummary:
    slug: str
    project_id: str
    path: Path
    has_sqlite: bool
    has_requirement: bool


def list_projects(docs_root: Path) -> list[ProjectSummary]:
    """List all projects under <docs_root>/projects/.

    Only directories matching pattern 'YYYY-MM-DD-<slug>' are included.
    Returns empty list if projects/ does not exist. Results sorted by
    project_id ascending.
    """
    projects_dir = docs_root / "projects"
    if not projects_dir.is_dir():
        return []

    summaries: list[ProjectSummary] = []
    for child in projects_dir.iterdir():
        if not child.is_dir():
            continue
        project_id = child.name
        if PROJECT_DIR_RE.fullmatch(project_id) is None:
            continue

        summaries.append(
            ProjectSummary(
                slug=project_id[11:],
                project_id=project_id,
                path=child.resolve(),
                has_sqlite=(child / "council.sqlite3").is_file(),
                has_requirement=(child / "requirement.md").is_file(),
            )
        )

    return sorted(summaries, key=lambda item: item.project_id)
