from pathlib import Path

from omc.gates.secrets import scan_paths, scan_text


def test_catches_aws_access_key():
    r = scan_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"')
    assert any(f.rule == "aws_access_key" for f in r)


def test_catches_openai_style_key():
    r = scan_text('api_key = "sk-abcDEF1234567890abcDEF"')
    assert any(f.rule == "openai_key" for f in r)


def test_catches_anthropic_key():
    r = scan_text('token = "sk-ant-abcd1234efgh5678ijkl9012"')
    assert any(f.rule == "anthropic_key" for f in r)


def test_catches_private_key_block():
    r = scan_text("-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----")
    assert any(f.rule == "private_key_block" for f in r)


def test_catches_high_entropy_assignment():
    # 40-char base64-ish blob assigned to a *_token name
    r = scan_text('my_token = "Xk7PqLz92AbCdEfGhIj8mNoPqRsTuVwXyZ012345"')
    assert any(f.rule == "high_entropy_assignment" for f in r)


def test_ignores_placeholder_values():
    r = scan_text('API_KEY = "your-api-key-goes-here-changeme-example"')
    assert all(f.rule != "high_entropy_assignment" for f in r)


def test_ignores_low_entropy_strings():
    r = scan_text('PASSWORD = "passwordpasswordpassword"')
    assert all(f.rule != "high_entropy_assignment" for f in r)


def test_scan_paths_skips_binary_and_vendored(tmp_path: Path):
    (tmp_path / "node_modules" / "lib").mkdir(parents=True)
    (tmp_path / "node_modules" / "lib" / "leak.py").write_text(
        'AWS="AKIAIOSFODNN7EXAMPLE"'
    )
    (tmp_path / "real.py").write_text('AWS="AKIAIOSFODNN7EXAMPLE"')
    findings = scan_paths(tmp_path)
    paths = {f.path for f in findings}
    assert "real.py" in paths
    assert not any("node_modules" in p for p in paths)


def test_redaction_hides_full_secret():
    r = scan_text('API="AKIAIOSFODNN7EXAMPLE"')
    assert "AKIAIOSFODNN7EXAMPLE" not in r[0].snippet
    assert "..." in r[0].snippet


def test_cli_scan_returns_1_on_finding(tmp_path, monkeypatch, capsys):
    from omc.cli import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "leaky.py").write_text('KEY="AKIAIOSFODNN7EXAMPLE"')
    rc = main(["scan", "--path", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "aws_access_key" in out


def test_cli_scan_clean_returns_0(tmp_path, monkeypatch, capsys):
    from omc.cli import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "clean.py").write_text("x = 1\ny = 2\n")
    rc = main(["scan", "--path", str(tmp_path)])
    assert rc == 0
    assert "scan clean" in capsys.readouterr().out
