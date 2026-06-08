import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from tests.db_settings import test_database_connection_settings, test_database_refusal_reason


def _settings() -> dict[str, str | int | None]:
    return test_database_connection_settings()


def main() -> int:
    settings = _settings()
    refusal_reason = (
        test_database_refusal_reason(settings["database_url"])
        if settings.get("database_url")
        else None
    )
    if refusal_reason:
        print(refusal_reason, file=sys.stderr)
        return 2

    database = str(settings.get("database") or "")
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
