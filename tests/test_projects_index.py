from pathlib import Path

from omc.projects_index import ProjectSummary, list_projects


def test_list_projects_empty_docs_root(tmp_path: Path) -> None:
    assert list_projects(tmp_path) == []


def test_list_projects_skips_invalid_names(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / ".DS_Store").write_text("", encoding="utf-8")
    (projects_dir / "random").mkdir()
    valid_dir = projects_dir / "2026-04-12-ok"
    valid_dir.mkdir()

    result = list_projects(tmp_path)

    assert len(result) == 1
    assert result[0] == ProjectSummary(
        slug="ok",
        project_id="2026-04-12-ok",
        path=valid_dir.resolve(),
        has_sqlite=False,
        has_requirement=False,
    )


def test_list_projects_detects_sqlite_and_requirement(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    rich_dir = projects_dir / "2026-04-12-alpha"
    rich_dir.mkdir()
    (rich_dir / "council.sqlite3").write_text("", encoding="utf-8")
    (rich_dir / "requirement.md").write_text("# requirement\n", encoding="utf-8")

    bare_dir = projects_dir / "2026-04-13-beta"
    bare_dir.mkdir()

    result = list_projects(tmp_path)

    assert result == [
        ProjectSummary(
            slug="alpha",
            project_id="2026-04-12-alpha",
            path=rich_dir.resolve(),
            has_sqlite=True,
            has_requirement=True,
        ),
        ProjectSummary(
            slug="beta",
            project_id="2026-04-13-beta",
            path=bare_dir.resolve(),
            has_sqlite=False,
            has_requirement=False,
        ),
    ]


def test_list_projects_sorted_by_project_id(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    for name in [
        "2026-04-14-charlie",
        "2026-04-12-alpha",
        "2026-04-13-bravo",
    ]:
        (projects_dir / name).mkdir()

    result = list_projects(tmp_path)

    assert [item.project_id for item in result] == [
        "2026-04-12-alpha",
        "2026-04-13-bravo",
        "2026-04-14-charlie",
    ]
