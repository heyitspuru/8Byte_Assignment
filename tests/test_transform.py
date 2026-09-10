# tests/test_transform.py
# Unit tests for src/transform.py — no network or DB calls.

"""
Tests for the data transformation layer.

Covers:
- Valid row normalizes correctly (Decimal prices, int volume, date objects)
- Missing field → record skipped with warning
- Bad date → record skipped
- Bad number → record skipped
- Empty series → EmptyPayloadError
- All-malformed series → EmptyPayloadError
- Mixed valid and invalid records → valid kept, invalid skipped
"""

from datetime import date
from decimal import Decimal

import pytest

from src.exceptions import EmptyPayloadError
from src.transform import transform_daily_data

SYMBOL = "AAPL"


def _make_raw_data(time_series: dict) -> dict:
    """Helper to wrap time series data in the expected API response structure."""
    return {
        "Meta Data": {"1. Information": "Daily Prices", "2. Symbol": SYMBOL},
        "Time Series (Daily)": time_series,
    }


VALID_DAY = {
    "1. open": "150.0000",
    "2. high": "152.0000",
    "3. low": "149.0000",
    "4. close": "151.5000",
    "5. volume": "12345678",
}


class TestTransformValidData:
    """Test transformation of valid records."""

    def test_valid_single_record(self):
        """A single valid record is correctly transformed."""
        raw = _make_raw_data({"2026-09-10": VALID_DAY})

        records = transform_daily_data(SYMBOL, raw)

        assert len(records) == 1
        rec = records[0]
        assert rec["symbol"] == "AAPL"
        assert rec["trade_date"] == date(2026, 9, 10)
        assert rec["open_price"] == Decimal("150.0000")
        assert rec["high_price"] == Decimal("152.0000")
        assert rec["low_price"] == Decimal("149.0000")
        assert rec["close_price"] == Decimal("151.5000")
        assert rec["volume"] == 12345678

    def test_multiple_valid_records(self):
        """Multiple valid records are all transformed."""
        raw = _make_raw_data(
            {
                "2026-09-10": VALID_DAY,
                "2026-09-09": {
                    "1. open": "148.0000",
                    "2. high": "150.5000",
                    "3. low": "147.5000",
                    "4. close": "149.2000",
                    "5. volume": "11223344",
                },
            }
        )

        records = transform_daily_data(SYMBOL, raw)

        assert len(records) == 2
        dates = {r["trade_date"] for r in records}
        assert date(2026, 9, 10) in dates
        assert date(2026, 9, 9) in dates

    def test_symbol_uppercased(self):
        """Symbol is always uppercased regardless of input."""
        raw = _make_raw_data({"2026-09-10": VALID_DAY})

        records = transform_daily_data("aapl", raw)

        assert records[0]["symbol"] == "AAPL"

    def test_prices_are_decimal_type(self):
        """All price fields must be Decimal, not float."""
        raw = _make_raw_data({"2026-09-10": VALID_DAY})

        records = transform_daily_data(SYMBOL, raw)

        rec = records[0]
        for field in ["open_price", "high_price", "low_price", "close_price"]:
            assert isinstance(rec[field], Decimal), f"{field} should be Decimal"


class TestTransformMissingFields:
    """Test handling of missing or empty field values."""

    def test_missing_volume_returns_none(self):
        """A missing volume field should result in None, not a fabricated value."""
        day = dict(VALID_DAY)
        del day["5. volume"]
        raw = _make_raw_data({"2026-09-10": day})

        records = transform_daily_data(SYMBOL, raw)

        assert len(records) == 1
        assert records[0]["volume"] is None

    def test_missing_price_returns_none(self):
        """A missing price field should result in None, not zero."""
        day = dict(VALID_DAY)
        del day["1. open"]
        raw = _make_raw_data({"2026-09-10": day})

        records = transform_daily_data(SYMBOL, raw)

        assert len(records) == 1
        assert records[0]["open_price"] is None


class TestTransformMalformedRecords:
    """Test that individual malformed records are skipped, not the whole batch."""

    def test_bad_date_skipped(self):
        """A record with an invalid date is skipped."""
        raw = _make_raw_data(
            {
                "not-a-date": VALID_DAY,
                "2026-09-10": VALID_DAY,
            }
        )

        records = transform_daily_data(SYMBOL, raw)

        assert len(records) == 1
        assert records[0]["trade_date"] == date(2026, 9, 10)

    def test_bad_price_skipped(self):
        """A record with an unparseable price is skipped."""
        bad_day = dict(VALID_DAY)
        bad_day["1. open"] = "not_a_number"
        raw = _make_raw_data(
            {
                "2026-09-08": bad_day,
                "2026-09-10": VALID_DAY,
            }
        )

        records = transform_daily_data(SYMBOL, raw)

        assert len(records) == 1
        assert records[0]["trade_date"] == date(2026, 9, 10)

    def test_bad_volume_skipped(self):
        """A record with an unparseable volume is skipped."""
        bad_day = dict(VALID_DAY)
        bad_day["5. volume"] = "abc"
        raw = _make_raw_data(
            {
                "2026-09-08": bad_day,
                "2026-09-10": VALID_DAY,
            }
        )

        records = transform_daily_data(SYMBOL, raw)

        assert len(records) == 1
        assert records[0]["trade_date"] == date(2026, 9, 10)


class TestTransformEmptyOrInvalid:
    """Test that empty or fully invalid payloads raise EmptyPayloadError."""

    def test_empty_time_series_raises(self):
        """An empty Time Series dict should raise EmptyPayloadError."""
        raw = _make_raw_data({})

        with pytest.raises(EmptyPayloadError, match="No time series data"):
            transform_daily_data(SYMBOL, raw)

    def test_missing_time_series_key_raises(self):
        """A response without 'Time Series (Daily)' should raise EmptyPayloadError."""
        raw = {"Meta Data": {"1. Information": "Daily Prices"}}

        with pytest.raises(EmptyPayloadError, match="No time series data"):
            transform_daily_data(SYMBOL, raw)

    def test_all_records_malformed_raises(self):
        """If every record is malformed, raise EmptyPayloadError."""
        raw = _make_raw_data(
            {
                "not-a-date-1": VALID_DAY,
                "not-a-date-2": VALID_DAY,
            }
        )

        with pytest.raises(EmptyPayloadError, match="All records.*malformed"):
            transform_daily_data(SYMBOL, raw)
