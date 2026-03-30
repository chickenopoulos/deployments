from __future__ import annotations

import os
from typing import Iterable

import pandas as pd
import requests
from dotenv import load_dotenv
from tqdm import tqdm
import time
import random
import threading
from time import monotonic, sleep

from deployments.paths import DATA_DIR

BASE_URL = 'https://open-api-v4.coinglass.com'
PAIR_UNIVERSE_URL = f'{BASE_URL}/api/futures/supported-exchange-pairs?exchange=Binance'
ENDPOINTS = {
    'binance_futures_orderbook_pair_coinglass.parquet': '/api/futures/orderbook/ask-bids-history',
    'binance_futures_funding_rate_coinglass.parquet': '/api/futures/funding-rate/history',
    'binance_futures_funding_rate_oi_weight_coinglass.parquet': '/api/futures/funding-rate/oi-weight-history',
    'binance_futures_basis_coinglass.parquet': '/api/futures/basis/history',
}

SESSION = requests.Session()

COINGLASS_RPM = int(os.getenv("COINGLASS_RATE_LIMIT_PER_MIN", "25"))
# Keep a safety buffer below the published plan limit.
REQUEST_SPACING_SECONDS = 60.0 / max(COINGLASS_RPM, 1)
_rate_lock = threading.Lock()
_last_request_ts = 0.0


def _throttle() -> None:
    global _last_request_ts
    with _rate_lock:
        now = monotonic()
        wait = REQUEST_SPACING_SECONDS - (now - _last_request_ts)
        if wait > 0:
            sleep(wait)
        _last_request_ts = monotonic()

def _headers() -> dict:
    load_dotenv()
    api_key = os.getenv('COINGLASS_API_KEY')
    if not api_key:
        raise EnvironmentError('COINGLASS_API_KEY is required')
    return {'accept': 'application/json', 'CG-API-KEY': api_key}

