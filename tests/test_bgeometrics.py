from __future__ import annotations

import pytest

from deployments.scrappers.bgeometrics import series_from_payload


ROWS = [
    {"d": "2026-09-08", "unixTs": 1757289600, "mvrv": 1.49},
    {"d": "2026-09-09", "unixTs": 1757376000, "mvrv": 1.48},
]


def test_parses_canonical_d_column():
    series = series_from_payload(ROWS, "mvrv", "mvrv")
    assert float(series.loc["2026-09-09"]) == pytest.approx(1.49)
    assert series.index.tz is not None


def test_unwraps_data_envelope():
    series = series_from_payload({"data": ROWS}, "mvrv", "mvrv")
    assert float(series.dropna().iloc[-1]) == pytest.approx(1.48)


def test_empty_list_is_a_clear_error():
    with pytest.raises(ValueError, match="empty/non-list"):
        series_from_payload([], "mvrv", "mvrv")


def test_missing_date_column_is_a_clear_error():
    with pytest.raises(ValueError, match="missing required columns"):
        series_from_payload([{"unixTs": 1, "mvrv": 1.0}], "mvrv", "mvrv")
