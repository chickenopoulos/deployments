"""Yahoo Finance daily OHLCV for cash equities/ETFs (temporary until IBKR)."""

from __future__ import annotations

import argparse

import pandas as pd
import yaml

from deployments.paths import CONFIG_DIR, DATA_DIR

DEFAULT_SYMBOLS = ["SPY"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh yfinance OHLCV parquet files.")
    parser.add_argument("--interval", default="1d", help="yfinance interval (default 1d)")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Tickers to refresh (default: config data.yaml yfinance_ohlcv.symbols or SPY)",
    )
    return parser.parse_args()


def load_data_config() -> dict:
    path = CONFIG_DIR / "data.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def output_filename(interval: str) -> str:
    return f"yfinance_ohlcv_{interval}.parquet"


def _session_index_utc(index: pd.Index) -> pd.DatetimeIndex:
    idx = pd.to_datetime(index)
    if idx.tz is None:
        idx = idx.tz_localize("America/New_York", ambiguous="infer", nonexistent="shift_forward")
    return idx.tz_convert("UTC")


def fetch_symbol(symbol: str, interval: str) -> pd.DataFrame:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="max", interval=interval, auto_adjust=True)
    if hist is None or hist.empty:
        raise ValueError(f"yfinance returned no history for {symbol} interval={interval}")
    hist = hist.rename(columns={c: str(c).lower() for c in hist.columns})
    hist.index = _session_index_utc(hist.index)
    hist = hist.sort_index()
    out = pd.DataFrame(
        {
            "open_time": hist.index,
            "asset": symbol.upper(),
            "open": pd.to_numeric(hist["open"], errors="coerce"),
            "high": pd.to_numeric(hist["high"], errors="coerce"),
            "low": pd.to_numeric(hist["low"], errors="coerce"),
            "close": pd.to_numeric(hist["close"], errors="coerce"),
            "volume": pd.to_numeric(hist.get("volume", 0.0), errors="coerce"),
        }
    )
    out["close_time"] = (
        out["open_time"].dt.tz_convert("America/New_York").dt.normalize()
        + pd.Timedelta(hours=16)
    ).dt.tz_convert("UTC")
    out["quote_asset_volume"] = out["close"] * out["volume"]
    return out.dropna(subset=["open", "high", "low", "close"]).drop_duplicates(subset=["open_time"])


def refresh(symbols: list[str], interval: str) -> pd.DataFrame:
    frames = []
    for symbol in symbols:
        print(f"yfinance {interval} {symbol}")
        frames.append(fetch_symbol(symbol, interval))
    if not frames:
        raise ValueError("No yfinance symbols refreshed")
    combined = pd.concat(frames, ignore_index=True).sort_values(["asset", "open_time"])
    path = DATA_DIR / output_filename(interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    print(f"Wrote {len(combined)} rows to {path}")
    return combined


def main() -> None:
    args = parse_args()
    cfg = load_data_config().get("yfinance_ohlcv") or {}
    symbols = args.symbols if args.symbols else list(cfg.get("symbols") or DEFAULT_SYMBOLS)
    refresh([s.upper() for s in symbols], args.interval)


if __name__ == "__main__":
    main()
