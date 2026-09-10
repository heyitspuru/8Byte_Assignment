# Stock Market Data Pipeline — Full Implementation Plan (Revised)

This document sits on top of two inputs you provided:

1. `Assignment: Dockerized Data Pipeline with Airflow/Dagster` — the graded requirements.
2. `Final End-to-End Implementation Plan` (PDF) — the architecture/design decisions already made.

It does three things: (a) assesses the PDF plan against the assignment and flags gaps, (b) specifies the dev
environment and tooling needed to actually build it, and (c) lays out a phased implementation roadmap with
clear exit criteria per phase. Two companion files enforce the parts of this plan that should **not** drift
during implementation — see `rules/` at the end of this document.

---

## 1. Assessment of the existing plan

The PDF's architecture is sound and over-delivers on the assignment (idempotent UPSERT, a real error taxonomy,
transactional loading, module boundaries). It should be kept largely as-is. The gaps are almost all in
*execution mechanics* — the things you need to actually sit down and build it — not in the architecture.

| Area | PDF plan status | Verdict | Tweak |
|---|---|---|---|
| Orchestrator (Airflow) | Justified, matches assignment wording | Keep | — |
| DB schema + idempotency (composite PK, `ON CONFLICT DO UPDATE`) | Strong | Keep | Add a secondary index on `trade_date` only if you expect to query across symbols by date — not required for the assignment scope |
| Error taxonomy (retry vs fail-fast) | Very strong, already table-form | Keep | Promote verbatim into a rules file so it's enforced during coding, not just documented |
| Version pinning | Uses `apache/airflow:3.1.7` as an *illustrative* tag | **Update** | Airflow's current stable line is **3.3.x** (as of Sept 2026; verify the exact patch at build time) supporting Python 3.10–3.14. Pin the exact patch version in both `Dockerfile` and `requirements.txt`, and use the matching `constraints-<version>` file from the Airflow repo when installing extra packages |
| Alpha Vantage free-tier limits | States 25 requests/day | Confirmed current | Also enforce the **5 requests/minute** cap explicitly in code (a `time.sleep` guard or a simple token bucket) once you move past a single symbol — the PDF's daily schedule avoids this for one symbol, but it becomes real the moment `STOCK_SYMBOLS` has more than a handful of tickers |
| Dev environment / IDE / local tooling | **Not addressed at all** | Gap | This is Section 3 below |
| Dependency management | `requirements.txt` only | Adequate | Optional upgrade: `pip-compile` (pip-tools) or `uv pip compile` for a locked, reproducible dependency set — nice-to-have, not required for grading |
| Linting/formatting | Not mentioned | Gap (feeds the "Code Quality" evaluation criterion) | Add `ruff` (lint + format in one tool) and `pre-commit`, kept minimal so it doesn't fight the plan's own "don't over-engineer" philosophy |
| CI | Not mentioned | Optional gap | A single lightweight GitHub Actions workflow (lint + unit tests + DAG-parse test) is a cheap, visible differentiator for "Code Quality" and "Correctness" — see Phase 9 |
| `.dockerignore` | Not mentioned | Gap | Needed so `.env`, `tests/`, `.git/` don't leak into the image or slow the build |
| DB testing strategy | Listed as a row ("Unit - database") without a mechanism | Needs specifics | Use the Compose Postgres service itself for integration-level DB tests (`docker compose exec postgres ...`), and `unittest.mock` for unit-level DB tests that shouldn't need a live connection — no new test-infra dependency required |
| README | Listed as deliverable, no authoring rule | Fine, add discipline | Every command in the README must be copy-pasted from a terminal you actually ran, not written from memory |
| Rules enforcement during coding | Not present | Gap you explicitly asked for | New `rules/` files, described in Section 10 |

**Net assessment:** don't redesign the architecture. Fill in the "how do I actually sit down and build this"
layer, and turn the PDF's already-good tables (error taxonomy, module boundaries) into enforceable rules so an
AI coding assistant or a second contributor can't quietly drift from them mid-implementation.

---

## 2. Finalized architecture (confirmed, with the tweaks above folded in)

