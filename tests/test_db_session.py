import importlib

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from unittest.mock import Mock


def _load_session_module(monkeypatch, **env):
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)

    for key in (
        "DATABASE_MODE",
        "DATABASE_URL",
        "LOCAL_DATABASE_URL",
        "NEON_DATABASE_URL",
        "NEON_DATABASE_DIRECT_URL",
        "DATABASE_MIGRATION_TARGET",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    ):
        monkeypatch.delenv(key, raising=False)

    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import src.db.session as session

    return importlib.reload(session)


def test_get_database_url_uses_database_url_when_present(monkeypatch):
    module = _load_session_module(
        monkeypatch,
        DATABASE_URL="postgresql://user:pass@db:5432/app",
    )

    assert module.get_database_url() == "postgresql+psycopg://user:pass@db:5432/app"


def test_get_database_url_builds_safe_url_from_postgres_env(monkeypatch):
    module = _load_session_module(
        monkeypatch,
        POSTGRES_HOST="postgres",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD="pa@ss:word",
        POSTGRES_DB="ai_running_coach",
    )

    url = make_url(module.get_database_url())

    assert url.drivername == "postgresql+psycopg"
    assert url.username == "postgres"
    assert url.host == "postgres"
    assert url.port == 5432
    assert url.database == "ai_running_coach"
    assert module.get_database_url() == "postgresql+psycopg://postgres:pa%40ss%3Aword@postgres:5432/ai_running_coach"


def test_get_database_url_uses_neon_pooler_when_cloud_mode_enabled(monkeypatch):
    module = _load_session_module(
        monkeypatch,
        DATABASE_MODE="cloud",
        DATABASE_URL="postgresql://local:pass@localhost:5432/local_db",
        NEON_DATABASE_URL="postgresql://neon:pass@ep-demo-pooler.neon.tech/neon_db",
        NEON_DATABASE_DIRECT_URL="postgresql://neon:pass@ep-demo.neon.tech/neon_db",
    )

    assert module.get_database_url() == "postgresql+psycopg://neon:pass@ep-demo-pooler.neon.tech/neon_db"


def test_get_shadow_database_url_uses_neon_pooler_in_mirror_mode(monkeypatch):
    module = _load_session_module(
        monkeypatch,
        DATABASE_MODE="mirror",
        DATABASE_URL="postgresql://local:pass@localhost:5432/local_db",
        NEON_DATABASE_URL="postgresql://neon:pass@ep-demo-pooler.neon.tech/neon_db",
    )

    assert module.get_database_url() == "postgresql+psycopg://local:pass@localhost:5432/local_db"
    assert module.get_shadow_database_url() == "postgresql+psycopg://neon:pass@ep-demo-pooler.neon.tech/neon_db"


def test_get_migration_database_url_uses_neon_direct_url(monkeypatch):
    module = _load_session_module(
        monkeypatch,
        DATABASE_MODE="cloud",
        DATABASE_MIGRATION_TARGET="cloud",
        NEON_DATABASE_URL="postgresql://neon:pass@ep-demo-pooler.neon.tech/neon_db",
        NEON_DATABASE_DIRECT_URL="postgresql://neon:pass@ep-demo.neon.tech/neon_db",
    )

    assert module.get_migration_database_url() == "postgresql+psycopg://neon:pass@ep-demo.neon.tech/neon_db"


def test_get_migration_database_url_requires_explicit_neon_direct_url(monkeypatch):
    module = _load_session_module(
        monkeypatch,
        DATABASE_MODE="cloud",
        DATABASE_MIGRATION_TARGET="cloud",
        NEON_DATABASE_URL="postgresql://neon:pass@ep-demo-pooler.neon.tech/neon_db",
    )

    with pytest.raises(ValueError, match="NEON_DATABASE_DIRECT_URL"):
        module.get_migration_database_url()


def test_get_database_mode_rejects_unknown_value(monkeypatch):
    module = _load_session_module(monkeypatch)
    monkeypatch.setenv("DATABASE_MODE", "weird")

    with pytest.raises(ValueError, match="Unsupported DATABASE_MODE"):
        module.get_database_mode()


def test_database_connection_classifier_rejects_statement_timeout():
    from src.db.settings import is_database_connection_error

    statement_timeout = OperationalError(
        "SELECT expensive_query",
        {},
        Exception("canceling statement due to statement timeout"),
    )

    assert is_database_connection_error(statement_timeout) is False


class _DriverError(Exception):
    def __init__(self, message: str, *, sqlstate: str | None = None):
        super().__init__(message)
        self.sqlstate = sqlstate


def test_database_connection_classifier_accepts_connection_timeout_expired():
    from src.db.settings import is_database_connection_error

    connection_timeout = OperationalError(
        "SELECT 1",
        {},
        _DriverError("connection failed: connection timeout expired"),
    )

    assert is_database_connection_error(connection_timeout) is True


