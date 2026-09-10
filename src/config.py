# src/config.py
# Reads and validates all required environment variables at import time.
# Imports from: os, src.exceptions.

"""
Configuration loader for the stock market data pipeline.

Reads all required environment variables once at import time and fails fast
with a clear, non-secret error message if anything is missing or malformed.
Environment variables are read here and only here — no other module calls
os.getenv() directly.
"""

import os

from src.exceptions import PipelineError


class ConfigurationError(PipelineError):
    """Raised when a required environment variable is missing or invalid."""


def _require_env(name: str) -> str:
    """Read a required environment variable or raise immediately.

    Inputs: environment variable name.
    Outputs: the variable's value (string), or raises ConfigurationError.
    Never logs or includes the variable's value in error messages for secret vars.
    """
    value = os.environ.get(name)
    if not value or not value.strip():
        raise ConfigurationError(
            f"Required environment variable '{name}' is missing or empty. "
            f"Set it in your .env file or environment."
        )
    return value.strip()


def _parse_symbols(raw: str) -> list[str]:
    """Parse a comma-separated list of stock symbols.

    Inputs: raw string like 'AAPL,MSFT,GOOGL'.
    Outputs: list of uppercase, stripped, non-empty symbols.
    """
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    if not symbols:
        raise ConfigurationError(
            "STOCK_SYMBOLS is set but contains no valid symbols after parsing. "
            "Expected comma-separated ticker symbols like 'AAPL,MSFT,GOOGL'."
        )
    return symbols


def _parse_port(raw: str) -> int:
    """Parse and validate a port number.

    Inputs: raw port string.
    Outputs: integer port number between 1 and 65535.
    """
    try:
        port = int(raw)
    except ValueError:
        raise ConfigurationError(f"POSTGRES_PORT must be a valid integer, got: '{raw}'") from None
    if not 1 <= port <= 65535:
        raise ConfigurationError(f"POSTGRES_PORT must be between 1 and 65535, got: {port}")
    return port


class Config:
    """Immutable configuration container.

    All values are validated at construction time. Access fields directly:
        config = get_config()
        config.api_key
        config.stock_symbols
        config.db_host
    """

    def __init__(self) -> None:
        # API configuration — values are not logged
        self.api_key: str = _require_env("ALPHA_VANTAGE_API_KEY")
        self.stock_symbols: list[str] = _parse_symbols(_require_env("STOCK_SYMBOLS"))

        # Database configuration — password is not logged
        self.db_host: str = _require_env("POSTGRES_HOST")
        self.db_port: int = _parse_port(_require_env("POSTGRES_PORT"))
        self.db_name: str = _require_env("POSTGRES_DB")
        self.db_user: str = _require_env("POSTGRES_USER")
        self.db_password: str = _require_env("POSTGRES_PASSWORD")

    def get_db_connection_params(self) -> dict:
        """Return connection parameters for psycopg.connect().

        Outputs: dict with host, port, dbname, user, password.
        """
        return {
            "host": self.db_host,
            "port": self.db_port,
            "dbname": self.db_name,
            "user": self.db_user,
            "password": self.db_password,
        }


# Module-level singleton — validated on first import
_config: Config | None = None


def get_config() -> Config:
    """Return the validated configuration singleton.

    Inputs: reads from environment variables on first call.
    Outputs: Config instance with all fields validated.
    Raises ConfigurationError immediately if any required var is missing.
    """
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> None:
    """Reset the config singleton (for testing only).

    This allows tests to re-read environment variables between test cases.
    """
    global _config
    _config = None
