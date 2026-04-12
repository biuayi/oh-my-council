from omc.gates.path_whitelist import GateResult, check_paths


def test_all_paths_allowed():
    result = check_paths(produced=["src/a.py"], whitelist=["src/a.py"])
    assert result == GateResult(ok=True, offenders=[])


def test_offender_detected():
    result = check_paths(
        produced=["src/a.py", "src/secret.py"], whitelist=["src/a.py"]
    )
    assert result.ok is False
    assert result.offenders == ["src/secret.py"]


def test_empty_produced_is_ok():
    result = check_paths(produced=[], whitelist=["src/a.py"])
    assert result.ok is True