def test_database_connection_classifier_accepts_cannot_connect_now():
    from src.db.settings import is_database_connection_error

    compute_starting = OperationalError(
        "SELECT 1",
        {},
        _DriverError(
            "FATAL: the database system is starting up",
            sqlstate="57P03",
        ),
    )

    assert is_database_connection_error(compute_starting) is True


@pytest.mark.parametrize("sqlstate", ["57P01", "57P02"])
def test_database_connection_classifier_accepts_shutdown_sqlstates(sqlstate):
    from src.db.settings import is_database_connection_error

    shutdown_error = OperationalError(
        "SELECT 1",
        {},
        _DriverError("database connection terminated during restart", sqlstate=sqlstate),
        connection_invalidated=True,
    )

    assert is_database_connection_error(shutdown_error) is True


@pytest.mark.parametrize(
    ("sqlstate", "connection_invalidated"),
    [("57014", False), ("57P04", True)],
)
def test_database_connection_classifier_rejects_other_operator_intervention_states(
    sqlstate,
    connection_invalidated,
):
    from src.db.settings import is_database_connection_error

    non_transient_error = OperationalError(
        "SELECT 1",
        {},
        _DriverError("non-transient operator intervention", sqlstate=sqlstate),
        connection_invalidated=connection_invalidated,
    )

    assert is_database_connection_error(non_transient_error) is False


@pytest.mark.parametrize("sqlstate", ["28P01", None])
def test_database_connection_classifier_rejects_authentication_failures(sqlstate):
    from src.db.settings import is_database_connection_error

    authentication_failure = OperationalError(
        "SELECT 1",
        {},
        _DriverError(
            "connection failed: FATAL: password authentication failed for user",
            sqlstate=sqlstate,
        ),
    )

    assert is_database_connection_error(authentication_failure) is False


@pytest.mark.parametrize("error_name", ["AdminShutdown", "CrashShutdown", "CannotConnectNow"])
def test_database_connection_classifier_accepts_exact_restart_error_classes(error_name):
    from src.db.settings import is_database_connection_error

    driver_error_type = type(error_name, (Exception,), {})
    restart_error = OperationalError(
        "SELECT 1",
        {},
        driver_error_type("temporary database restart"),
    )

    assert is_database_connection_error(restart_error) is True


@pytest.mark.parametrize(
    "error_name",
    ["AdminShutdownSomething", "CrashShutdownHelper", "CannotConnectNow2"],
)
def test_database_connection_classifier_rejects_similar_restart_error_classes(error_name):
    from src.db.settings import is_database_connection_error

    driver_error_type = type(error_name, (Exception,), {})
    other_error = OperationalError(
        "SELECT 1",
        {},
        driver_error_type("unrelated migration failure"),
    )

    assert is_database_connection_error(other_error) is False


def test_authentication_marker_fails_closed_even_with_connection_sqlstate():
    from src.db.settings import is_database_connection_error

    contradictory_error = OperationalError(
        "SELECT 1",
        {},
        _DriverError(
            "password authentication failed during connection",
            sqlstate="08006",
        ),
    )

    assert is_database_connection_error(contradictory_error) is False


def test_unknown_invalidated_operational_error_fails_closed():
    from src.db.settings import is_database_connection_error

    unknown_error = OperationalError(
        "SELECT 1",
        {},
        _DriverError("unclassified operational failure"),
        connection_invalidated=True,
    )

    assert is_database_connection_error(unknown_error) is False


def test_database_connection_classifier_ignores_unrelated_implicit_exception_context():
    from src.db.settings import is_database_connection_error

    transient = OperationalError(
        "SELECT 1",
        {},
        _DriverError("connection refused", sqlstate="08006"),
    )

    try:
        raise transient
    except OperationalError:
        try:
            raise IntegrityError("INSERT", {}, Exception("constraint failed"))
        except IntegrityError as fatal:
            assert fatal.__context__ is transient
            assert is_database_connection_error(fatal) is False


def test_dispose_database_connections_clears_cached_engines_and_factories(monkeypatch):
    module = _load_session_module(monkeypatch)
    primary_engine = Mock()
    shadow_engine = Mock()
    module._engine = primary_engine
    module._shadow_engine = shadow_engine
    module._session_factory = Mock()
    module._shadow_session_factory = Mock()

    module.dispose_database_connections()

    primary_engine.dispose.assert_called_once_with()
    shadow_engine.dispose.assert_called_once_with()
    assert module._engine is None
    assert module._shadow_engine is None
    assert module._session_factory is None
    assert module._shadow_session_factory is None


# ---------------------------------------------------------------------------
# db_settings safety-guard unit tests
# These do not require a real database connection.
# ---------------------------------------------------------------------------

import importlib as _importlib


