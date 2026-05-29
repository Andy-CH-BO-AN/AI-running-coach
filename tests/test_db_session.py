import importlib

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy.engine import make_url


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
