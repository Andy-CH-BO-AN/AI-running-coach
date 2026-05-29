from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import MetaData, create_engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from src.db.base import Base
from src.db import models  # noqa: F401
from src.db.session import resolve_database_url

DEFAULT_SYNC_BATCH_SIZE = 500
LOGICAL_KEY_COLUMNS = {
    "users": ("external_source", "external_user_id"),
    "activities": ("garmin_activity_id",),
}
SNAPSHOT_MARKER_COLUMNS = (
    "updated_at",
    "created_at",
    "started_at",
    "captured_at",
    "computed_at",
    "activity_date",
    "week_start",
    "garmin_activity_id",
)


def _database_metadata() -> MetaData:
    return Base.metadata


def _sorted_tables(table_names: Iterable[str] | None = None) -> list[Table]:
    tables = list(_database_metadata().sorted_tables)
    if table_names is None:
        return tables

    wanted = set(table_names)
    return [table for table in tables if table.name in wanted]


def build_target_engine(target: str, *, purpose: str = "direct") -> Engine:
    return create_engine(resolve_database_url(target, purpose=purpose), future=True, pool_pre_ping=True)


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


def _serialize_marker_value(value: Any) -> str | int | float | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _serialize_marker_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_marker_value(item) for item in value]
    return value


def _table_content_digest(connection, table: Table) -> str:
    stmt = select(*table.c)
    primary_key_columns = list(table.primary_key.columns)
    if primary_key_columns:
        stmt = stmt.order_by(*primary_key_columns)

    hasher = hashlib.sha256()
    result = connection.execute(stmt).mappings()
    for row in result:
        payload = json.dumps(
            {key: _serialize_marker_value(value) for key, value in dict(row).items()},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        hasher.update(payload.encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def _marker_column(table: Table):
    for column_name in SNAPSHOT_MARKER_COLUMNS:
        column = table.c.get(column_name)
        if column is not None:
            return column
    return None


def collect_database_snapshot(target: str, *, table_names: Iterable[str] | None = None) -> dict[str, Any]:
    engine = build_target_engine(target, purpose="direct")
    tables: list[dict[str, Any]] = []
    try:
        with engine.connect() as connection:
            for table in _sorted_tables(table_names):
                row_count = connection.scalar(select(func.count()).select_from(table)) or 0
                marker_column = _marker_column(table)
                marker_name = marker_column.name if marker_column is not None else None
                marker_value = None
                if marker_column is not None:
                    marker_value = connection.scalar(
                        select(marker_column).where(marker_column.is_not(None)).order_by(marker_column.desc()).limit(1)
                    )
                tables.append(
                    {
                        "table": table.name,
                        "row_count": int(row_count),
                        "content_digest": _table_content_digest(connection, table),
                        "marker_column": marker_name,
                        "marker_value": _serialize_marker_value(marker_value),
                    }
                )
    finally:
        engine.dispose()

    return {"target": target, "tables": tables}


def compare_database_targets(
    source_target: str = "local",
    target_target: str = "cloud",
    *,
    table_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    source_snapshot = collect_database_snapshot(source_target, table_names=table_names)
    target_snapshot = collect_database_snapshot(target_target, table_names=table_names)

    source_tables = {table["table"]: table for table in source_snapshot["tables"]}
    target_tables = {table["table"]: table for table in target_snapshot["tables"]}
    mismatches: list[dict[str, Any]] = []

    for table_name in sorted(set(source_tables) | set(target_tables)):
        source_table = source_tables.get(table_name)
        target_table = target_tables.get(table_name)
        if source_table == target_table:
            continue
        mismatches.append(
            {
                "table": table_name,
                "source": source_table,
                "target": target_table,
            }
        )

    return {
        "source": source_target,
        "target": target_target,
        "ok": not mismatches,
        "mismatches": mismatches,
        "source_snapshot": source_snapshot,
        "target_snapshot": target_snapshot,
    }
