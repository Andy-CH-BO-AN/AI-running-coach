from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.sql.schema import Table

from src.db.sync_copy import _sorted_tables
from src.db.sync_targets import build_target_engine

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
    snapshot_collector: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if snapshot_collector is None:
        source_snapshot = collect_database_snapshot(source_target, table_names=table_names)
        target_snapshot = collect_database_snapshot(target_target, table_names=table_names)
    else:
        source_snapshot = snapshot_collector(source_target)
        target_snapshot = snapshot_collector(target_target)

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
