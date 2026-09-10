# src/database.py
# Handles PostgreSQL connection and transactional UPSERT of stock price records.
# Imports from: psycopg, logging, src.exceptions.

"""
Database layer for the stock market data pipeline.

Owns: PostgreSQL connection management and transactional UPSERT via
INSERT ... ON CONFLICT (symbol, trade_date) DO UPDATE.
Must never contain: Airflow scheduling logic, HTTP calls, or business logic.
"""

import logging

import psycopg

from src.exceptions import DatabaseConstraintError, TransientDatabaseError

logger = logging.getLogger(__name__)

UPSERT_SQL = """
    INSERT INTO stock_prices (
        symbol, trade_date, open_price, high_price, low_price, close_price, volume, updated_at
    )
    VALUES (
        %(symbol)s, %(trade_date)s, %(open_price)s, %(high_price)s,
        %(low_price)s, %(close_price)s, %(volume)s, NOW()
    )
    ON CONFLICT (symbol, trade_date) DO UPDATE SET
        open_price  = EXCLUDED.open_price,
        high_price  = EXCLUDED.high_price,
        low_price   = EXCLUDED.low_price,
        close_price = EXCLUDED.close_price,
        volume      = EXCLUDED.volume,
        updated_at  = NOW()
"""


def get_connection(connection_params: dict) -> psycopg.Connection:
    """Create a new database connection.

    Inputs: connection_params dict with host, port, dbname, user, password.
    Outputs: an open psycopg.Connection.
    Raises TransientDatabaseError if the connection fails.
    Never logs the connection string or password.
    """
    try:
        conn = psycopg.connect(**connection_params)
        logger.info(
            "Connected to database '%s' on %s:%s",
            connection_params.get("dbname"),
            connection_params.get("host"),
            connection_params.get("port"),
        )
        return conn
    except psycopg.OperationalError as exc:
        logger.error(
            "Failed to connect to database '%s' on %s:%s",
            connection_params.get("dbname"),
            connection_params.get("host"),
            connection_params.get("port"),
        )
        raise TransientDatabaseError(
            f"Cannot connect to database '{connection_params.get('dbname')}' "
            f"on {connection_params.get('host')}:{connection_params.get('port')}. "
            f"Is PostgreSQL running?"
        ) from exc


def upsert_stock_prices(conn: psycopg.Connection, records: list[dict]) -> int:
    """UPSERT stock price records into the database.

    Inputs:
        conn: an open psycopg.Connection
        records: list of dicts with keys matching the UPSERT_SQL parameters

    Outputs:
        int — number of rows upserted

    Behavior:
        - All-or-nothing per batch: uses a single transaction
        - Rolls back completely on any error mid-write
        - Never leaves a partially-written batch committed

    Raises:
        DatabaseConstraintError: on SQL errors (fail-fast, transaction rolled back)
        TransientDatabaseError: on connection issues (retryable)
    """
    if not records:
        logger.warning("upsert_stock_prices called with empty records list.")
        return 0

    try:
        with conn.transaction():
            cur = conn.cursor()
            cur.executemany(UPSERT_SQL, records)
            row_count = len(records)

        logger.info("Successfully upserted %d records.", row_count)
        return row_count

    except psycopg.OperationalError as exc:
        logger.error("Database connection error during upsert: %s", exc)
        raise TransientDatabaseError(f"Database connection lost during upsert: {exc}") from exc
    except psycopg.errors.UniqueViolation as exc:
        # This shouldn't happen with ON CONFLICT, but handle defensively
        logger.error("Unexpected unique violation during upsert: %s", exc)
        raise DatabaseConstraintError(f"Unexpected unique constraint violation: {exc}") from exc
    except psycopg.Error as exc:
        logger.error("Database error during upsert: %s", exc)
        raise DatabaseConstraintError(f"Database error during upsert: {exc}") from exc
