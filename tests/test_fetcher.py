# tests/test_fetcher.py
# Unit tests for src/fetch_stock_data.py — all HTTP mocked, no live API calls.

"""
Tests for the Alpha Vantage API client.

Covers every row in the error taxonomy relevant to the fetch layer:
- Successful fetch (200 with valid data)
- HTTP 429 (rate limit) → RateLimitError
- HTTP 500 (server error) → TransientApiError
- Timeout → TransientApiError
- Connection error → TransientApiError
- Malformed JSON → MalformedResponseError
- API error in body ("Error Message") → InvalidApiKeyError
- Rate limit in body ("Information") → RateLimitError
- Missing Time Series key → EmptyPayloadError
- Empty Time Series → EmptyPayloadError
- Secrets never leak into exception messages
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.exceptions import (
    EmptyPayloadError,
    InvalidApiKeyError,
    MalformedResponseError,
    RateLimitError,
    TransientApiError,
)
from src.fetch_stock_data import fetch_daily_data

FAKE_API_KEY = "TEST_KEY_NEVER_REAL"
SYMBOL = "AAPL"


def _make_mock_response(status_code: int, json_data: dict | None = None, ok: bool = True):
    """Helper to create a mock requests.Response."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = status_code
    mock_resp.ok = ok
    if json_data is not None:
        mock_resp.json.return_value = json_data
    else:
        mock_resp.json.side_effect = ValueError("No JSON")
    return mock_resp


VALID_RESPONSE = {
    "Meta Data": {
        "1. Information": "Daily Prices",
        "2. Symbol": "AAPL",
    },
    "Time Series (Daily)": {
        "2026-09-10": {
            "1. open": "150.0000",
            "2. high": "152.0000",
            "3. low": "149.0000",
            "4. close": "151.5000",
            "5. volume": "12345678",
        }
    },
}


class TestFetchDailyDataSuccess:
    """Test successful API responses."""

    @patch("src.fetch_stock_data.requests.get")
    def test_successful_fetch_returns_data(self, mock_get):
        """A valid 200 response with Time Series data returns the full dict."""
        mock_get.return_value = _make_mock_response(200, VALID_RESPONSE)

        result = fetch_daily_data(SYMBOL, FAKE_API_KEY)

        assert "Time Series (Daily)" in result
        assert "2026-09-10" in result["Time Series (Daily)"]
        mock_get.assert_called_once()

    @patch("src.fetch_stock_data.requests.get")
    def test_request_uses_correct_params(self, mock_get):
        """The request includes the correct query parameters."""
        mock_get.return_value = _make_mock_response(200, VALID_RESPONSE)

        fetch_daily_data(SYMBOL, FAKE_API_KEY)

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["function"] == "TIME_SERIES_DAILY"
        assert params["symbol"] == SYMBOL
        assert params["apikey"] == FAKE_API_KEY
        assert params["outputsize"] == "compact"

    @patch("src.fetch_stock_data.requests.get")
    def test_request_has_timeout(self, mock_get):
        """Every request must have an explicit timeout — never hang indefinitely."""
        mock_get.return_value = _make_mock_response(200, VALID_RESPONSE)

        fetch_daily_data(SYMBOL, FAKE_API_KEY)

        call_kwargs = mock_get.call_args
        timeout = call_kwargs.kwargs.get("timeout") or call_kwargs[1].get("timeout")
        assert timeout is not None


class TestFetchDailyDataTransientErrors:
    """Test retryable (transient) error handling."""

    @patch("src.fetch_stock_data.requests.get")
    def test_timeout_raises_transient_error(self, mock_get):
        """A request timeout should raise TransientApiError (retryable)."""
        mock_get.side_effect = requests.exceptions.Timeout("timed out")

        with pytest.raises(TransientApiError, match="timed out"):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

    @patch("src.fetch_stock_data.requests.get")
    def test_connection_error_raises_transient_error(self, mock_get):
        """A connection error should raise TransientApiError (retryable)."""
        mock_get.side_effect = requests.exceptions.ConnectionError("connection refused")

        with pytest.raises(TransientApiError, match="Connection error"):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

    @patch("src.fetch_stock_data.requests.get")
    def test_http_500_raises_transient_error(self, mock_get):
        """HTTP 500 should raise TransientApiError (retryable)."""
        mock_get.return_value = _make_mock_response(500, ok=False)

        with pytest.raises(TransientApiError, match="500"):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

    @patch("src.fetch_stock_data.requests.get")
    def test_http_502_raises_transient_error(self, mock_get):
        """HTTP 502 should raise TransientApiError (retryable)."""
        mock_get.return_value = _make_mock_response(502, ok=False)

        with pytest.raises(TransientApiError, match="502"):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

    @patch("src.fetch_stock_data.requests.get")
    def test_http_429_raises_rate_limit_error(self, mock_get):
        """HTTP 429 should raise RateLimitError (retryable with backoff)."""
        mock_get.return_value = _make_mock_response(429, ok=False)

        with pytest.raises(RateLimitError, match="Rate limited"):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)


