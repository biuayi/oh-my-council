"""Tests for the hallucination gate (Task 7)."""

from pathlib import Path

from omc.gates.hallucination import check_symbols


def test_known_stdlib_import_ok(tmp_path: Path):
    res = check_symbols(
        [{"name": "json", "kind": "import", "file": "a.py"}],
        project_root=tmp_path,
    )
    assert res.ok is True


def test_unknown_import_flagged(tmp_path: Path):
    res = check_symbols(
        [{"name": "zzz_not_a_real_pkg", "kind": "import", "file": "a.py"}],
        project_root=tmp_path,
    )
    assert res.ok is False
    assert any("zzz_not_a_real_pkg" in o for o in res.offenders)


def test_known_call_ok(tmp_path: Path):
    res = check_symbols(
        [{"name": "json.loads", "kind": "call", "file": "a.py"}],
        project_root=tmp_path,
    )
    assert res.ok is True


def test_hallucinated_call_flagged(tmp_path: Path):
    res = check_symbols(
        [{"name": "json.nonexistent_fn", "kind": "call", "file": "a.py"}],
        project_root=tmp_path,
    )
    assert res.ok is False
    assert any("nonexistent_fn" in o for o in res.offenders)


def test_declared_dependency_counts_as_known(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["rich>=13"]\n'
    )
    res = check_symbols(
        [{"name": "rich", "kind": "import", "file": "a.py"}],
        project_root=tmp_path,
    )
    # Declared dep counts as known even if not installed in the test venv.
    assert res.ok is True
