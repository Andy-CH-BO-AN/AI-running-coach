from __future__ import annotations

from typing import Any

from src.db.session import get_database_mode
from src.db.sync import compare_database_targets, sync_database_targets

MIRROR_TABLES = (
    "users",
    "activities",
    "user_profile_snapshots",
    "weekly_summaries",
    "activity_features",
    "activity_splits",
    "ai_reports",
    "swimming_lengths",
)


def mirror_mode_enabled() -> bool:
    return get_database_mode() == "mirror"


def sync_shadow_database() -> dict[str, Any] | None:
    if not mirror_mode_enabled():
        return None
    return sync_database_targets("local", "cloud", table_names=MIRROR_TABLES)


def validate_shadow_parity() -> dict[str, Any] | None:
    if not mirror_mode_enabled():
        return None
    return compare_database_targets("local", "cloud", table_names=MIRROR_TABLES)