def _clear_test_db_env(monkeypatch):
    for key in (
        "TEST_DATABASE_URL",
        "TEST_POSTGRES_HOST",
        "TEST_POSTGRES_USER",
        "TEST_POSTGRES_PASSWORD",
        "TEST_POSTGRES_DB",
        "TEST_POSTGRES_PORT",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_resolve_test_database_url_returns_none_when_env_missing(monkeypatch):
    _clear_test_db_env(monkeypatch)
    import tests.db_settings as _dbs
    _importlib.reload(_dbs)
    assert _dbs.resolve_test_database_url() is None


def test_resolve_test_database_url_uses_test_database_url_env(monkeypatch):
    _clear_test_db_env(monkeypatch)
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/myapp_test")
    import tests.db_settings as _dbs
    _importlib.reload(_dbs)
    assert _dbs.resolve_test_database_url() == "postgresql+psycopg://u:p@localhost:5432/myapp_test"


def test_resolve_test_database_url_builds_from_postgres_env(monkeypatch):
    _clear_test_db_env(monkeypatch)
    monkeypatch.setenv("TEST_POSTGRES_HOST", "testhost")
    monkeypatch.setenv("TEST_POSTGRES_USER", "testuser")
    monkeypatch.setenv("TEST_POSTGRES_PASSWORD", "testpass")
    monkeypatch.setenv("TEST_POSTGRES_DB", "ai_running_coach_test")
    import tests.db_settings as _dbs
    _importlib.reload(_dbs)
    result = _dbs.resolve_test_database_url()
    assert result is not None
    url = make_url(result)
    assert url.host == "testhost"
    assert url.username == "testuser"
    assert url.database == "ai_running_coach_test"
    assert url.port == 5432


def test_test_database_refusal_reason_rejects_when_matches_database_url(monkeypatch):
    prod = "postgresql+psycopg://u:p@localhost:5432/ai_running_coach"
    monkeypatch.setenv("DATABASE_URL", prod)
    import tests.db_settings as _dbs
    _importlib.reload(_dbs)
    reason = _dbs.test_database_refusal_reason(prod)
    assert reason is not None
    assert "DATABASE_URL" in reason


def test_test_database_refusal_reason_rejects_non_test_db_name(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import tests.db_settings as _dbs
    _importlib.reload(_dbs)
    reason = _dbs.test_database_refusal_reason(
        "postgresql+psycopg://u:p@localhost:5432/ai_running_coach"
    )
    assert reason is not None
    assert "test" in reason.lower()


def test_test_database_refusal_reason_allows_safe_test_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import tests.db_settings as _dbs
    _importlib.reload(_dbs)
    reason = _dbs.test_database_refusal_reason(
        "postgresql+psycopg://u:p@localhost:5432/ai_running_coach_test"
    )
    assert reason is None


def test_require_safe_skips_when_env_missing(monkeypatch):
    _clear_test_db_env(monkeypatch)
    import tests.db_settings as _dbs
    _importlib.reload(_dbs)
    with pytest.raises(pytest.skip.Exception):
        _dbs.require_safe_test_database_url_or_skip()


def test_require_safe_skips_on_prod_url_match(monkeypatch):
    _clear_test_db_env(monkeypatch)
    prod = "postgresql+psycopg://u:p@localhost:5432/ai_running_coach"
    monkeypatch.setenv("TEST_DATABASE_URL", prod)
    monkeypatch.setenv("DATABASE_URL", prod)
    import tests.db_settings as _dbs
    _importlib.reload(_dbs)
    with pytest.raises(pytest.skip.Exception):
        _dbs.require_safe_test_database_url_or_skip()


def test_require_safe_skips_on_non_test_db_name(monkeypatch):
    _clear_test_db_env(monkeypatch)
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/ai_running_coach")
    import tests.db_settings as _dbs
    _importlib.reload(_dbs)
    with pytest.raises(pytest.skip.Exception):
        _dbs.require_safe_test_database_url_or_skip()


def test_require_safe_returns_url_for_safe_target(monkeypatch):
    _clear_test_db_env(monkeypatch)
    safe = "postgresql+psycopg://u:p@localhost:5432/ai_running_coach_test"
    monkeypatch.setenv("TEST_DATABASE_URL", safe)
    import tests.db_settings as _dbs
    _importlib.reload(_dbs)
    result = _dbs.require_safe_test_database_url_or_skip()
    assert result == safe


# ---------------------------------------------------------------------------
# ensure_test_database.py regression: no-database-configured path
# ---------------------------------------------------------------------------

def test_ensure_script_returns_exit2_when_no_test_db_configured(monkeypatch):
    """Regression: ensure script must exit 2 without any connection attempt when
    TEST_DATABASE_URL and TEST_POSTGRES_* are both missing/incomplete."""
    _clear_test_db_env(monkeypatch)
    # Also clear POSTGRES_* so no fallback host sneaks through
    for key in ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT"):
        monkeypatch.delenv(key, raising=False)

    import tests.scripts.ensure_test_database as _ensure
    _importlib.reload(_ensure)

    # Patch psycopg.connect to detect if a connection is attempted (it must NOT be)
    import psycopg as _psycopg

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("psycopg.connect should not be called when no DB is configured")

    monkeypatch.setattr(_psycopg, "connect", _fail_if_called)
    assert _ensure.main() == 2
