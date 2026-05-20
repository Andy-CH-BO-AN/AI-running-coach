import os
import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def _settings() -> dict[str, str | int | None]:
    host = os.getenv("TEST_POSTGRES_HOST")
    user = os.getenv("TEST_POSTGRES_USER")
    database = os.getenv("TEST_POSTGRES_DB")
    if host and user and database:
        return {
            "host": host,
            "port": int(os.getenv("TEST_POSTGRES_PORT", "5432")),
            "user": user,
            "password": os.getenv("TEST_POSTGRES_PASSWORD"),
            "database": database,
        }

    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url:
        url = make_url(database_url)
        return {
            "host": url.host or "localhost",
            "port": url.port or 5432,
            "user": url.username,
            "password": url.password,
            "database": url.database,
        }

    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
        "database": None,
    }


def main() -> int:
    settings = _settings()
    database = str(settings.get("database") or "")
    if "test" not in database.lower():
        print("Refusing to create test database: target database name must contain 'test'.", file=sys.stderr)
        return 2

    maintenance_db = os.getenv("TEST_POSTGRES_MAINTENANCE_DB") or os.getenv("POSTGRES_DB") or "postgres"
    with psycopg.connect(
        host=settings["host"],
        port=settings["port"],
        user=settings["user"],
        password=settings["password"],
        dbname=maintenance_db,
        autocommit=True,
    ) as connection:
        exists = connection.execute("select 1 from pg_database where datname = %s", (database,)).fetchone()
        if not exists:
            connection.execute(sql.SQL("create database {}").format(sql.Identifier(database)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