```
Docker Compose
  ├── postgres            (healthcheck-gated)
  ├── airflow-init         (one-shot init)
  ├── airflow-scheduler
  ├── airflow-dag-processor
  ├── airflow-api-server
  ├── airflow-worker
  └── airflow-triggerer

stock_market_pipeline DAG
  fetch_data → validate_data → load_data
  (retries=3, retry_delay=5m w/ backoff, execution_timeout=10m, schedule=@daily, catchup=False, max_active_runs=1)

Alpha Vantage TIME_SERIES_DAILY (compact, json)
        │
        ▼
stock_prices (symbol, trade_date) PK, UPSERT on conflict
```

Everything else (data contract, SQL, retry table, edge-case playbook) from the PDF stands. Section 9 of the
PDF (error taxonomy) and Section 7 (module responsibility table) are the two sections promoted into the rules
files, because those are the ones most likely to erode under time pressure.

---

## 3. Development environment & tooling

### 3.1 IDE

| Option | When to pick it |
|---|---|
| **VS Code** (recommended) | Free, best Docker/Compose + Python + YAML extension support, lightest weight. Default choice unless you already have a PyCharm license. |
| **PyCharm Professional** | If you already use it — native Docker Compose run configs and a built-in DB client are genuinely nice here. Community edition lacks the Docker Compose integration, so it's not worth switching to just for this. |
| **AI-assisted IDE / agent (Cursor or Claude Code)** | Optional, but a good fit for this project because the plan is already fully specified — an agent mostly needs to *not deviate* from it. If you use one, load `rules/ai-coding-agent-rules.md` (or `.cursorrules`) as its instruction file before you start. |

VS Code extensions worth installing: **Python** + **Pylance**, **Docker**, **YAML** (Red Hat), **Ruff**,
**GitLens**, and a Postgres client extension (e.g. "PostgreSQL" by Chris Kolkman) so you can browse
`stock_prices` without leaving the editor.

### 3.2 Required software

| Tool | Purpose | Notes |
|---|---|---|
| **Docker Desktop** (Mac/Windows) or **Docker Engine + Compose plugin** (Linux) | Runs the whole stack | Confirm `docker compose version` reports v2.x. Windows: use the WSL2 backend. |
| **Git** | Version control, submission | — |
| **Python 3.11 or 3.12** (local interpreter, outside containers) | Running `pytest`, `ruff`, `pre-commit` locally without spinning up Docker every time | Match whatever you pin in the Dockerfile so local and container behavior agree |
| **A Postgres client** | Manually verifying `stock_prices` | `psql` CLI is enough; DBeaver/TablePlus/pgAdmin if you prefer a GUI |
| **Alpha Vantage free API key** | The actual data source | Sign up at alphavantage.co — instant, no card required |
| **curl or HTTPie/Postman** | Sanity-check the Alpha Vantage endpoint *before* wiring it into Python | Catches API-shape surprises early, outside of Airflow's retry/log noise |
| **pre-commit** (`pip install pre-commit`) | Runs `ruff` on every commit | Optional but cheap, and it's exactly the kind of thing graders notice |
| **make** (optional) | Convenience wrapper around long `docker compose` commands | Skip on Windows unless you're in WSL2; not required |
| **GitHub account + repo** | Submission target, and host for the optional CI workflow | — |

### 3.3 What you do *not* need

Kafka, Spark, Kubernetes, Redis, a message broker beyond Airflow's own, or a second orchestrator. The PDF is
explicit about this and it's correct — none of it improves your score against the stated evaluation criteria,
and all of it increases the surface area for something to break during grading.

---

## 4. Final repository structure

```
stock-market-pipeline/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitignore
├── .dockerignore                 # NEW — keep .env, tests, .git out of the image
├── .pre-commit-config.yaml       # NEW — ruff on commit
├── pyproject.toml                # NEW — ruff config (+ pytest config)
├── README.md
├── rules/                        # NEW — see Section 10
│   ├── architecture-and-code-rules.md
│   ├── error-handling-and-security-rules.md
│   └── ai-coding-agent-rules.md
├── .github/
│   └── workflows/
│       └── ci.yml                # NEW — optional, lint + unit tests + DAG-parse
├── dags/
│   └── stock_market_pipeline.py
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── exceptions.py
│   ├── fetch_stock_data.py
│   ├── transform.py
│   └── database.py
├── sql/
│   └── init.sql
└── tests/
    ├── test_fetcher.py
    ├── test_transform.py
    ├── test_database.py
    └── test_dag_parses.py        # NEW — explicit DAG import/parse test
```

