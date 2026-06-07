import uuid
from collections.abc import Generator

import pytest
import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.base import Base
from src.db import models  # noqa: F401
from tests.db_settings import test_database_refusal_reason, test_database_url

load_dotenv()


def _test_database_url() -> str | URL | None:
    return test_database_url()


def _validate_test_database_url(database_url: str | URL) -> None:
    refusal_reason = test_database_refusal_reason(database_url)
    if refusal_reason:
        pytest.skip(refusal_reason)


def isolated_db_session() -> Generator[Session, None, None]:
    database_url = _test_database_url()
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL or TEST_POSTGRES_* to run PostgreSQL DB tests.")

    _validate_test_database_url(database_url)
    engine = sqlalchemy.create_engine(database_url, future=True)
    schema_name = f"test_schema_{uuid.uuid4().hex}"

    try:
        with engine.connect() as healthcheck:
            healthcheck.execute(text("select 1"))
    except SQLAlchemyError as exc:
        engine.dispose()
        pytest.skip(f"Cannot connect to TEST_DATABASE_URL: {exc}")

    with engine.begin() as connection:
        connection.execute(text(f"create schema {schema_name}"))

    connection = engine.connect()
    try:
        connection.execute(text(f"set search_path to {schema_name}"))
        Base.metadata.create_all(connection)
        session = Session(bind=connection, autoflush=False, expire_on_commit=False, future=True)
        try:
            yield session
        finally:
            session.rollback()
            session.close()
            connection.rollback()
    finally:
        connection.close()
        with engine.begin() as cleanup:
            cleanup.execute(text(f"drop schema if exists {schema_name} cascade"))
        engine.dispose()
