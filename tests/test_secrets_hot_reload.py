import json
from pathlib import Path

from omc.gates.secrets import load_extra_rules, scan_paths, scan_text


def test_load_extra_rules_missing_env_returns_empty(monkeypatch):
    monkeypatch.delenv("OMC_SECRETS_RULES", raising=False)
    assert load_extra_rules() == ()


def test_load_extra_rules_missing_file_warns(monkeypatch, capsys):
    monkeypatch.setenv("OMC_SECRETS_RULES", "/tmp/does-not-exist-xyz.json")
    assert load_extra_rules() == ()
    assert "not found" in capsys.readouterr().err


def test_load_extra_rules_bad_json(tmp_path: Path, capsys):
    f = tmp_path / "rules.json"
    f.write_text("this is not json")
    assert load_extra_rules(f) == ()
    assert "failed to load" in capsys.readouterr().err


def test_load_extra_rules_skips_invalid_entries(tmp_path: Path, capsys):
    f = tmp_path / "rules.json"
    f.write_text(json.dumps([
        {"name": "good", "pattern": r"COMPANY-[A-Z]{6}"},
        {"name": "bad_regex", "pattern": r"["},          # unclosed char class
        {"pattern": r"MYSECRET[0-9]+"},                    # missing name
        "not a dict",
    ]))
    rules = load_extra_rules(f)
    names = [n for n, _ in rules]
    # Only the "good" one and the auto-named "custom_2" (missing name still
    # gets an auto-name) survive. "bad_regex" is rejected.
    assert "good" in names
    assert "custom_2" in names
    assert "bad_regex" not in names
    err = capsys.readouterr().err
    assert "bad regex" in err


def test_custom_rule_matches_in_scan_text(tmp_path: Path):
    f = tmp_path / "rules.json"
    f.write_text(json.dumps([
        {"name": "company_token", "pattern": r"\bACME-[A-Z0-9]{10}\b"},
    ]))
    rules = load_extra_rules(f)
    findings = scan_text("leak = ACME-ABCD123456", extra_rules=rules)
    assert any(f_.rule == "company_token" for f_ in findings)


def test_scan_paths_hot_reloads_from_env(tmp_path: Path, monkeypatch):
    # Write a rule file, point env at it, scan, edit rule, scan again —
    # the second scan should pick up the new rule without restart.
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps([
        {"name": "foo_rule", "pattern": r"\bFOO-[A-Z]{5}\b"},
    ]))
    src = tmp_path / "code.py"
    src.write_text("a = 'FOO-ABCDE'\nb = 'BAR-VWXYZ'\n")
    monkeypatch.setenv("OMC_SECRETS_RULES", str(rules_file))

    # First scan: matches FOO only
    f1 = scan_paths(tmp_path, paths=[src])
    names1 = {f.rule for f in f1}
    assert "foo_rule" in names1

    # Edit rules file — swap FOO for BAR
    rules_file.write_text(json.dumps([
        {"name": "bar_rule", "pattern": r"\bBAR-[A-Z]{5}\b"},
    ]))
    f2 = scan_paths(tmp_path, paths=[src])
    names2 = {f.rule for f in f2}
    assert "bar_rule" in names2
    assert "foo_rule" not in names2
