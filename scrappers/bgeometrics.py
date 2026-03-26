from __future__ import annotations

import os

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

from deployments.paths import DATA_DIR

BASE_URL = 'https://bitcoin-data.com/v1'


def _get_metric(endpoint: str, value_column: str) -> pd.Series:
    load_dotenv()
    token = os.getenv('BITCOIN_DATA_API_TOKEN')
    if not token:
        raise EnvironmentError('BITCOIN_DATA_API_TOKEN is required')
    url = f"{BASE_URL}/{endpoint}?token={token}"
    payload = requests.get(url, timeout=30)
    payload.raise_for_status()
    frame = pd.DataFrame(payload.json())
    frame['date'] = pd.to_datetime(frame['d'], utc=True)
    frame.set_index('date', inplace=True)
    frame.drop(columns=['unixTs', 'd'], inplace=True)
    frame.sort_index(inplace=True)
    for _ in range(2):
        next_date = frame.index[-1] + pd.Timedelta(days=1)
        frame.loc[next_date] = [np.nan for _ in range(frame.shape[1])]
        frame = frame.sort_index()
    frame = frame.shift()
    return frame[value_column].astype(float).copy()


def get_mvrv() -> pd.Series:
    return _get_metric('mvrv', 'mvrv')


def get_sth_nupl() -> pd.Series:
    return _get_metric('nupl-sth', 'nuplSth')


def main() -> None:
    output = pd.concat([get_mvrv(), get_sth_nupl()], axis=1)
    output.to_parquet(DATA_DIR / 'bgeometrics_data.parquet')


if __name__ == '__main__':
    main()
