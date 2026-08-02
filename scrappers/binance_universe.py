"""Fetch Binance USDT-M perpetual futures universe (no Coinglass dependency)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd
import requests

from deployments.paths import DATA_DIR

BASE_URL = "https://fapi.binance.com"
EXCHANGE_INFO_ENDPOINT = "/fapi/v1/exchangeInfo"
UNIVERSE_FILENAME = "binance_usdt_perpetual_universe.parquet"


def fetch_binance_usdt_perpetual_symbols() -> list[str]:
    """Return sorted TRADING USDT-M perpetual symbols from Binance futures exchangeInfo."""
    response = requests.get(BASE_URL + EXCHANGE_INFO_ENDPOINT, timeout=30)
    response.raise_for_status()
    payload = response.json()

    symbols: list[str] = []
    for item in payload.get("symbols", []):
        if (
            item.get("status") == "TRADING"
            and item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
        ):
            symbols.append(str(item["symbol"]))

    return sorted(set(symbols))


def save_universe_snapshot(symbols: list[str], *, as_of: datetime | None = None) -> pd.DataFrame:
    """Persist the latest universe list for auditing and offline use."""
    ts = as_of or datetime.now(timezone.utc)
    frame = pd.DataFrame(
        {
            "symbol": symbols,
            "quote_asset": "USDT",
            "contract_type": "PERPETUAL",
            "source": "binance_fapi_exchangeInfo",
            "as_of": ts,
        }
    )
    path = DATA_DIR / UNIVERSE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame


def load_binance_usdt_perpetual_universe(*, refresh: bool = False) -> list[str]:
    """Load the daily OHLCV universe from Binance; refresh from API when requested."""
    path = DATA_DIR / UNIVERSE_FILENAME
    if not refresh and path.exists():
        frame = pd.read_parquet(path)
        if "symbol" in frame.columns and not frame.empty:
            return sorted(frame["symbol"].dropna().astype(str).unique().tolist())

    symbols = fetch_binance_usdt_perpetual_symbols()
    if not symbols:
        raise RuntimeError("Binance exchangeInfo returned an empty USDT perpetual universe")
    save_universe_snapshot(symbols)
    return symbols


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Binance USDT-M perpetual universe parquet.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force refresh from Binance API (default when parquet is missing).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = load_binance_usdt_perpetual_universe(refresh=True if args.refresh else not (DATA_DIR / UNIVERSE_FILENAME).exists())
    print(f"Saved {len(symbols)} symbols to {DATA_DIR / UNIVERSE_FILENAME}")


if __name__ == "__main__":
    main()
