from __future__ import annotations

from pathlib import Path
from typing import Any

from src.db.mirror import sync_shadow_database, validate_shadow_parity
from src.db.repositories import get_or_create_default_user
from src.db.session import SessionLocal
from src.services.db_importer import import_artifact_bundle


def import_garmin_artifacts(
    *,
    user_files: list[str | Path] | None = None,
    raw_file: str | Path | None = None,
    processed_file: str | Path | None = None,
    include_mirror_sync: bool = True,
) -> dict[str, Any]:
    with SessionLocal() as session:
        user = get_or_create_default_user(session)
        results = import_artifact_bundle(
            session,
            user.id,
            user_files=user_files,
            raw_file=raw_file,
            processed_file=processed_file,
        )
        session.commit()

    if include_mirror_sync:
        shadow_import = sync_shadow_database()
        if shadow_import is not None:
            results["shadow_import"] = shadow_import
            results["shadow_parity"] = validate_shadow_parity()

    return results


def import_fetched_raw_artifacts(user_path: Path, raw_path: Path) -> dict[str, Any]:
    results = import_garmin_artifacts(user_files=[user_path], raw_file=raw_path)
    user_snapshot_ids = results.pop("user_snapshot_ids", [])
    if user_snapshot_ids:
        results["user_snapshot_id"] = user_snapshot_ids[0]
    return results
