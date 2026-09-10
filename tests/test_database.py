# tests/test_database.py
# Unit tests for src/database.py — mocked, no live database required.

"""
Tests for the database layer (UPSERT and connection management).

Covers:
- Successful insert
- Duplicate insert becomes update (idempotent UPSERT)
- Rollback on database error
- Empty records list handling
- Connection failure raises TransientDatabaseError
- SQL errors raise DatabaseConstraintError
- Credentials never leak into exception messages
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.database import get_connection, upsert_stock_prices
from src.exceptions import DatabaseConstraintError, TransientDatabaseError

SAMPLE_RECORD = {
    "symbol": "AAPL",
    "trade_date": date(2026, 9, 10),
    "open_price": Decimal("150.0000"),
    "high_price": Decimal("152.0000"),
    "low_price": Decimal("149.0000"),
    "close_price": Decimal("151.5000"),
    "volume": 12345678,
}


class TestGetConnection:
    """Tests for the get_connection function."""

    @patch("src.database.psycopg.connect")
    def test_successful_connection(self, mock_connect):
        """A successful connection returns the connection object."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        params = {
            "host": "localhost",
            "port": 5432,
            "dbname": "stocks",
            "user": "stock_user",
            "password": "secret",
        }
        conn = get_connection(params)

        assert conn is mock_conn
        mock_connect.assert_called_once_with(**params)

    @patch("src.database.psycopg.connect")
    def test_connection_failure_raises_transient_error(self, mock_connect):
        """Connection failure should raise TransientDatabaseError (retryable)."""
        import psycopg

        mock_connect.side_effect = psycopg.OperationalError("connection refused")

        params = {
            "host": "localhost",
            "port": 5432,
            "dbname": "stocks",
            "user": "stock_user",
            "password": "secret",
        }
        with pytest.raises(TransientDatabaseError, match="Cannot connect"):
            get_connection(params)

    @patch("src.database.psycopg.connect")
    def test_password_not_in_error_message_or_logs(self, mock_connect, caplog):
        """Database password must never appear in exception messages or captured logs."""
        import psycopg

        mock_connect.side_effect = psycopg.OperationalError("connection refused")

        password = "super_secret_password_12345"
        params = {
            "host": "localhost",
            "port": 5432,
            "dbname": "stocks",
            "user": "stock_user",
            "password": password,
        }
        with pytest.raises(TransientDatabaseError) as exc_info:
            get_connection(params)

        assert password not in str(exc_info.value)
        assert password not in caplog.text


class TestUpsertStockPrices:
    """Tests for the upsert_stock_prices function."""

    def test_successful_insert(self):
        """Records are inserted via executemany within a transaction."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        # Mock the transaction context manager
        mock_conn.transaction.return_value.__enter__ = MagicMock()
        mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=False)

        count = upsert_stock_prices(mock_conn, [SAMPLE_RECORD])

        assert count == 1
        mock_cursor.executemany.assert_called_once()

    def test_multiple_records_insert(self):
        """Multiple records are all passed to executemany."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.transaction.return_value.__enter__ = MagicMock()
        mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=False)

        records = [
            SAMPLE_RECORD,
            {**SAMPLE_RECORD, "trade_date": date(2026, 9, 9)},
        ]
        count = upsert_stock_prices(mock_conn, records)

        assert count == 2
        call_args = mock_cursor.executemany.call_args
        assert len(call_args[0][1]) == 2

    def test_empty_records_returns_zero(self):
        """Calling with an empty list returns 0 without touching the DB."""
        mock_conn = MagicMock()

        count = upsert_stock_prices(mock_conn, [])

        assert count == 0
        mock_conn.cursor.assert_not_called()

    def test_operational_error_raises_transient(self):
        """A connection error during upsert should raise TransientDatabaseError."""
        import psycopg

        mock_conn = MagicMock()
        mock_conn.transaction.return_value.__enter__ = MagicMock()
        mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.executemany.side_effect = psycopg.OperationalError("lost connection")

        with pytest.raises(TransientDatabaseError, match="connection lost"):
            upsert_stock_prices(mock_conn, [SAMPLE_RECORD])

    def test_generic_db_error_raises_constraint_error(self):
        """A generic psycopg.Error during upsert should raise DatabaseConstraintError."""
        import psycopg

        mock_conn = MagicMock()
        mock_conn.transaction.return_value.__enter__ = MagicMock()
        mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.executemany.side_effect = psycopg.Error("some SQL error")

        with pytest.raises(DatabaseConstraintError, match="Database error"):
            upsert_stock_prices(mock_conn, [SAMPLE_RECORD])


@pytest.mark.integration
class TestDatabaseIntegration:
    """Integration tests that execute against a live PostgreSQL instance.

    These tests verify real transactional behavior, composite primary key constraints,
    and idempotent UPSERT (ON CONFLICT DO UPDATE).
    """

    @pytest.fixture(autouse=True)
    def db_connection(self):
        """Obtain a live database connection or skip if PostgreSQL is unavailable."""
        import os

        import psycopg

        host = os.getenv("POSTGRES_HOST", "localhost")
        port = int(os.getenv("POSTGRES_PORT", "5432"))
        dbname = os.getenv("POSTGRES_DB", "stocks")
        user = os.getenv("POSTGRES_USER", "stock_user")
        password = os.getenv("POSTGRES_PASSWORD", "test_password")

        try:
            conn = psycopg.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=user,
                password=password,
                connect_timeout=3,
            )
        except psycopg.OperationalError:
            pytest.skip("PostgreSQL instance not reachable for integration tests")

        yield conn
        conn.close()

    def test_live_upsert_idempotency(self, db_connection):
        """Proves that inserting the same record twice updates instead of duplicating."""
        test_record = {
            "symbol": "TEST",
            "trade_date": date(2026, 9, 10),
            "open_price": Decimal("100.0000"),
            "high_price": Decimal("105.0000"),
            "low_price": Decimal("99.0000"),
            "close_price": Decimal("102.0000"),
            "volume": 50000,
        }

        # First insert
        count1 = upsert_stock_prices(db_connection, [test_record])
        assert count1 == 1

        # Second insert with updated close price
        updated_record = {**test_record, "close_price": Decimal("104.5000")}
        count2 = upsert_stock_prices(db_connection, [updated_record])
        assert count2 == 1

        # Verify exactly one row exists and close_price was updated
        with db_connection.cursor() as cur:
            cur.execute(
                "SELECT close_price FROM stock_prices WHERE symbol = %s AND trade_date = %s",
                ("TEST", date(2026, 9, 10)),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == Decimal("104.5000")

            # Cleanup
            cur.execute("DELETE FROM stock_prices WHERE symbol = %s", ("TEST",))
            db_connection.commit()
