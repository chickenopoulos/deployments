from __future__ import annotations

import os
import time
from typing import Any

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

from deployments.paths import DATA_DIR, ROOT

BASE_URL = "https://bitcoin-data.com/v1"
DATE_COLUMNS = ("d", "date")
RECORD_KEYS = ("data", "values", "result", "rows")
MAX_ATTEMPTS = 5


def _load_token() -> str:
    load_dotenv(ROOT / ".env")
    token = os.getenv("BITCOIN_DATA_API_TOKEN")
    if not token:
        raise EnvironmentError("BITCOIN_DATA_API_TOKEN is required")
    return token


def _records_from_payload(payload: Any, endpoint: str) -> list:
    if isinstance(payload, dict):
        for key in RECORD_KEYS:
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            keys = sorted(str(k) for k in payload.keys())
            raise ValueError(f"bitcoin-data {endpoint} returned object keys={keys}")
    if not isinstance(payload, list) or not payload:
        kind = type(payload).__name__
        n = len(payload) if isinstance(payload, list) else "n/a"
        raise ValueError(
            f"bitcoin-data {endpoint} returned empty/non-list payload type={kind} n={n}"
        )
    return payload


def series_from_payload(payload: Any, endpoint: str, value_column: str) -> pd.Series:
    records = _records_from_payload(payload, endpoint)
    frame = pd.DataFrame(records)
    date_col = next((column for column in DATE_COLUMNS if column in frame.columns), None)
    if date_col is None or value_column not in frame.columns:
        raise ValueError(
            f"bitcoin-data {endpoint} missing required columns "
            f"(need date in {DATE_COLUMNS} and {value_column}; got {list(frame.columns)})"
        )
    frame[date_col] = pd.to_datetime(frame[date_col], utc=True)
    frame = frame.set_index(date_col).sort_index()
    frame.index.name = "date"
    drop_cols = [column for column in ("unixTs", "d") if column in frame.columns]
    if drop_cols:
        frame = frame.drop(columns=drop_cols)
    for _ in range(2):
        next_date = frame.index[-1] + pd.Timedelta(days=1)
        frame.loc[next_date] = [np.nan for _ in range(frame.shape[1])]
        frame = frame.sort_index()
    frame = frame.shift()
    if value_column not in frame.columns:
        raise ValueError(f"bitcoin-data {endpoint} lost value column {value_column}")
    return frame[value_column].astype(float).copy()


def _get_metric(endpoint: str, value_column: str) -> pd.Series:
    token = _load_token()
    url = f"{BASE_URL}/{endpoint}"
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            try:
                response = requests.get(url, params={"token": token}, timeout=30)
            except requests.RequestException as exc:
                raise RuntimeError(
                    f"bitcoin-data {endpoint} request failed: {type(exc).__name__}"
                ) from exc
            if response.status_code >= 400:
                raise ValueError(f"bitcoin-data {endpoint} HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise ValueError(f"bitcoin-data {endpoint} returned non-JSON") from exc
            return series_from_payload(payload, endpoint, value_column)
        except (RuntimeError, ValueError) as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS:
                break
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(
        f"bitcoin-data {endpoint} failed after {MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error


def get_mvrv() -> pd.Series:
    return _get_metric("mvrv", "mvrv")


def get_sth_nupl() -> pd.Series:
    return _get_metric("nupl-sth", "nuplSth")


def main() -> None:
    output = pd.concat([get_mvrv(), get_sth_nupl()], axis=1)
    output.to_parquet(DATA_DIR / "bgeometrics_data.parquet")


if __name__ == "__main__":
    main()
