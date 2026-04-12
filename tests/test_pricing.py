"""Price table + compute_cost. See plan §Task 1."""

from __future__ import annotations

from pathlib import Path

from omc.pricing import DEFAULT_PRICES, ModelPrice, compute_cost, load_prices


def test_default_prices_include_known_models():
    assert "minimax-text-01" in DEFAULT_PRICES
    assert "glm-4.6" in DEFAULT_PRICES
    assert "gemini-2.5-flash" in DEFAULT_PRICES
    for p in DEFAULT_PRICES.values():
        assert p.in_usd_per_mtok >= 0
        assert p.out_usd_per_mtok >= 0


def test_compute_cost_basic():
    prices = {"m": ModelPrice(in_usd_per_mtok=1.0, out_usd_per_mtok=3.0)}
    # 1M in + 1M out = 1 + 3 = 4 USD
    assert compute_cost("m", 1_000_000, 1_000_000, prices) == 4.0
    # 500k in + 250k out = 0.5 + 0.75 = 1.25
    assert compute_cost("m", 500_000, 250_000, prices) == 1.25


def test_compute_cost_unknown_model_returns_zero():
    assert compute_cost("unknown-xyz", 10_000, 10_000, {}) == 0.0


def test_compute_cost_zero_tokens():
    prices = {"m": ModelPrice(in_usd_per_mtok=5.0, out_usd_per_mtok=5.0)}
    assert compute_cost("m", 0, 0, prices) == 0.0


def test_load_prices_merges_override_file(tmp_path: Path):
    override = tmp_path / "prices.toml"
    override.write_text(
        '[prices."minimax-text-01"]\n'
        'in_usd_per_mtok = 99.0\n'
        'out_usd_per_mtok = 199.0\n'
        '[prices."custom-model"]\n'
        'in_usd_per_mtok = 0.1\n'
        'out_usd_per_mtok = 0.2\n',
        encoding="utf-8",
    )
    prices = load_prices(override)
    # override wins
    assert prices["minimax-text-01"].in_usd_per_mtok == 99.0
    # new entry added
    assert prices["custom-model"].out_usd_per_mtok == 0.2
    # unmerged defaults still present
    assert "glm-4.6" in prices


def test_load_prices_missing_file_returns_defaults(tmp_path: Path):
    prices = load_prices(tmp_path / "nope.toml")
    assert prices == DEFAULT_PRICES
