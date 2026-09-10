# src/fetch_stock_data.py
# Handles HTTP requests to the Alpha Vantage TIME_SERIES_DAILY endpoint.
# Imports from: requests, src.exceptions.

"""
Alpha Vantage API client for fetching daily stock price data.

Owns: HTTP request construction, HTTP-error handling, API-level response
validation (Error Message, Information, missing Time Series key).
Must never contain: Airflow-specific code, database code, SQL.
"""

import logging

import requests

from src.exceptions import (
    EmptyPayloadError,
    InvalidApiKeyError,
    MalformedResponseError,
    RateLimitError,
    TransientApiError,
)

logger = logging.getLogger(__name__)

ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
TIME_SERIES_KEY = "Time Series (Daily)"

# Timeout: 5s connect, 30s read — no request hangs indefinitely
DEFAULT_TIMEOUT = (5, 30)


def fetch_daily_data(symbol: str, api_key: str) -> dict:
    """Fetch TIME_SERIES_DAILY data for a single symbol.

    Inputs from caller:
        symbol: stock ticker (e.g. 'AAPL')
        api_key: Alpha Vantage API key (never logged)

    Outputs:
        dict containing the raw 'Time Series (Daily)' data from the API.

    Raises:
        TransientApiError: on timeout, connection error, or HTTP 5xx (retryable)
        RateLimitError: on HTTP 429 (retryable with backoff)
        InvalidApiKeyError: on API error indicating bad credentials (fail-fast)
        MalformedResponseError: on non-JSON response or unexpected structure (fail-fast)
        EmptyPayloadError: when 'Time Series (Daily)' key is missing (fail-fast)
    """
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": "compact",
        "datatype": "json",
        "apikey": api_key,
    }

    # --- HTTP layer ---
    try:
        response = requests.get(
            ALPHA_VANTAGE_BASE_URL,
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.exceptions.Timeout as exc:
        logger.error("Timeout fetching data for symbol=%s", symbol)
        raise TransientApiError(
            f"Request to Alpha Vantage timed out for symbol '{symbol}'."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        logger.error("Connection error fetching data for symbol=%s", symbol)
        raise TransientApiError(
            f"Connection error reaching Alpha Vantage for symbol '{symbol}'."
        ) from exc
    except requests.exceptions.RequestException as exc:
        logger.error("Unexpected request error for symbol=%s: %s", symbol, type(exc).__name__)
        raise TransientApiError(
            f"Unexpected request error for symbol '{symbol}': {type(exc).__name__}"
        ) from exc

    # --- HTTP status layer ---
    if response.status_code == 429:
        logger.warning("Rate limited (HTTP 429) for symbol=%s", symbol)
        raise RateLimitError(
            f"Rate limited by Alpha Vantage for symbol '{symbol}'. Retry after delay."
        )

    if response.status_code >= 500:
        logger.error("Server error (HTTP %d) for symbol=%s", response.status_code, symbol)
        raise TransientApiError(
            f"Alpha Vantage server error (HTTP {response.status_code}) for symbol '{symbol}'."
        )

    if response.status_code >= 400:
        logger.error("Client error (HTTP %d) for symbol=%s", response.status_code, symbol)
        raise InvalidApiKeyError(
            f"Alpha Vantage client error (HTTP {response.status_code}) for symbol '{symbol}'. "
            f"Check your API key and request parameters."
        )

    # --- JSON parsing layer ---
    try:
        data = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        logger.error(
            "Failed to parse JSON response for symbol=%s, status=%d",
            symbol,
            response.status_code,
        )
        raise MalformedResponseError(
            f"Response for symbol '{symbol}' is not valid JSON (HTTP {response.status_code})."
        ) from exc

    # --- Business-level validation layer ---
    # Alpha Vantage returns HTTP 200 even for errors — must inspect the body.

    if "Error Message" in data:
        logger.error("API error for symbol=%s: %s", symbol, data["Error Message"])
        raise InvalidApiKeyError(
            f"Alpha Vantage API error for symbol '{symbol}': {data['Error Message']}"
        )

    if "Information" in data:
        # "Information" typically indicates rate limiting or account issues
        logger.warning("API information notice for symbol=%s: %s", symbol, data["Information"])
        raise RateLimitError(
            f"Alpha Vantage rate limit / info notice for symbol '{symbol}': {data['Information']}"
        )

    if TIME_SERIES_KEY not in data:
        logger.error(
            "Missing '%s' key in response for symbol=%s. Keys present: %s",
            TIME_SERIES_KEY,
            symbol,
            list(data.keys()),
        )
        raise EmptyPayloadError(
            f"Response for symbol '{symbol}' is missing the '{TIME_SERIES_KEY}' key. "
            f"The data contract is not satisfied."
        )

    time_series = data[TIME_SERIES_KEY]
    if not time_series:
        raise EmptyPayloadError(
            f"Response for symbol '{symbol}' has an empty '{TIME_SERIES_KEY}' section."
        )

    logger.info("Successfully fetched %d daily records for symbol=%s", len(time_series), symbol)
    return data
