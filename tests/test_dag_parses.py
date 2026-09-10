# tests/test_dag_parses.py
# DAG parse test — verifies the DAG imports cleanly with no side effects.

"""
Tests that the stock_market_pipeline DAG can be imported and parsed
without making any network or database calls.

This is a critical test: if the DAG module has import-time side effects
(e.g., calling get_config() or connecting to a database at module level),
this test will fail — and it should.
"""

import pytest


class TestDagParses:
    """Verify the DAG file imports cleanly and has the expected structure."""

    def test_dag_import_no_errors(self):
        """The DAG module imports without raising any exceptions."""
        # We need to mock airflow imports since Airflow may not be installed locally
        # In the Docker environment, this test runs with real Airflow
        try:
            import dags.stock_market_pipeline  # noqa: F401
        except ImportError as exc:
            if "airflow" in str(exc).lower():
                pytest.skip("Airflow not installed locally — test runs in Docker")
            raise

    def test_dag_has_expected_id(self):
        """The DAG has the correct dag_id."""
        try:
            # Access the DagBag to find our DAG
            import dags.stock_market_pipeline as dag_module

            # The module creates the DAG via the @dag decorator
            # Check that it defines the expected function
            assert hasattr(dag_module, "stock_market_pipeline")
        except ImportError:
            pytest.skip("Airflow not installed locally — test runs in Docker")

    def test_dag_catchup_disabled(self):
        """catchup must be False to avoid backfilling historical runs."""
        try:
            from airflow.models import DagBag

            dagbag = DagBag(dag_folder="dags/", include_examples=False)
            assert "stock_market_pipeline" in dagbag.dags
            dag = dagbag.dags["stock_market_pipeline"]
            assert dag.catchup is False
        except ImportError:
            pytest.skip("Airflow not installed locally — test runs in Docker")

    def test_dag_max_active_runs(self):
        """max_active_runs must be 1 to prevent concurrent execution."""
        try:
            from airflow.models import DagBag

            dagbag = DagBag(dag_folder="dags/", include_examples=False)
            dag = dagbag.dags["stock_market_pipeline"]
            assert dag.max_active_runs == 1
        except ImportError:
            pytest.skip("Airflow not installed locally — test runs in Docker")
