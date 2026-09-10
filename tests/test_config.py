# tests/test_config.py
# Unit tests for src/config.py — validates config loading and validation.

"""
Tests for the configuration module.

Covers:
- Missing required env var raises ConfigurationError immediately
- Valid env vars produce correct Config object
- Port validation (non-integer, out of range)
- Symbol parsing (comma-separated, whitespace handling)
- Config singleton reset for test isolation
"""

import os
from unittest.mock import patch

import pytest

from src.config import ConfigurationError, get_config, reset_config

# Minimal valid environment for all required vars
VALID_ENV = {
    "ALPHA_VANTAGE_API_KEY": "test_key",
    "STOCK_SYMBOLS": "AAPL,MSFT",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "stocks",
    "POSTGRES_USER": "stock_user",
    "POSTGRES_PASSWORD": "test_password",
}


class TestConfigValidEnv:
    """Test Config with all required vars present."""

    @patch.dict(os.environ, VALID_ENV, clear=True)
    def test_valid_config_loads(self):
        """All required env vars present → Config loads without error."""
        reset_config()
        config = get_config()
        assert config.api_key == "test_key"
        assert config.stock_symbols == ["AAPL", "MSFT"]
        assert config.db_host == "localhost"
        assert config.db_port == 5432
        assert config.db_name == "stocks"
        assert config.db_user == "stock_user"
        assert config.db_password == "test_password"

    @patch.dict(os.environ, VALID_ENV, clear=True)
    def test_get_db_connection_params(self):
        """get_db_connection_params returns the correct dict."""
        reset_config()
        config = get_config()
        params = config.get_db_connection_params()
        assert params == {
            "host": "localhost",
            "port": 5432,
            "dbname": "stocks",
            "user": "stock_user",
            "password": "test_password",
        }


class TestConfigMissingVars:
    """Test Config with missing required vars."""

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key_raises(self):
        """Missing ALPHA_VANTAGE_API_KEY raises ConfigurationError immediately."""
        reset_config()
        with pytest.raises(ConfigurationError, match="ALPHA_VANTAGE_API_KEY"):
            get_config()

    @patch.dict(os.environ, {**VALID_ENV, "POSTGRES_HOST": ""}, clear=True)
    def test_empty_var_raises(self):
        """An empty required var raises ConfigurationError."""
        reset_config()
        with pytest.raises(ConfigurationError, match="POSTGRES_HOST"):
            get_config()


class TestConfigPortValidation:
    """Test port number validation."""

    @patch.dict(os.environ, {**VALID_ENV, "POSTGRES_PORT": "abc"}, clear=True)
    def test_non_integer_port_raises(self):
        """A non-integer port raises ConfigurationError."""
        reset_config()
        with pytest.raises(ConfigurationError, match="valid integer"):
            get_config()

    @patch.dict(os.environ, {**VALID_ENV, "POSTGRES_PORT": "99999"}, clear=True)
    def test_out_of_range_port_raises(self):
        """A port > 65535 raises ConfigurationError."""
        reset_config()
        with pytest.raises(ConfigurationError, match="between 1 and 65535"):
            get_config()


class TestConfigSymbolParsing:
    """Test STOCK_SYMBOLS parsing."""

    @patch.dict(os.environ, {**VALID_ENV, "STOCK_SYMBOLS": " aapl , msft , googl "}, clear=True)
    def test_symbols_trimmed_and_uppercased(self):
        """Symbols are stripped and uppercased."""
        reset_config()
        config = get_config()
        assert config.stock_symbols == ["AAPL", "MSFT", "GOOGL"]

    @patch.dict(os.environ, {**VALID_ENV, "STOCK_SYMBOLS": "AAPL"}, clear=True)
    def test_single_symbol(self):
        """A single symbol without commas works."""
        reset_config()
        config = get_config()
        assert config.stock_symbols == ["AAPL"]

    @patch.dict(os.environ, {**VALID_ENV, "STOCK_SYMBOLS": ",,,"}, clear=True)
    def test_empty_symbols_after_parsing_raises(self):
        """Comma-only string has no valid symbols → raises."""
        reset_config()
        with pytest.raises(ConfigurationError, match="no valid symbols"):
            get_config()


class TestConfigSecrets:
    """Verify secrets are never leaked in logs during config loading."""

    @patch.dict(os.environ, VALID_ENV, clear=True)
    def test_secrets_not_logged_at_startup(self, caplog):
        """API key and DB password must never appear in log output during config init."""
        reset_config()
        config = get_config()
        assert config.api_key not in caplog.text
        assert config.db_password not in caplog.text
