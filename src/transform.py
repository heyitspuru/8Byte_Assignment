# src/transform.py
# Parses and validates raw Alpha Vantage JSON into typed records.
# Imports from: datetime, decimal, logging, src.exceptions.

"""
Transform layer for the stock market data pipeline.

Owns: JSON → typed record parsing and validation. Converts string prices
to Decimal, volumes to int, dates to date objects. Skips individual
malformed records with a warning. Raises if the whole series is empty/invalid.
Must never contain: database connection management, HTTP code.
"""

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from src.exceptions import DataValidationError, EmptyPayloadError

logger = logging.getLogger(__name__)

TIME_SERIES_KEY = "Time Series (Daily)"

# Alpha Vantage field mapping
FIELD_MAP = {
    "1. open": "open_price",
    "2. high": "high_price",
    "3. low": "low_price",
    "4. close": "close_price",
    "5. volume": "volume",
}


def _parse_date(date_str: str) -> date:
    """Parse a date string in YYYY-MM-DD format.

    Inputs: date string from API response.
    Outputs: date object.
    Raises DataValidationError on invalid format.
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError) as exc:
        raise DataValidationError(
            f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD."
        ) from exc


def _parse_price(value: str, field_name: str) -> Decimal | None:
    """Parse a price string to Decimal.

    Inputs: raw price string and field name for error context.
    Outputs: Decimal value, or None if the value is missing/empty.
    Raises DataValidationError on unparseable non-empty values.
    Never fabricates a zero or any substitute value for missing data.
    """
    if value is None or str(value).strip() == "":
        return None
    try:
        result = Decimal(str(value).strip())
        return result
    except InvalidOperation as exc:
        raise DataValidationError(f"Cannot parse {field_name} value '{value}' as Decimal.") from exc


def _parse_volume(value: str) -> int | None:
    """Parse a volume string to int.

    Inputs: raw volume string.
    Outputs: integer value, or None if missing/empty.
    Raises DataValidationError on unparseable non-empty values.
    """
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError) as exc:
        raise DataValidationError(f"Cannot parse volume value '{value}' as integer.") from exc


def transform_daily_data(symbol: str, raw_data: dict) -> list[dict]:
    """Transform raw API response into a list of validated records.

    Inputs from caller:
        symbol: stock ticker symbol (e.g. 'AAPL')
        raw_data: full API response dict containing 'Time Series (Daily)'

    Outputs:
        list of dicts, each with keys:
            symbol (str), trade_date (date),
            open_price (Decimal|None), high_price (Decimal|None),
            low_price (Decimal|None), close_price (Decimal|None),
            volume (int|None)

    Raises:
        EmptyPayloadError: if no valid records remain after filtering.
    """
    time_series = raw_data.get(TIME_SERIES_KEY, {})
    if not time_series:
        raise EmptyPayloadError(f"No time series data found for symbol '{symbol}'.")

    records: list[dict] = []
    skipped_count = 0

    for date_str, daily_values in time_series.items():
        try:
            trade_date = _parse_date(date_str)

            record = {
                "symbol": symbol.upper(),
                "trade_date": trade_date,
            }

            # Parse each price/volume field — skip the whole record if any
            # required parsing fails (per error taxonomy: skip & log, don't abort)
            for api_key, db_field in FIELD_MAP.items():
                raw_value = daily_values.get(api_key)
                if db_field == "volume":
                    record[db_field] = _parse_volume(raw_value)
                else:
                    record[db_field] = _parse_price(raw_value, db_field)

            records.append(record)

        except DataValidationError as exc:
            skipped_count += 1
            logger.warning(
                "Skipping record for symbol=%s, date=%s: %s",
                symbol,
                date_str,
                exc,
            )
            continue

    if skipped_count > 0:
        logger.info(
            "Skipped %d malformed records for symbol=%s, kept %d valid records.",
            skipped_count,
            symbol,
            len(records),
        )

    if not records:
        raise EmptyPayloadError(
            f"All records for symbol '{symbol}' were malformed. "
            f"Skipped {skipped_count} records, 0 valid records remain."
        )

    logger.info(
        "Transformed %d valid records for symbol=%s.",
        len(records),
        symbol,
    )
    return records