---

## 5. Phased implementation roadmap

Each phase lists the goal, the concrete tasks, which tools from Section 3 you're using, and how you know
you're done. Work through them in order — each phase's exit criteria are the next phase's assumptions.

**Phase 0 — Environment bootstrap**
Install everything in Section 3.2. Verify: `docker --version`, `docker compose version`, `python3 --version`,
`git --version`, `psql --version`. Get your Alpha Vantage key and confirm it works with a bare `curl` call.
*Exit: a raw `curl` to the Alpha Vantage endpoint returns real JSON.*

**Phase 1 — Repo & tooling scaffold**
`git init`, create the directory tree in Section 4, write `.gitignore`/`.dockerignore`/`.env.example`, set up
`pyproject.toml` with `ruff`, install `pre-commit` and `pre-commit install`. Commit the skeleton.
*Exit: `pre-commit run --all-files` passes on an empty-ish repo.*

**Phase 2 — Database schema**
Write `sql/init.sql` (the PDF's `CREATE TABLE ... PRIMARY KEY (symbol, trade_date)`). Bring up a bare
`postgres` container locally and manually run the UPSERT SQL twice to prove idempotency by hand before any
Python touches it.
*Exit: running the same manual INSERT twice results in one row, updated, not two.*

**Phase 3 — Configuration & secrets layer**
`src/config.py`: read and validate every required env var at import time, fail fast with a clear (non-secret)
message if anything's missing. `src/exceptions.py`: define the exception hierarchy from the PDF's error
taxonomy (`InvalidApiRequest`, `RateLimitOrProviderInfo`, `EmptyOrInvalidPayload`, etc.).
*Exit: unit test proves a missing env var raises immediately with a readable message.*

**Phase 4 — API client**
`src/fetch_stock_data.py`: `requests.get(..., timeout=(5, 30))`, `raise_for_status()`, then the business-level
JSON checks (`Error Message`, `Information`, missing `Time Series (Daily)`). Mock all HTTP in tests — no test
should need a live API key.
*Exit: `tests/test_fetcher.py` covers 200/429/500/timeout/malformed-JSON/provider-error-payload, all mocked.*

**Phase 5 — Transform & validation**
`src/transform.py`: JSON → typed records (Decimal prices, int volume, `date` objects), skip-and-log any single
malformed record, raise if the whole series is empty/invalid.
*Exit: `tests/test_transform.py` covers a valid row, a missing field, a bad date, a bad number, and an empty
series.*

**Phase 6 — Database loader**
`src/database.py`: `psycopg` connection, transactional `executemany()` of the UPSERT SQL, rollback on any DB
exception.
*Exit: `tests/test_database.py` proves insert, duplicate-insert-is-update, and rollback-on-error, against the
Compose Postgres service.*

**Phase 7 — Airflow DAG**
`dags/stock_market_pipeline.py`: wire `fetch → validate → load` as the three tasks, with `retries=3`,
`retry_delay`, `execution_timeout`, `schedule="@daily"`, `catchup=False`, `max_active_runs=1`. Keep all
business logic in `src/`; the DAG file only orchestrates.
*Exit: `tests/test_dag_parses.py` imports the DAG module with zero network/DB calls and asserts the three
task IDs exist.*

**Phase 8 — Dockerization**
`Dockerfile` (pinned Airflow base image, pinned `requirements.txt`), `docker-compose.yml` (Postgres
healthcheck, `depends_on: condition: service_healthy`, `airflow-init` as a one-shot service, no `latest`
tags, no host-exposed Postgres port by default).
*Exit: `docker compose up airflow-init && docker compose up -d` brings up a clean stack from a fresh clone.*

**Phase 9 — Testing, failure injection, and CI**
Run the full local suite (`pytest -q`), then manually trigger the DAG from the Airflow UI, confirm rows in
`stock_prices`, then deliberately break things: stop Postgres mid-run, feed a bad API key, simulate a 429 —
confirm the retry/fail-fast behavior matches the error-taxonomy table exactly. Wire `.github/workflows/ci.yml`
to run `ruff check`, `pytest`, and the DAG-parse test on every push.
*Exit: every row of the PDF's Section 19 testing table and Section 20 edge-case table has been actually
exercised, not just designed.*

**Phase 10 — Documentation & submission packaging**
Write `README.md` with real, tested commands: build/run, Airflow UI usage, the exact `psql` verification
query, troubleshooting, test instructions, and the "what cannot be guaranteed" limitations section from the
PDF. Final `git log` review, then package/submit.
*Exit: someone with a clean machine and only the README can get rows into `stock_prices` without asking you a
question.*

---

## 6. Local dev workflow (cheat sheet)

```bash
# first run
docker compose up airflow-init
docker compose up -d

# day to day
docker compose ps
docker compose logs -f airflow-scheduler
docker compose exec postgres psql -U stock_user -d stocks \
  -c "SELECT symbol, trade_date, close_price, volume FROM stock_prices ORDER BY trade_date DESC LIMIT 10;"

# before every commit
ruff check . && ruff format --check .
pytest -q

# full reset
docker compose down -v
```

---

## 7. Deliverables mapping

| Assignment deliverable | Repo artifact | Status target |
|---|---|---|
| `docker-compose.yml` | `docker-compose.yml` | Phase 8 |
| Orchestrator logic (DAG) | `dags/stock_market_pipeline.py` | Phase 7 |
| Data-fetching script | `src/fetch_stock_data.py` (+ `transform.py`, `database.py`) | Phases 4–6 |
| `README.md` | `README.md` | Phase 10 |
| *(supporting, not separately graded but expected)* | `Dockerfile`, `requirements.txt`, `.env.example`, `sql/init.sql`, `tests/` | Phases 1–9 |

---

## 8. Testing strategy — execution detail

| Layer | Tool | What it must prove |
|---|---|---|
| Unit — fetcher | `pytest` + `unittest.mock` (or `responses`) | Every branch in the error taxonomy raises the right exception type; no secret ever appears in an exception message or log line |
| Unit — transform | `pytest` | Valid rows normalize correctly; each invalid-field case is skipped/rejected per policy, not silently coerced |
| Unit — database | `pytest`, real Postgres via Compose | Insert, duplicate-insert-becomes-update, rollback-on-error |
| DAG parse | `pytest` | DAG module imports cleanly, no network/DB side effects at import time, expected task IDs present |
| Integration | `docker compose up` + manual/CLI DAG trigger | End-to-end rows land in `stock_prices` |
| Failure injection | manual: `docker compose stop postgres`, a deliberately bad API key, a forced 429 | Behavior matches the retry/fail-fast table exactly |

---

## 9. Definition of done / submission checklist

- [ ] `docker compose up --build` works from a clean clone with no manual steps beyond copying `.env.example` → `.env`
- [ ] DAG visible, manually triggerable, and schedulable in the Airflow UI
- [ ] A real Alpha Vantage call succeeds with timeout + HTTP + business-level validation
- [ ] `stock_prices` has correct types, no duplicate `(symbol, trade_date)` rows after repeated runs
- [ ] Transient failures retry; deterministic failures fail fast and clearly; a mid-batch DB error rolls back cleanly
- [ ] Bad individual records are skipped and logged, never fabricated; a fully invalid payload fails loudly
- [ ] No secret is committed, logged, or printed anywhere
- [ ] `STOCK_SYMBOLS` is config-driven, not hardcoded in `src/`
- [ ] `ruff check` and `pytest -q` both pass locally and in CI (if you added the workflow)
- [ ] README lets a stranger reproduce everything above without asking you a question

---

## 10. Rules files (strict enforcement)

Two of the PDF's own tables — module responsibility and error taxonomy — are exactly the kind of thing that
quietly erodes under deadline pressure, especially if an AI coding assistant is doing some of the typing. They're
promoted into standalone rule files so they're checked against, not just read once:

- **`rules/architecture-and-code-rules.md`** — module boundaries, naming, idempotency, Docker rules, versioning.
- **`rules/error-handling-and-security-rules.md`** — the retry/fail-fast taxonomy as hard rules, plus secrets handling.
- **`rules/ai-coding-agent-rules.md`** — if you use Cursor, Claude Code, or another AI coding agent to write the
  actual code, point it at this file first. It keeps the agent inside this plan instead of improvising.
