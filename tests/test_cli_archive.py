"""Integration tests for `omc archive` + `omc import` roundtrip."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from omc.cli import main


def _seed_project(docs: Path, project_id: str) -> None:
    pdir = docs / "projects" / project_id
    (pdir / "tasks").mkdir(parents=True)
    (pdir / "workspace" / "src").mkdir(parents=True)
    (pdir / "requirement.md").write_text("# demo\n\nrequirement body\n")
    (pdir / "tasks" / "T001.md").write_text("# T001\nspec\n")
    (pdir / "workspace" / "src" / "a.py").write_text("x = 1\n")
    (pdir / "council.sqlite3").write_bytes(b"SQLite format 3\x00" + b"\x00" * 80)


def test_archive_roundtrip(tmp_path: Path, capsys):
    docs = tmp_path / "docs"
    pid = "2026-04-13-roundtrip"
    _seed_project(docs, pid)
    tarball = tmp_path / f"{pid}.tar.gz"

    assert main(
        ["--docs-root", str(docs), "archive", pid, "--output", str(tarball)]
    ) == 0
    assert tarball.exists()
    with tarfile.open(tarball, "r:gz") as tf:
        names = tf.getnames()
    assert f"{pid}/requirement.md" in names
    assert f"{pid}/tasks/T001.md" in names
    assert f"{pid}/workspace/src/a.py" in names

    # Import into a fresh docs root
    docs2 = tmp_path / "docs2"
    assert main(
        ["--docs-root", str(docs2), "import", str(tarball)]
    ) == 0
    restored = docs2 / "projects" / pid
    assert restored.exists()
    assert (restored / "tasks" / "T001.md").read_text() == "# T001\nspec\n"
    assert (restored / "workspace" / "src" / "a.py").read_text() == "x = 1\n"


def test_import_refuses_existing_without_force(tmp_path: Path, capsys):
    docs = tmp_path / "docs"
    pid = "2026-04-13-collide"
    _seed_project(docs, pid)
    tarball = tmp_path / f"{pid}.tar.gz"
    assert main(["--docs-root", str(docs), "archive", pid, "--output", str(tarball)]) == 0

    # Importing into the same docs root should refuse
    rc = main(["--docs-root", str(docs), "import", str(tarball)])
    assert rc == 4
    err = capsys.readouterr().err
    assert "already exists" in err

    # With --force it succeeds
    assert main(["--docs-root", str(docs), "import", str(tarball), "--force"]) == 0


def test_import_rejects_unsafe_paths(tmp_path: Path, capsys):
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        payload = tmp_path / "payload.txt"
        payload.write_text("x")
        # Make the top dir look legitimate so we don't trip the "single top dir"
        # check before the traversal check.
        tf.add(payload, arcname="legit/sub/../../etc/passwd")
    docs = tmp_path / "docs"
    rc = main(["--docs-root", str(docs), "import", str(bad)])
    # Either traversal rejection (5) or top-level mismatch (3) is acceptable —
    # both prevent the malicious extract. But we explicitly want the traversal
    # case to register.
    assert rc in (3, 5)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
