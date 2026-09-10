# dags/stock_market_pipeline.py
# Airflow DAG that orchestrates the stock market data pipeline.
# Imports from: airflow, datetime, src.config, src.fetch_stock_data,
#               src.transform, src.database.

"""
Airflow DAG: stock_market_pipeline

Orchestrates: fetch_data → validate_data → load_data
Schedule: @daily, catchup=False, max_active_runs=1
Retries: 3 per task, 5-minute delay with exponential backoff
Execution timeout: 10 minutes per task

All business logic lives in src/ — this file only wires tasks together.
Triggers nodes: fetch_stock_data.fetch_daily_data, transform.transform_daily_data,
                database.upsert_stock_prices
Returns: task status to Airflow scheduler
"""

import logging
import time
from datetime import datetime, timedelta

from airflow.sdk import dag, task

logger = logging.getLogger(__name__)

# DAG-level defaults — applied to every task unless overridden
default_args = {
    "owner": "data-engineering",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(minutes=10),
}

# Rate limit delay between symbols (seconds) — respects the 5 req/min Alpha Vantage limit
RATE_LIMIT_DELAY_SECONDS = 15


@dag(
    dag_id="stock_market_pipeline",
    description="Fetches daily stock prices from Alpha Vantage and loads into PostgreSQL",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["stock-market", "data-pipeline"],
)
def stock_market_pipeline():
    """Main DAG definition. Wires three tasks: fetch → validate → load."""

    @task
    def fetch_data(**kwargs) -> dict:
        """Fetch raw stock data from Alpha Vantage for all configured symbols.

        Inputs: reads STOCK_SYMBOLS and API key from config.
        Outputs: dict mapping symbol → raw API response data.
        """
        from src.config import get_config
        from src.fetch_stock_data import fetch_daily_data

        config = get_config()
        all_data = {}

        for i, symbol in enumerate(config.stock_symbols):
            logger.info(
                "Fetching data for symbol %s (%d/%d)",
                symbol,
                i + 1,
                len(config.stock_symbols),
            )

            if i > 0:
                logger.info("Rate limit delay: sleeping %ds", RATE_LIMIT_DELAY_SECONDS)
                time.sleep(RATE_LIMIT_DELAY_SECONDS)

            raw_data = fetch_daily_data(symbol, config.api_key)
            all_data[symbol] = raw_data
            logger.info("Fetched data for %s successfully", symbol)

        return all_data

    @task
    def validate_data(raw_data: dict, **kwargs) -> list[dict]:
        """Transform and validate raw API data into typed records.

        Inputs: dict mapping symbol → raw API response.
        Outputs: flat list of validated record dicts ready for UPSERT.
        """
        from src.transform import transform_daily_data

        all_records = []

        for symbol, data in raw_data.items():
            logger.info("Transforming data for symbol %s", symbol)
            records = transform_daily_data(symbol, data)
            all_records.extend(records)
            logger.info("Transformed %d records for %s", len(records), symbol)

        logger.info("Total validated records: %d", len(all_records))
        return all_records

    @task
    def load_data(records: list[dict], **kwargs) -> None:
        """Load validated records into PostgreSQL via transactional UPSERT.

        Inputs: flat list of validated record dicts.
        Outputs: rows upserted into stock_prices table.
        """
        from src.config import get_config
        from src.database import get_connection, upsert_stock_prices

        if not records:
            logger.warning("No records to load. Skipping database write.")
            return

        config = get_config()
        conn = get_connection(config.get_db_connection_params())

        try:
            count = upsert_stock_prices(conn, records)
            logger.info("Successfully loaded %d records into stock_prices.", count)
        finally:
            conn.close()
            logger.info("Database connection closed.")

    # Wire the task dependencies: fetch → validate → load
    raw = fetch_data()
    validated = validate_data(raw)
    load_data(validated)


# Instantiate the DAG
stock_market_pipeline()