def _get(url: str, params: dict, max_retries: int = 8) -> dict:
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            _throttle()
            resp = SESSION.get(url, headers=_headers(), params=params, timeout=30)

            # Case 1: transport-level 429
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    sleep_s = int(retry_after)
                else:
                    sleep_s = min(90, 2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(sleep_s)
                last_error = RuntimeError(
                    f"HTTP 429 rate limit for {url} params={params}"
                )
                continue

            resp.raise_for_status()
            payload = resp.json()

            if not isinstance(payload, dict):
                return payload

            code = str(payload.get("code", "0")).strip()
            msg = str(payload.get("msg", "")).lower()
            success = payload.get("success", True)

            # Case 2: payload-level 429 / rate-limit response
            is_rate_limited = (
                code == "429"
                or "too many requests" in msg
                or ("rate" in msg and "limit" in msg)
            )

            if is_rate_limited:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    sleep_s = int(retry_after)
                else:
                    sleep_s = min(90, 2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(sleep_s)
                last_error = RuntimeError(
                    f"Payload 429 rate limit for {url} params={params}: {payload}"
                )
                continue

            # Non-rate-limit API error: fail fast
            if code not in ("0", "", "None") or success is False:
                raise RuntimeError(
                    f"CoinGlass API error for {url} params={params}: {payload}"
                )

            return payload

        except requests.RequestException as e:
            last_error = e
            sleep_s = min(60, 2 ** attempt) + random.uniform(0, 0.5)
            time.sleep(sleep_s)

    raise last_error if last_error else RuntimeError(f"Request failed for {url}")

def load_binance_usdt_pairs() -> list[str]:
    payload = _get(PAIR_UNIVERSE_URL, {})
    frame = pd.DataFrame(payload.get('data', {}).get('Binance', []))
    if frame.empty:
        return []
    return sorted(frame.loc[frame['quote_asset'] == 'USDT', 'instrument_id'].dropna().unique().tolist())

def _normalize_rows(payload: dict, asset: str) -> pd.DataFrame:
    data = payload.get("data", payload)

    if data is None:
        return pd.DataFrame()

    # Common API shapes: list, dict with nested list, dict-of-lists, single row dict
    if isinstance(data, dict):
        for key in ("list", "rows", "items", "result"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break

    try:
        if isinstance(data, list):
            frame = pd.DataFrame(data)
        elif isinstance(data, dict):
            # dict-of-lists vs single-row dict
            try:
                frame = pd.DataFrame(data)
            except Exception:
                frame = pd.DataFrame([data])
        else:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    if frame.empty:
        return frame

    # Normalize likely time column names
    time_cols_ms = ["timestamp", "time", "ts", "t", "openTime", "closeTime"]
    time_cols_str = ["date", "datetime"]

    if "datetime" not in frame.columns:
        for col in time_cols_ms:
            if col in frame.columns:
                frame["datetime"] = pd.to_datetime(frame[col], unit="ms", utc=True, errors="coerce")
                break

    if "datetime" not in frame.columns:
        for col in time_cols_str:
            if col in frame.columns:
                frame["datetime"] = pd.to_datetime(frame[col], utc=True, errors="coerce")
                break

    if "datetime" in frame.columns:
        frame = frame[frame["datetime"].notna()].copy()

    if frame.empty:
        return frame

    frame["asset"] = asset
    return frame

def _coerce_frame_types(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame

    if 'datetime' in frame.columns:
        frame['datetime'] = pd.to_datetime(frame['datetime'], utc=True, errors='coerce')

    text_cols = {
        'asset', 'symbol', 'baseAsset', 'quoteAsset', 'exchange',
        'market', 'pair', 'instrument_id', 'datetime'
    }

    for col in frame.columns:
        if col in text_cols:
            continue
        frame[col] = pd.to_numeric(frame[col], errors='coerce')

    if 'asset' in frame.columns:
        frame['asset'] = frame['asset'].astype(str)

    if 'datetime' in frame.columns:
        frame = frame[frame['datetime'].notna()].copy()

    return frame

def _fetch_with_retries(
    endpoint: str,
    params: dict,
    *,
    max_attempts: int = 8):
    return _get(f"{BASE_URL}{endpoint}", params, max_retries=max_attempts)

def _page_params_for_asset(asset: str, endpoint: str, interval: str, limit: int) -> dict:
    params = {
        "symbol": asset,
        "exchange": "Binance",
        "interval": interval,
        "limit": limit,
    }

    if "oi-weight" in endpoint:
        params = {
            "symbol": asset.replace("USDT", ""),
            "interval": interval,
            "limit": limit,
        }

    return params

def _oldest_timestamp_ms(frame: pd.DataFrame) -> int | None:
    """
    Return the oldest timestamp in ms from a normalized/coerced frame.
    Assumes either:
    - a raw integer timestamp column like 'time' / 'timestamp'
    - or a parsed datetime column named 'datetime'
    """
    for col in ("time", "timestamp", "ts"):
        if col in frame.columns and not frame[col].dropna().empty:
            val = frame[col].min()
            try:
                return int(val)
            except Exception:
                pass

    if "datetime" in frame.columns and not frame["datetime"].dropna().empty:
        ts = pd.to_datetime(frame["datetime"], utc=True).min()
        return int(ts.timestamp() * 1000)

    return None

def _add_pagination_cursor(params: dict, cursor_ms: int) -> dict:
    """
    Coinglass history endpoints typically page backwards in time.
    Depending on the endpoint, one of these may be honored:
    - endTime
    - to
    - before
    - end_time

    Keep the first one that your endpoint actually supports.
    """
    out = dict(params)

    # Use the parameter your specific endpoint expects.
    # For most Coinglass historical endpoints, `endTime` is the most likely.
    out["endTime"] = cursor_ms
    return out

def refresh_endpoint(
    filename: str,
    endpoint: str,
    assets: Iterable[str],
    interval: str = "1d",
    limit: int = 1000,
    max_attempts: int = 3,) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for asset in tqdm(assets):

        try:

            asset_frames: list[pd.DataFrame] = []
            seen_cursors: set[int] = set()

            base_params = _page_params_for_asset(asset, endpoint, interval, limit)
            page_params = dict(base_params)

            while True:
                payload = _fetch_with_retries(
                    endpoint,
                    page_params,
                    max_attempts=max_attempts,
                )

                frame = _normalize_rows(payload, asset)
                frame = _coerce_frame_types(frame)

                if not frame.empty and "datetime" not in frame.columns:
                    raise ValueError(
                        f"{filename} returned rows but no datetime column for asset={asset}. "
                        f"Columns={list(frame.columns)} "
                        f"payload_keys={list(payload.keys()) if isinstance(payload, dict) else type(payload)}"
                    )

                if frame.empty:
                    break

                asset_frames.append(frame)

                # If the endpoint returned fewer than `limit`, we're done paginating.
                if len(frame) < limit:
                    break

                oldest_ts = _oldest_timestamp_ms(frame)
                if oldest_ts is None:
                    raise ValueError(
                        f"Could not determine pagination cursor for asset={asset}. "
                        f"Columns={list(frame.columns)}"
                    )

                # Prevent infinite loops if the API keeps returning the same oldest page.
                next_cursor = oldest_ts - 1
                if next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)

                page_params = _add_pagination_cursor(base_params, next_cursor)

            if asset_frames:
                asset_out = pd.concat(asset_frames, ignore_index=True)
                asset_out = _coerce_frame_types(asset_out)

                # Drop duplicates across overlapping pages.
                dedupe_cols = [c for c in ("asset", "datetime") if c in asset_out.columns]
                if dedupe_cols:
                    asset_out = asset_out.drop_duplicates(subset=dedupe_cols).sort_values(
                        dedupe_cols
                    )

                frames.append(asset_out)
    
        except Exception as e:
            print(f"[WARN] Skipping asset={asset}: {e}")
            continue

    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out = _coerce_frame_types(out)
    out.to_parquet(DATA_DIR / filename)
    return out

def main() -> None:
    assets = load_binance_usdt_pairs()
    for filename, endpoint in ENDPOINTS.items():
        print('Fetching data for endpoint:', endpoint)
        refresh_endpoint(filename, endpoint, assets)

if __name__ == '__main__':
    main()


