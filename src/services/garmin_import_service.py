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

    _add_mirror_sync_results(results, include_mirror_sync=include_mirror_sync)

    return results


def _add_mirror_sync_results(results: dict[str, Any], *, include_mirror_sync: bool) -> None:
    if not include_mirror_sync:
        return

    shadow_import = sync_shadow_database()
    if shadow_import is not None:
        results["shadow_import"] = shadow_import
        results["shadow_parity"] = validate_shadow_parity()


def _shape_fetched_payload_results(import_results: dict[str, Any]) -> dict[str, Any]:
    raw_counts = dict(import_results.get("raw_import") or {})
    results: dict[str, Any] = {
        "activities": raw_counts.get("activities", 0),
        "splits": raw_counts.get("splits", 0),
        "swimming_lengths": raw_counts.get("swimming_lengths", 0),
        "user_snapshot": bool(import_results.get("user_snapshot_ids")),
    }
    if raw_counts:
        results["raw_import"] = raw_counts
    if import_results.get("processed_import"):
        results["processed_import"] = import_results["processed_import"]

    user_snapshot_ids = import_results.get("user_snapshot_ids") or []
    if user_snapshot_ids:
        results["user_snapshot_id"] = user_snapshot_ids[0]
        results["user_snapshot_ids"] = user_snapshot_ids

    return results


def import_fetched_garmin_payload(
    *,
    session: Any | None = None,
    user_id: Any | None = None,
    user_path: str | Path | None = None,
    raw_path: str | Path | None = None,
    include_mirror_sync: bool = True,
) -> dict[str, Any]:
    if session is None:
        with SessionLocal() as session:
            user = get_or_create_default_user(session)
            return import_fetched_garmin_payload(
                session=session,
                user_id=user.id,
                user_path=user_path,
                raw_path=raw_path,
                include_mirror_sync=include_mirror_sync,
            )
    if user_id is None:
        raise ValueError("user_id is required when passing an existing session")

    import_results = import_artifact_bundle(
        session,
        user_id,
        user_files=[user_path] if user_path else None,
        raw_file=raw_path,
    )
    session.commit()

    results = _shape_fetched_payload_results(import_results)
    _add_mirror_sync_results(results, include_mirror_sync=include_mirror_sync)
    return results


def import_fetched_raw_artifacts(user_path: Path, raw_path: Path) -> dict[str, Any]:
    results = import_fetched_garmin_payload(user_path=user_path, raw_path=raw_path)
    return {
        key: value
        for key, value in results.items()
        if key
        not in {
            "activities",
            "splits",
            "swimming_lengths",
            "user_snapshot",
            "user_snapshot_ids",
        }
    }
