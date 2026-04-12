from unittest.mock import patch

from omc.cli import main


def test_cli_mcp_dispatches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("omc.cli.run_stdio") as rs:
        rc = main(["mcp"])
    assert rc == 0
    rs.assert_called_once()
