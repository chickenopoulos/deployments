"""Yahoo Finance daily OHLCV for cash equities/ETFs/futures proxies (temporary until IBKR)."""

from __future__ import annotations

import argparse
import time

import pandas as pd
import yaml

from deployments.paths import CONFIG_DIR, DATA_DIR
from deployments.utils.mulvaney_universe import (
    YAHOO_TICKERS,
    bar_close_utc,
    canonical_yahoo,
    session_for_yahoo,
    yahoo_symbol_is_stale,
)

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
    parser.add_argument(
        "--universe",
        choices=("default", "mulvaney", "g7_fx", "all"),
        default="default",
        help="default=ETF list; mulvaney=CTA proxies; g7_fx=Yahoo FX majors; all=union",
    )
    parser.add_argument(
        "--period",
        default="max",
        help="yfinance history period (default max; path-dependent CTA needs full history)",
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


def _session_index_utc(index: pd.Index, yahoo_symbol: str) -> pd.DatetimeIndex:
    idx = pd.to_datetime(index)
    tz, _hhmm = session_for_yahoo(yahoo_symbol)
    if idx.tz is None:
        idx = idx.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward")
    return idx.tz_convert("UTC")


def fetch_symbol(symbol: str, interval: str, period: str = "max") -> pd.DataFrame:
    import yfinance as yf

    yahoo = canonical_yahoo(symbol)
    ticker = yf.Ticker(yahoo)
    hist = ticker.history(period=period, interval=interval, auto_adjust=True)
    if hist is None or hist.empty:
        raise ValueError(f"yfinance returned no history for {yahoo} interval={interval}")
    hist = hist.rename(columns={c: str(c).lower() for c in hist.columns})
    hist.index = _session_index_utc(hist.index, yahoo)
    hist = hist.sort_index()
    out = pd.DataFrame(
        {
            "open_time": hist.index,
            "asset": yahoo,
            "open": pd.to_numeric(hist["open"], errors="coerce"),
            "high": pd.to_numeric(hist["high"], errors="coerce"),
            "low": pd.to_numeric(hist["low"], errors="coerce"),
            "close": pd.to_numeric(hist["close"], errors="coerce"),
            "volume": pd.to_numeric(hist.get("volume", 0.0), errors="coerce"),
        }
    )
    out["close_time"] = [bar_close_utc(ts, yahoo) for ts in out["open_time"]]
    out["quote_asset_volume"] = out["close"] * out["volume"]
    return out.dropna(subset=["open", "high", "low", "close"]).drop_duplicates(subset=["open_time"])


def merge_asset_frames(existing: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """Replace rows for assets present in `new`; keep other assets from `existing`."""
    if existing is None or existing.empty:
        combined = new
    else:
        assets = set(new["asset"].astype(str).unique())
        kept = existing[~existing["asset"].astype(str).isin(assets)]
        combined = pd.concat([kept, new], ignore_index=True)
    return combined.sort_values(["asset", "open_time"]).reset_index(drop=True)


def resolve_symbols(cfg: dict, universe: str, override: list[str] | None) -> list[str]:
    if override:
        return [canonical_yahoo(s) for s in override]
    default_syms = list(cfg.get("symbols") or DEFAULT_SYMBOLS)
    mulvaney_syms = list(cfg.get("mulvaney_symbols") or YAHOO_TICKERS)
    g7_syms = list(cfg.get("g7_fx_symbols") or [])
    if universe == "mulvaney":
        raw = mulvaney_syms
    elif universe == "g7_fx":
        raw = g7_syms
    elif universe == "all":
        raw = list(dict.fromkeys([*default_syms, *mulvaney_syms, *g7_syms]))
    else:
        raw = default_syms
    return [canonical_yahoo(s) for s in raw]


def _last_open_by_asset(df: pd.DataFrame) -> dict[str, pd.Timestamp]:
    if df is None or df.empty:
        return {}
    frame = df.copy()
    frame["asset"] = frame["asset"].astype(str).map(canonical_yahoo)
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    last = frame.sort_values("open_time").groupby("asset", as_index=False).tail(1)
    return {str(row["asset"]): pd.Timestamp(row["open_time"]) for _, row in last.iterrows()}


def stale_yahoo_symbols(
    df: pd.DataFrame,
    symbols: list[str],
    now: pd.Timestamp | None = None,
) -> list[str]:
    """Symbols whose last stored bar is behind the last completed venue session."""
    now_utc = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if now_utc.tzinfo is None:
        now_utc = now_utc.tz_localize("UTC")
    last_opens = _last_open_by_asset(df)
    stale: list[str] = []
    for symbol in symbols:
        yahoo = canonical_yahoo(symbol)
        last_open = last_opens.get(yahoo)
        if last_open is None or yahoo_symbol_is_stale(last_open, now_utc, yahoo):
            stale.append(yahoo)
    return stale


def _fetch_many(symbols: list[str], interval: str, period: str) -> tuple[list[pd.DataFrame], list[str]]:
    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    for i, symbol in enumerate(symbols):
        print(f"yfinance {interval} {symbol}")
        try:
            frames.append(fetch_symbol(symbol, interval, period=period))
        except Exception as exc:
            failed.append(symbol)
            print(f"WARN skip {symbol}: {exc}")
        if i + 1 < len(symbols):
            time.sleep(0.25)
    return frames, failed


def refresh(symbols: list[str], interval: str, period: str = "max") -> pd.DataFrame:
    path = DATA_DIR / output_filename(interval)
    existing = pd.read_parquet(path) if path.exists() else None
    pending = [canonical_yahoo(s) for s in symbols]
    frames, failed = _fetch_many(pending, interval, period)
    if frames:
        new = pd.concat(frames, ignore_index=True)
        existing = merge_asset_frames(existing, new)

    # Yahoo sometimes returns a truncated last bar (EXX5.DE, some FX=X names).
    # Retry names that are behind the last completed session before we persist.
    retry = stale_yahoo_symbols(existing if existing is not None else pd.DataFrame(), pending)
    retry = [s for s in retry if s not in failed]
    if retry:
        print(f"WARN stale after first pass, retrying: {retry}")
        time.sleep(0.5)
        extra, extra_failed = _fetch_many(retry, interval, period)
        failed.extend(extra_failed)
        if extra:
            existing = merge_asset_frames(existing, pd.concat(extra, ignore_index=True))

    if existing is None or existing.empty:
        raise ValueError(f"No yfinance symbols refreshed (failed={failed})")
    still_stale = stale_yahoo_symbols(existing, pending)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing.to_parquet(path, index=False)
    print(f"Wrote {len(existing)} rows ({existing['asset'].nunique()} assets) to {path}")
    if failed:
        print(f"WARN failed symbols: {failed}")
    if still_stale:
        print(f"WARN stale symbols after retry: {still_stale}")
    return existing


def main() -> None:
    args = parse_args()
    cfg = load_data_config().get("yfinance_ohlcv") or {}
    symbols = resolve_symbols(cfg, args.universe, args.symbols)
    refresh(symbols, args.interval, period=args.period)


if __name__ == "__main__":
    main()
