from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy.engine import URL, make_url


def test_database_url() -> str | URL | None:
    host = os.getenv("TEST_POSTGRES_HOST")
    user = os.getenv("TEST_POSTGRES_USER")
    database = os.getenv("TEST_POSTGRES_DB")
    if host and user and database:
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=os.getenv("TEST_POSTGRES_PASSWORD"),
            host=host,
            port=int(os.getenv("TEST_POSTGRES_PORT", "5432")),
            database=database,
        )

    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url:
        return database_url

    return None


def test_database_refusal_reason(database_url: str | URL) -> str | None:
    configured_database_url = os.getenv("DATABASE_URL")
    if configured_database_url and make_url(database_url) == make_url(configured_database_url):
        return "TEST_DATABASE_URL matches DATABASE_URL; refusing to run DB tests."

    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        return "TEST_DATABASE_URL database name must contain 'test'."
    return None


def resolve_test_database_url() -> str | URL | None:
    """Public alias for test_database_url().

    Returns the resolved test database URL from TEST_DATABASE_URL or
    TEST_POSTGRES_* environment variables, or None when neither is set.
    """
    return test_database_url()


def require_safe_test_database_url_or_skip() -> str | URL:
    """Return the test database URL or call pytest.skip().

    Skips the test when:
    - TEST_DATABASE_URL and TEST_POSTGRES_* are both unset.
    - The resolved URL matches DATABASE_URL (production DB guard).
    - The resolved database name does not contain 'test'.
    """
    database_url = resolve_test_database_url()
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL or TEST_POSTGRES_* to run PostgreSQL DB tests.")
    refusal_reason = test_database_refusal_reason(database_url)
    if refusal_reason:
        pytest.skip(refusal_reason)
    return database_url


def test_database_connection_settings() -> dict[str, Any]:
    database_url = test_database_url()
    if database_url:
        url = make_url(database_url)
        return {
            "host": url.host or "localhost",
            "port": url.port or 5432,
            "user": url.username,
            "password": url.password,
            "database": url.database,
            "database_url": database_url,
        }

    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
        "database": None,
        "database_url": None,
    }
