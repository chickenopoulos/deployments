from __future__ import annotations

import argparse
import os
import time
from typing import Iterable

import pandas as pd
import requests
import yaml
from dotenv import load_dotenv
from tqdm import tqdm

from deployments.paths import CONFIG_DIR, DATA_DIR
from deployments.scrappers.binance_universe import load_binance_usdt_perpetual_universe

BASE_URL = "https://fapi.binance.com"
KLINES_ENDPOINT = "/fapi/v1/klines"
COINGLASS_UNIVERSE_URL = "https://open-api-v4.coinglass.com/api/futures/supported-exchange-pairs?exchange=Binance"

VALID_INTERVALS = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Binance futures OHLCV parquet files.")
    parser.add_argument(
        "--interval",
        choices=VALID_INTERVALS + ["all"],
        default="all",
        help="Binance kline interval to refresh. Use 'all' to refresh both configured jobs.",
    )
    parser.add_argument(
        "--start",
        default="2000-01-01",
        help="UTC start date for historical backfill, e.g. 2020-01-01",
    )
    return parser.parse_args()


def get_output_filename(interval: str) -> str:
    return f"binance_futures_ohlcv_{interval}.parquet"


def get_binance_futures_ohlcv(
    symbol: str = "BTCUSDT",
    interval: str = "1d",
    start_str: str = "2020-01-01",
    end_str: str | None = None,
    limit: int = 1500,
) -> pd.DataFrame:
    start_ts = int(pd.Timestamp(start_str, tz="UTC").timestamp() * 1000)
    end_ts = int((pd.Timestamp(end_str, tz="UTC") if end_str else pd.Timestamp.utcnow()).timestamp() * 1000)
    all_rows = []
    while start_ts < end_ts:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": limit,
        }
        resp = requests.get(BASE_URL + KLINES_ENDPOINT, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        all_rows.extend(data)
        last_open_time = data[-1][0]
        next_open_time = last_open_time + 1
        if next_open_time <= start_ts:
            break
        start_ts = next_open_time
        time.sleep(0.05)
        if len(data) < limit:
            break

    if not all_rows:
        return pd.DataFrame()

    cols = [
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_asset_volume", "number_of_trades",
        "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
    ]
    df = pd.DataFrame(all_rows, columns=cols)

    for c in [
        "open", "high", "low", "close", "volume",
        "quote_asset_volume", "taker_buy_base_asset_volume",
        "taker_buy_quote_asset_volume", "number_of_trades"
    ]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

    return (
        df[
            [
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_asset_volume", "number_of_trades"
            ]
        ]
        .drop_duplicates(subset=["open_time"])
        .reset_index(drop=True)
    )


def load_data_config() -> dict:
    with (CONFIG_DIR / "data.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_daily_universe(config: dict) -> list[str]:
    source = config.get("daily_universe_source", "binance")
    if source == "coinglass_binance_usdt_pairs":
        return load_coinglass_binance_usdt_universe()
    if source in ("binance", "binance_usdt_perpetuals"):
        return load_binance_usdt_perpetual_universe()
    raise ValueError(f"Unsupported daily_universe_source: {source}")


def load_coinglass_binance_usdt_universe() -> list[str]:
    load_dotenv()
    api_key = os.getenv("COINGLASS_API_KEY")
    if not api_key:
        raise EnvironmentError("COINGLASS_API_KEY is required to refresh the Binance daily universe")

    headers = {"accept": "application/json", "CG-API-KEY": api_key}
    response = requests.get(COINGLASS_UNIVERSE_URL, headers=headers, timeout=30)
    response.raise_for_status()
    payload = response.json().get("data", {}).get("Binance", [])
    frame = pd.DataFrame(payload)

    if frame.empty:
        return []

    return sorted(
        frame.loc[frame["quote_asset"] == "USDT", "instrument_id"]
        .dropna()
        .unique()
        .tolist()
    )


def refresh_symbols(
    symbols: Iterable[str],
    interval: str,
    output_filename: str,
    start_str: str = "2000-01-01",
) -> pd.DataFrame:
    frames = []

    for asset in tqdm(list(symbols), desc=f"binance {interval}"):
        try:
            frame = get_binance_futures_ohlcv(
                symbol=asset,
                interval=interval,
                start_str=start_str,
            )
        except Exception:
            continue

        if frame.empty:
            continue

        frame["asset"] = asset
        frames.append(frame)

    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    path = DATA_DIR / output_filename
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(path)
    return data


def main() -> None:
    args = parse_args()
    config = load_data_config().get("binance_ohlcv", {})

    if args.interval == "all":
        daily_symbols = resolve_daily_universe(config)
        refresh_symbols(
            daily_symbols,
            config.get("daily_interval", "1d"),
            "binance_futures_ohlcv_1d.parquet",
            start_str=args.start,
        )

        intraday_symbols = config.get("intraday_symbols", ["BTCUSDT"])
        refresh_symbols(
            intraday_symbols,
            config.get("intraday_interval", "1h"),
            "binance_futures_ohlcv_1h.parquet",
            start_str=args.start,
        )
        return

    if args.interval == config.get("daily_interval", "1d"):
        symbols = resolve_daily_universe(config)
    else:
        symbols = config.get("intraday_symbols", ["BTCUSDT"])

    refresh_symbols(
        symbols,
        args.interval,
        get_output_filename(args.interval),
        start_str=args.start,
    )


if __name__ == "__main__":
    main()