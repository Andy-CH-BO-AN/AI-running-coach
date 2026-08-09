from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy.engine import URL, make_url


LOCAL_TEST_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
FORBIDDEN_TEST_DATABASE_QUERY_KEYS = frozenset(
    {"conninfo", "database", "dbname", "dsn", "hostaddr", "service", "servicefile"}
)
LIBPQ_TARGET_ENV_NAMES = ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")


def _database_host_refusal_reason(database_url: URL) -> str | None:
    if any(os.getenv(name) for name in LIBPQ_TARGET_ENV_NAMES):
        return "PostgreSQL DB tests do not allow ambient connection target overrides."

    query_keys = {key.lower() for key in database_url.query}
    if query_keys & FORBIDDEN_TEST_DATABASE_QUERY_KEYS:
        return "PostgreSQL DB tests do not allow connection target overrides."

    host_values: list[str] = []
    if database_url.host:
        host_values.append(database_url.host)

    query_host = database_url.query.get("host")
    if isinstance(query_host, str):
        host_values.append(query_host)
    elif isinstance(query_host, tuple):
        host_values.extend(query_host)

    for configured_hosts in host_values:
        hosts = configured_hosts.split(",")
        has_unix_socket = any(host.strip().startswith("/") for host in hosts)
        if has_unix_socket and (len(host_values) != 1 or len(hosts) != 1):
            return "PostgreSQL DB tests require a local test database host."

        for host in hosts:
            normalized_host = host.strip().lower().rstrip(".")
            if normalized_host.startswith("/"):
                continue
            if normalized_host == "neon.tech" or normalized_host.endswith(".neon.tech"):
                return "Neon hosts are not allowed for PostgreSQL DB tests."
            if normalized_host not in LOCAL_TEST_DATABASE_HOSTS:
                return "PostgreSQL DB tests require a local test database host."
    return None


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
    parsed_database_url = make_url(database_url)
    configured_database_url = os.getenv("DATABASE_URL")
    if configured_database_url and parsed_database_url == make_url(configured_database_url):
        return "TEST_DATABASE_URL matches DATABASE_URL; refusing to run DB tests."

    host_refusal_reason = _database_host_refusal_reason(parsed_database_url)
    if host_refusal_reason:
        return host_refusal_reason

    database_name = parsed_database_url.database or ""
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
    - The resolved URL targets Neon or another remote host.
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
