"""Per-model USD price table + cost calculator.

Defaults are hardcoded against public list prices (see docs/phase3c-budget-setup.md
for sources and refresh policy). User can override via
~/.config/oh-my-council/prices.toml with the same shape:

    [prices."minimax-text-01"]
    in_usd_per_mtok = 0.20
    out_usd_per_mtok = 1.10

Unknown models yield zero cost (warned but not fatal) so a new vendor can be
trialled without blocking the run; the user should add the model to the
override file once they confirm the spend pattern.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PRICES_PATH = Path.home() / ".config" / "oh-my-council" / "prices.toml"


@dataclass(slots=True, frozen=True)
class ModelPrice:
    in_usd_per_mtok: float
    out_usd_per_mtok: float


# Public list prices in USD per 1M tokens (in, out). Refresh when vendors change.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    # MiniMax
    "minimax-text-01":        ModelPrice(0.20, 1.10),
    "minimax-m1":             ModelPrice(0.40, 2.20),
    # Zhipu GLM
    "glm-4.6":                ModelPrice(0.60, 2.20),
    "glm-4.5":                ModelPrice(0.50, 2.00),
    "glm-4.5-air":            ModelPrice(0.20, 1.10),
    # Google Gemini
    "gemini-2.5-pro":         ModelPrice(1.25, 10.00),
    "gemini-2.5-flash":       ModelPrice(0.30, 2.50),
    "gemini-2.5-flash-lite":  ModelPrice(0.10, 0.40),
    # OpenAI (reference — Codex CLI doesn't expose usage yet, kept for manual use)
    "gpt-5-codex":            ModelPrice(1.25, 10.00),
    # Anthropic (reference — claude -p usage via API billing, not local meter)
    "claude-opus-4":          ModelPrice(15.00, 75.00),
    "claude-sonnet-4":        ModelPrice(3.00, 15.00),
    "claude-haiku-4":         ModelPrice(1.00, 5.00),
}


def compute_cost(
    model: str,
    tokens_in: int,
    tokens_out: int,
    prices: dict[str, ModelPrice],
) -> float:
    p = prices.get(model)
    if p is None:
        return 0.0
    return (tokens_in / 1_000_000) * p.in_usd_per_mtok + (
        tokens_out / 1_000_000
    ) * p.out_usd_per_mtok


def load_prices(path: Path | None = None) -> dict[str, ModelPrice]:
    target = path if path is not None else DEFAULT_PRICES_PATH
    merged = dict(DEFAULT_PRICES)
    if not target.exists():
        return merged
    with target.open("rb") as f:
        doc = tomllib.load(f)
    overrides = doc.get("prices", {})
    for name, entry in overrides.items():
        merged[name] = ModelPrice(
            in_usd_per_mtok=float(entry["in_usd_per_mtok"]),
            out_usd_per_mtok=float(entry["out_usd_per_mtok"]),
        )
    return merged
