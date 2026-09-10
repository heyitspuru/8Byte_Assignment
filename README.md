# Stock Market Data Pipeline

A Dockerized Apache Airflow pipeline that fetches daily stock price data from [Alpha Vantage](https://www.alphavantage.co/) and loads it into a PostgreSQL database using idempotent UPSERT operations.

## Architecture

```
Docker Compose
  ├── postgres              (healthcheck-gated, data persistence)
  ├── airflow-init          (one-shot: DB migration + admin user)
  ├── airflow-api-server    (Web UI on port 8080)
  ├── airflow-scheduler     (triggers DAG runs)
  ├── airflow-dag-processor (parses DAG files)
  └── airflow-triggerer     (async trigger support)

stock_market_pipeline DAG
  fetch_data → validate_data → load_data

Alpha Vantage TIME_SERIES_DAILY (compact, JSON)
        │
        ▼
stock_prices (symbol, trade_date) PK — UPSERT on conflict
```

### Module Boundaries

| Module | Responsibility |
|---|---|
| `dags/stock_market_pipeline.py` | Orchestration only — schedule, task graph, retries |
| `src/fetch_stock_data.py` | HTTP requests + API-level error handling |
| `src/transform.py` | JSON → typed records, validation, skip bad rows |
| `src/database.py` | PostgreSQL connection + transactional UPSERT |
| `src/config.py` | Environment variable loading and validation |
| `src/exceptions.py` | Pipeline exception hierarchy |
| `sql/init.sql` | Table DDL with composite primary key |

## Prerequisites

- **Docker Desktop** (Windows/Mac) or **Docker Engine + Compose plugin** (Linux)
  - Verify: `docker --version` and `docker compose version` (v2.x required)
- **Alpha Vantage API key** — free at [alphavantage.co](https://www.alphavantage.co/support/#api-key)
- **Git** — for cloning and version control

## Quick Start

### 1. Clone and configure

```bash
git clone <repository-url>
cd stock-market-pipeline

# Copy the example env file and fill in your values
cp .env.example .env
```

Edit `.env` and set **at minimum**:
- `ALPHA_VANTAGE_API_KEY` — your actual API key
- `POSTGRES_PASSWORD` — a secure password of your choice
- Update `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` to match your `POSTGRES_USER` and `POSTGRES_PASSWORD`

### 2. Build and start

```bash
# Initialize Airflow (run once)
docker compose up airflow-init

# Start all services
docker compose up -d

# Check status
docker compose ps
```

### 3. Access the Airflow UI

Open [http://localhost:8080](http://localhost:8080) in your browser.

- **Username:** `admin` (or whatever you set in `.env`)
- **Password:** `admin` (or whatever you set in `.env`)

### 4. Trigger the DAG

1. In the Airflow UI, find the `stock_market_pipeline` DAG
2. Toggle it **ON** (unpause)
3. Click the **Play** button to trigger a manual run
4. Monitor progress in the **Graph** or **Grid** view

### 5. Verify data

```bash
# Connect to PostgreSQL and check the data
docker compose exec postgres psql -U stock_user -d stocks \
  -c "SELECT symbol, trade_date, close_price, volume FROM stock_prices ORDER BY trade_date DESC LIMIT 10;"
```

## Configuration

All configuration is via environment variables in `.env`:

| Variable | Required | Description |
|---|---|---|
| `ALPHA_VANTAGE_API_KEY` | Yes | Your Alpha Vantage API key |
| `STOCK_SYMBOLS` | Yes | Comma-separated ticker symbols (e.g., `AAPL,MSFT,GOOGL`) |
| `POSTGRES_USER` | Yes | PostgreSQL username |
| `POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `POSTGRES_DB` | Yes | PostgreSQL database name |
| `AIRFLOW__CORE__FERNET_KEY` | No | Encryption key for Airflow connections |

## Idempotency

The pipeline is fully idempotent:
- The `stock_prices` table uses a composite primary key `(symbol, trade_date)`
- Every write uses `INSERT ... ON CONFLICT (symbol, trade_date) DO UPDATE`
- Running the pipeline multiple times on the same data produces the same rows, never duplicates

## Error Handling

| Failure | Behavior |
|---|---|
| Timeout / connection error | Retry (Airflow retries=3, 5min delay) |
| HTTP 429 (rate limit) | Retry with exponential backoff |
| HTTP 5xx | Retry |
| Invalid API key | Fail fast — clear error, no secret leaked |
| Missing time series data | Fail fast — data contract not satisfied |
| Single bad record | Skip and log, continue with valid records |
| PostgreSQL unavailable | Retry |
| SQL constraint error | Rollback transaction, fail fast |

## Testing

### Run locally (requires Python 3.12, `pip install -r requirements.txt pytest ruff`)

```bash
# Lint
ruff check .
ruff format --check .

# Unit tests (no live DB/API needed)
pytest -q -m "not integration"
```

### Run in Docker

```bash
# The DAG parse test and integration tests run inside the Airflow containers
docker compose exec airflow-api-server pytest /opt/airflow/tests/ -q
```

## Project Structure

```
├── docker-compose.yml          # Full stack definition
├── Dockerfile                  # Airflow 3.3.1 + Python 3.12
├── requirements.txt            # Pinned Python deps
├── .env.example                # Template for environment config
├── pyproject.toml              # Ruff + pytest config
├── dags/
│   └── stock_market_pipeline.py  # Airflow DAG (orchestration only)
├── src/
│   ├── config.py               # Env var loading + validation
│   ├── exceptions.py           # Exception hierarchy
│   ├── fetch_stock_data.py     # Alpha Vantage API client
│   ├── transform.py            # JSON → typed record transform
│   └── database.py             # PostgreSQL UPSERT
├── sql/
│   └── init.sql                # CREATE TABLE DDL
├── tests/
│   ├── test_config.py          # Config validation tests
│   ├── test_fetcher.py         # API client tests (mocked)
│   ├── test_transform.py       # Transform tests
│   ├── test_database.py        # DB layer tests (mocked)
│   └── test_dag_parses.py      # DAG import/parse test
└── .github/
    └── workflows/
        └── ci.yml              # Lint + test on push
```

## Troubleshooting

### Services won't start
```bash
docker compose logs postgres       # Check DB health
docker compose logs airflow-init   # Check init output
docker compose down -v             # Full reset (deletes data!)
docker compose up airflow-init     # Re-initialize
docker compose up -d
```

### DAG not visible in Airflow UI
- Check scheduler logs: `docker compose logs airflow-scheduler`
- Check DAG processor logs: `docker compose logs airflow-dag-processor`
- Verify the DAG file has no import errors

### API rate limiting
- Alpha Vantage free tier: 25 requests/day, 5 requests/minute
- The pipeline includes a 15-second delay between symbols
- If you see `RateLimitError`, wait and retry, or reduce `STOCK_SYMBOLS`

## Limitations

- **Alpha Vantage free tier**: 25 API calls/day limits the number of symbols you can fetch per run
- **No historical backfill**: `catchup=False` means only today's data is fetched when the DAG runs
- **Single-node Airflow**: Uses `LocalExecutor` — sufficient for this workload, not for production scale
- **No TLS**: Local demo stack does not use encrypted connections between services

## Teardown

```bash
# Stop all services
docker compose down

# Stop and remove all data (PostgreSQL data + Airflow logs)
docker compose down -v
```
