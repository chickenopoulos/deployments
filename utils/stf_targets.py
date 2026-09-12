"""Helpers so a fully-flat STF book still declares its universe.

``shadow-sim`` skips a strategy when ``targets`` is empty *and* the book has no
open positions. That meant id16/id17/id23–id29/id31–id33 never wrote equity
parquet while they were flat. Explicit zeros reach the mark path (same pattern
as id34/id35). Sign-change rebalance treats 0 the same as a missing name.
"""

from __future__ import annotations

from typing import Iterable, Mapping


def declared_weights(
    universe: Iterable[str],
    weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    raw = {str(k): float(v) for k, v in (weights or {}).items()}
    out = {str(sym): float(raw.get(str(sym), 0.0)) for sym in universe}
    for key, value in raw.items():
        out.setdefault(str(key), float(value))
    return out
