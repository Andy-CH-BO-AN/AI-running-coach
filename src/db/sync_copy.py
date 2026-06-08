from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from sqlalchemy import MetaData, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from src.db import models  # noqa: F401
from src.db.base import Base
from src.db.sync_targets import build_target_engine

DEFAULT_SYNC_BATCH_SIZE = 500
LOGICAL_KEY_COLUMNS = {
    "users": ("external_source", "external_user_id"),
    "activities": ("garmin_activity_id",),
}


def _database_metadata() -> MetaData:
    return Base.metadata


def _sorted_tables(table_names: Iterable[str] | None = None) -> list[Table]:
    tables = list(_database_metadata().sorted_tables)
    if table_names is None:
        return tables

    wanted = set(table_names)
    return [table for table in tables if table.name in wanted]


def _batched_rows(engine: Engine, table: Table, batch_size: int) -> Iterator[list[dict[str, Any]]]:
    stmt = select(*table.c)
    primary_key_columns = list(table.primary_key.columns)
    if primary_key_columns:
        stmt = stmt.order_by(*primary_key_columns)

    with engine.connect() as connection:
        result = connection.execute(stmt).mappings()
        while True:
            batch = result.fetchmany(batch_size)
            if not batch:
                break
            yield [dict(row) for row in batch]


def _upsert_rows(engine: Engine, table: Table, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    stmt = pg_insert(table).values(rows)
    primary_key_columns = [column.name for column in table.primary_key.columns]
    if primary_key_columns:
        update_columns = [column.name for column in table.columns if column.name not in primary_key_columns]
        if update_columns:
            stmt = stmt.on_conflict_do_update(
                index_elements=primary_key_columns,
                set_={column: getattr(stmt.excluded, column) for column in update_columns},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=primary_key_columns)

    with engine.begin() as connection:
        connection.execute(stmt)


def _find_logical_key_conflicts(
    source_rows: Iterable[dict[str, Any]],
    target_rows: Iterable[dict[str, Any]],
    *,
    logical_key_columns: tuple[str, ...],
    primary_key_columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    def _build_index(rows: Iterable[dict[str, Any]]) -> dict[tuple[Any, ...], tuple[Any, ...]]:
        index = {}
        for row in rows:
            logical_key = tuple(row.get(column) for column in logical_key_columns)
            primary_key = tuple(row.get(column) for column in primary_key_columns)
            index[logical_key] = primary_key
        return index

    source_index = _build_index(source_rows)
    target_index = _build_index(target_rows)
    conflicts = []
    for logical_key in sorted(set(source_index) & set(target_index)):
        if source_index[logical_key] == target_index[logical_key]:
            continue
        conflicts.append(
            {
                "logical_key": logical_key,
                "source_primary_key": source_index[logical_key],
                "target_primary_key": target_index[logical_key],
            }
        )
    return conflicts


def _assert_no_logical_key_conflicts(source_engine: Engine, target_engine: Engine, table: Table) -> None:
    logical_key_columns = LOGICAL_KEY_COLUMNS.get(table.name)
    if not logical_key_columns:
        return

    primary_key_columns = tuple(column.name for column in table.primary_key.columns)
    selected_columns = list(table.primary_key.columns) + [table.c[column] for column in logical_key_columns]
    stmt = select(*selected_columns)

    with source_engine.connect() as source_connection, target_engine.connect() as target_connection:
        source_rows = [dict(row) for row in source_connection.execute(stmt).mappings()]
        target_rows = [dict(row) for row in target_connection.execute(stmt).mappings()]

    conflicts = _find_logical_key_conflicts(
        source_rows,
        target_rows,
        logical_key_columns=logical_key_columns,
        primary_key_columns=primary_key_columns,
    )
    if conflicts:
        sample_conflict = conflicts[0]
        raise ValueError(
            "Logical key conflict detected before sync for "
            f"{table.name}. Same business row exists with different primary keys. "
            f"logical_key={sample_conflict['logical_key']!r}. "
            "Start from a fresh cloud sync or reconcile divergent rows before continuing."
        )


def sync_database_targets(
    source_target: str = "local",
    target_target: str = "cloud",
    *,
    batch_size: int = DEFAULT_SYNC_BATCH_SIZE,
    table_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    if source_target == target_target:
        raise ValueError("Source and target databases must be different.")

    source_engine = build_target_engine(source_target, purpose="direct")
    target_engine = build_target_engine(target_target, purpose="direct")
    table_results: list[dict[str, Any]] = []

    try:
        for table in _sorted_tables(table_names):
            _assert_no_logical_key_conflicts(source_engine, target_engine, table)
            copied_rows = 0
            for rows in _batched_rows(source_engine, table, batch_size):
                copied_rows += len(rows)
                _upsert_rows(target_engine, table, rows)
            table_results.append({"table": table.name, "rows_copied": copied_rows})
    finally:
        source_engine.dispose()
        target_engine.dispose()

    return {
        "source": source_target,
        "target": target_target,
        "batch_size": batch_size,
        "tables": table_results,
        "rows_copied": sum(item["rows_copied"] for item in table_results),
    }
