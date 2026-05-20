import importlib

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy.engine import make_url


def _load_session_module(monkeypatch, **env):
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)

    for key in (
        "DATABASE_URL",
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
        DATABASE_URL="postgresql+psycopg://user:pass@db:5432/app",
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
