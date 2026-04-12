"""Unit tests for omc verify CLI subcommand."""

from unittest.mock import patch

from omc.cli import main
from omc.verifier import VerdictOutput


def test_verify_prints_decision(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "projects" / "p1").mkdir(parents=True)
    with patch("omc.cli.MilestoneVerifier") as MV:
        MV.return_value.verify.return_value = VerdictOutput(
            decision="ACCEPT", summary="all good", next_actions=[],
        )
        rc = main(["verify", "p1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ACCEPT" in out
    assert "all good" in out


def test_verify_need_detail_returns_3(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "projects" / "p1").mkdir(parents=True)
    with patch("omc.cli.MilestoneVerifier") as MV:
        MV.return_value.verify.return_value = VerdictOutput(
            decision="NEED_DETAIL", summary="x", next_actions=["ask about y"],
        )
        rc = main(["verify", "p1"])
    assert rc == 3


def test_verify_missing_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = main(["verify", "nope"])
    assert rc == 2
