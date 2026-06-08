from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.db.sync_compare import (
    SNAPSHOT_MARKER_COLUMNS,
    _marker_column,
    _serialize_marker_value,
    _table_content_digest,
    collect_database_snapshot,
    compare_database_targets as _compare_database_targets,
)
from src.db.sync_copy import (
    DEFAULT_SYNC_BATCH_SIZE,
    LOGICAL_KEY_COLUMNS,
    _assert_no_logical_key_conflicts,
    _batched_rows,
    _find_logical_key_conflicts as _copy_find_logical_key_conflicts,
    _sorted_tables,
    _upsert_rows,
    sync_database_targets as _sync_database_targets,
)


def _find_logical_key_conflicts(
    source_rows: Iterable[dict[str, Any]],
    target_rows: Iterable[dict[str, Any]],
    *,
    logical_key_columns: tuple[str, ...],
    primary_key_columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    return _copy_find_logical_key_conflicts(
        source_rows,
        target_rows,
        logical_key_columns=logical_key_columns,
        primary_key_columns=primary_key_columns,
    )


def sync_database_targets(
    source_target: str = "local",
    target_target: str = "cloud",
    *,
    batch_size: int = DEFAULT_SYNC_BATCH_SIZE,
    table_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    return _sync_database_targets(
        source_target,
        target_target,
        batch_size=batch_size,
        table_names=table_names,
    )


def compare_database_targets(
    source_target: str = "local",
    target_target: str = "cloud",
    *,
    table_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    return _compare_database_targets(
        source_target,
        target_target,
        table_names=table_names,
        snapshot_collector=lambda target: collect_database_snapshot(target, table_names=table_names),
    )
