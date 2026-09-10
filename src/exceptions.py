# src/exceptions.py
# Defines the exception hierarchy for the stock market pipeline.
# Imports from: nothing (leaf module).
# Maps 1:1 to the error taxonomy in rules/error-handling-and-security-rules.md.

"""
Exception hierarchy for the stock market data pipeline.

Every failure mode maps to exactly one exception class here.
Callers catch specific types to decide retry vs. fail-fast behavior.
The taxonomy is enforced by rules/error-handling-and-security-rules.md.
"""


class PipelineError(Exception):
    """Base exception for all pipeline errors.

    All custom exceptions inherit from this so callers can catch
    PipelineError as a last resort — but specific subclasses should
    always be caught first.
    """


# ---------------------------------------------------------------------------
# API-layer exceptions
# ---------------------------------------------------------------------------


class ApiError(PipelineError):
    """Base for all API-related failures."""


class TransientApiError(ApiError):
    """Retryable API errors: timeouts, 5xx, connection failures.

    Inputs: HTTP status code or timeout details.
    Outputs: raised to let Airflow retry the task.
    """


class RateLimitError(TransientApiError):
    """HTTP 429 — rate limit exceeded.

    Inputs: HTTP 429 response.
    Outputs: raised to let Airflow retry with backoff.
    """


class InvalidApiKeyError(ApiError):
    """Invalid or missing API key — fail fast, do not retry.

    Inputs: API error response indicating bad credentials.
    Outputs: fails the task immediately. Never includes the key in the message.
    """


class MalformedResponseError(ApiError):
    """Response body is not valid JSON or has unexpected structure — fail fast.

    Inputs: raw response that couldn't be parsed.
    Outputs: fails the task. Logs response status, never the full body if it might contain secrets.
    """


class EmptyPayloadError(ApiError):
    """The API returned a valid response but with no usable data — fail fast.

    Inputs: response missing 'Time Series (Daily)' or containing zero valid records after transform.
    Outputs: fails the task — the data contract isn't satisfied.
    """


# ---------------------------------------------------------------------------
# Data validation exceptions
# ---------------------------------------------------------------------------


class DataValidationError(PipelineError):
    """A single record failed validation — skip and log, don't abort the batch.

    Inputs: the offending field name and value.
    Outputs: the record is skipped; a warning is logged.
    """


# ---------------------------------------------------------------------------
# Database-layer exceptions
# ---------------------------------------------------------------------------


class DatabaseError(PipelineError):
    """Base for all database-related failures."""


class TransientDatabaseError(DatabaseError):
    """Database connection or availability issue — retryable.

    Inputs: connection error details.
    Outputs: raised to let Airflow retry the task.
    """


class DatabaseConstraintError(DatabaseError):
    """SQL constraint violation or query error — fail fast, rollback.

    Inputs: SQL error details (never including credentials).
    Outputs: transaction is rolled back, task fails.
    """
