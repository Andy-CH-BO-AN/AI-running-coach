import os
import uuid
from collections.abc import Generator

import pytest
import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.base import Base
from src.db import models  # noqa: F401

load_dotenv()


def _validate_test_database_url(database_url: str) -> None:
    configured_database_url = os.getenv("DATABASE_URL")
    if configured_database_url and database_url == configured_database_url:
        pytest.skip("TEST_DATABASE_URL matches DATABASE_URL; refusing to run DB tests.")

    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        pytest.skip("TEST_DATABASE_URL database name must contain 'test'.")


def isolated_db_session() -> Generator[Session, None, None]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL DB tests.")

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
