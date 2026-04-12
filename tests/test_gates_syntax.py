from pathlib import Path

from omc.gates.syntax import check_syntax


def test_valid_python_passes(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    result = check_syntax([f])
    assert result.ok is True
    assert result.offenders == []


def test_syntax_error_fails(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("def broken(:\n")
    result = check_syntax([f])
    assert result.ok is False
    assert str(f) in result.offenders[0]


def test_non_python_is_skipped(tmp_path: Path):
    f = tmp_path / "README.md"
    f.write_text("not python")
    result = check_syntax([f])
    assert result.ok is True