class TestFetchDailyDataFailFast:
    """Test non-retryable error handling."""

    @patch("src.fetch_stock_data.requests.get")
    def test_http_400_raises_invalid_api_key(self, mock_get):
        """HTTP 4xx (non-429) should raise InvalidApiKeyError (fail-fast)."""
        mock_get.return_value = _make_mock_response(400, ok=False)

        with pytest.raises(InvalidApiKeyError):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

    @patch("src.fetch_stock_data.requests.get")
    def test_malformed_json_raises_error(self, mock_get):
        """A non-JSON response should raise MalformedResponseError (fail-fast)."""
        mock_get.return_value = _make_mock_response(200, json_data=None)

        with pytest.raises(MalformedResponseError, match="not valid JSON"):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

    @patch("src.fetch_stock_data.requests.get")
    def test_api_error_message_raises_invalid_key(self, mock_get):
        """An 'Error Message' in the body should raise InvalidApiKeyError."""
        mock_get.return_value = _make_mock_response(200, {"Error Message": "Invalid API call"})

        with pytest.raises(InvalidApiKeyError, match="Invalid API call"):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

    @patch("src.fetch_stock_data.requests.get")
    def test_information_notice_raises_rate_limit(self, mock_get):
        """An 'Information' key in the body indicates rate limiting."""
        mock_get.return_value = _make_mock_response(
            200,
            {"Information": "Thank you for using Alpha Vantage! Please visit..."},
        )

        with pytest.raises(RateLimitError, match="rate limit"):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

    @patch("src.fetch_stock_data.requests.get")
    def test_missing_time_series_key_raises_empty_payload(self, mock_get):
        """Response without 'Time Series (Daily)' should raise EmptyPayloadError."""
        mock_get.return_value = _make_mock_response(
            200, {"Meta Data": {"1. Information": "Daily Prices"}}
        )

        with pytest.raises(EmptyPayloadError, match="missing"):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

    @patch("src.fetch_stock_data.requests.get")
    def test_empty_time_series_raises_empty_payload(self, mock_get):
        """An empty 'Time Series (Daily)' dict should raise EmptyPayloadError."""
        mock_get.return_value = _make_mock_response(
            200,
            {"Meta Data": {}, "Time Series (Daily)": {}},
        )

        with pytest.raises(EmptyPayloadError, match="empty"):
            fetch_daily_data(SYMBOL, FAKE_API_KEY)


class TestFetchDailyDataSecrets:
    """Verify that API keys never leak into exception messages or logs."""

    @patch("src.fetch_stock_data.requests.get")
    def test_api_key_not_in_timeout_exception_or_logs(self, mock_get, caplog):
        """API key must not appear in TransientApiError messages or captured logs."""
        mock_get.side_effect = requests.exceptions.Timeout("timed out")

        with pytest.raises(TransientApiError) as exc_info:
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

        assert FAKE_API_KEY not in str(exc_info.value)
        assert FAKE_API_KEY not in caplog.text

    @patch("src.fetch_stock_data.requests.get")
    def test_api_key_not_in_invalid_key_exception_or_logs(self, mock_get, caplog):
        """API key must not appear in InvalidApiKeyError messages or captured logs."""
        mock_get.return_value = _make_mock_response(200, {"Error Message": "Invalid API call"})

        with pytest.raises(InvalidApiKeyError) as exc_info:
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

        assert FAKE_API_KEY not in str(exc_info.value)
        assert FAKE_API_KEY not in caplog.text

    @patch("src.fetch_stock_data.requests.get")
    def test_api_key_not_in_rate_limit_exception_or_logs(self, mock_get, caplog):
        """API key must not appear in RateLimitError messages or captured logs."""
        mock_get.return_value = _make_mock_response(429)

        with pytest.raises(RateLimitError) as exc_info:
            fetch_daily_data(SYMBOL, FAKE_API_KEY)

        assert FAKE_API_KEY not in str(exc_info.value)
        assert FAKE_API_KEY not in caplog.text

    @patch("src.fetch_stock_data.requests.get")
    def test_api_key_not_in_success_logs(self, mock_get, caplog):
        """API key must never appear in log output even on successful fetches."""
        mock_get.return_value = _make_mock_response(200, VALID_RESPONSE)

        fetch_daily_data(SYMBOL, FAKE_API_KEY)

        assert FAKE_API_KEY not in caplog.text
