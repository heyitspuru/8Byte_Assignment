# Dockerfile for the stock market data pipeline.
# Base: Apache Airflow 3.3.1 with Python 3.12 on Debian Bookworm.
# No secrets baked in — all config via environment variables at runtime.

FROM apache/airflow:3.3.1-python3.12

# Switch to root to install system dependencies if needed
USER root

# Install system dependencies for psycopg (binary wheels handle most cases,
# but having libpq-dev available ensures compatibility)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Switch back to airflow user for pip installs
USER airflow

# Copy and install Python dependencies
# Uses Airflow's constraints file to prevent version conflicts
COPY requirements.txt /opt/airflow/requirements.txt
RUN pip install --no-cache-dir \
    -c "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-3.12.txt" \
    -r /opt/airflow/requirements.txt

# Copy application source code
COPY src/ /opt/airflow/src/
COPY dags/ /opt/airflow/dags/
COPY sql/ /opt/airflow/sql/
