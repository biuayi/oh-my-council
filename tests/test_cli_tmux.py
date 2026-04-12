from unittest.mock import MagicMock, patch

from omc.cli import main


def test_tmux_builds_session_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "projects" / "p1").mkdir(parents=True)

    with patch("subprocess.run") as sr:
        sr.return_value = MagicMock(returncode=0, stderr="")
        rc = main(["tmux", "p1"])
    assert rc == 0
    commands = [c.args[0] for c in sr.call_args_list]
    joined = " ".join(" ".join(c) for c in commands)
    assert "new-session" in joined
    assert "split-window" in joined


def test_tmux_missing_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = main(["tmux", "nope"])
    assert rc == 2
