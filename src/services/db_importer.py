from __future__ import annotations

import csv
from copy import deepcopy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy.orm import Session

from src.db.repositories import (
    find_activity_by_garmin_id,
    insert_user_profile_snapshot,
    save_activity_features,
    upsert_activity,
    upsert_activity_splits,
    upsert_swimming_lengths,
)
from src.preprocessing.activity_policy import should_skip_short_cycling

FILENAME_DATE_RE = re.compile(r"(\d{8})")


def _load_json_file(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def _infer_captured_at(path: str | Path) -> datetime:
    match = FILENAME_DATE_RE.search(Path(path).name)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _strength_detail_fact_count(raw_data: Mapping[str, Any]) -> int:
    count = sum(
        raw_data.get(key) is not None
        for key in (
            "training_stress_score",
            "aerobic_training_effect",
            "anaerobic_training_effect",
        )
    )
    strength = raw_data.get("strength")
    if isinstance(strength, Mapping):
        count += sum(
            strength.get(key) is not None
            for key in ("total_sets", "active_sets", "total_reps", "total_volume_kg")
        )
        count += int(bool(strength.get("sets")))
    count += int(bool(raw_data.get("strength_raw_summary")))
    count += int(bool(raw_data.get("strength_raw_exercise_sets")))
    return count


def _merge_partial_strength_activity(
    existing_raw_json: Any,
    incoming: dict[str, Any],
) -> dict[str, Any] | None:
    """Monotonically enrich strength facts without replacing known facts with gaps."""
    if not isinstance(existing_raw_json, Mapping):
        return incoming

    existing_raw = existing_raw_json.get("raw_data") or existing_raw_json.get("raw_metrics") or {}
    incoming_raw = incoming.get("raw_data") or incoming.get("raw_metrics") or {}
    if not isinstance(existing_raw, Mapping) or not isinstance(incoming_raw, Mapping):
        return incoming

    # A summary/detail failure contributes no new deterministic facts. Preserve
    # any existing row exactly; first-seen failures are handled by the caller.
    if not incoming_raw:
        return None

    existing_raw_dict = dict(existing_raw)
    merged_raw = deepcopy(existing_raw_dict)

    # Overlay new non-null summary facts, while never replacing known values
    # with null/empty retry artifacts.
    for key, value in incoming_raw.items():
        if key in {"strength", "strength_raw_exercise_sets"}:
            continue
        if value is not None:
            merged_raw[key] = deepcopy(value)

    existing_strength = existing_raw_dict.get("strength")
    incoming_strength = incoming_raw.get("strength")
    if isinstance(existing_strength, Mapping) or isinstance(incoming_strength, Mapping):
        merged_strength = (
            deepcopy(dict(existing_strength))
            if isinstance(existing_strength, Mapping)
            else {}
        )
        if isinstance(incoming_strength, Mapping):
            for key, value in incoming_strength.items():
                if key == "sets":
                    if value:
                        merged_strength[key] = deepcopy(value)
                elif value is not None:
                    merged_strength[key] = deepcopy(value)
        merged_raw["strength"] = merged_strength

    incoming_sets = incoming_raw.get("strength_raw_exercise_sets")
    if incoming_sets:
        merged_raw["strength_raw_exercise_sets"] = deepcopy(incoming_sets)
    elif existing_raw_dict.get("strength_raw_exercise_sets"):
        merged_raw["strength_raw_exercise_sets"] = deepcopy(
            existing_raw_dict["strength_raw_exercise_sets"]
        )

    if (
        existing_raw_dict.get("strength_sets_available") is True
        and not incoming_raw.get("strength_raw_exercise_sets")
    ):
        merged_raw["strength_sets_available"] = True

    # Do not rewrite a complete row only because a retry failed. An upsert is
    # useful only when the merged payload contains strictly more known facts.
    if _strength_detail_fact_count(merged_raw) <= _strength_detail_fact_count(existing_raw_dict):
        return None

    merged = deepcopy(dict(existing_raw_json))
    for key, value in incoming.items():
        if key in {"raw_data", "raw_metrics"}:
            continue
        if value is not None:
            merged[key] = deepcopy(value)
    merged["raw_data"] = merged_raw
    merged.pop("raw_metrics", None)
    return merged


def import_garmin_user_file(session: Session, user_id, path: str | Path):
    profile_data = _load_json_file(path)
    if not isinstance(profile_data, dict):
        raise ValueError(f"Expected Garmin user JSON object in {path}")
    return insert_user_profile_snapshot(
        session=session,
        user_id=user_id,
        profile_data=profile_data,
        captured_at=_infer_captured_at(path),
        source_file=str(path),
    )


def import_garmin_raw_file(session: Session, user_id, path: str | Path) -> dict[str, int]:
    activities = _load_json_file(path)
    if not isinstance(activities, list):
        raise ValueError(f"Expected Garmin raw JSON list in {path}")

    counts = {"activities": 0, "splits": 0, "swimming_lengths": 0, "skipped_short_cycling": 0}
    for activity_data in activities:
        if not isinstance(activity_data, dict) or activity_data.get("activity_id") is None:
            continue

        activity_type = activity_data.get("type") or activity_data.get("activity_type")
        distance_km = activity_data.get("distance")
        if distance_km is None:
            distance_km = activity_data.get("distance_km")
        if should_skip_short_cycling(activity_type, distance_km):
            counts["skipped_short_cycling"] += 1
            continue

        raw_data = activity_data.get("raw_data") or activity_data.get("raw_metrics") or {}
        # Missing set details must use the monotonic merge path even when the
        # all-history fetch tolerated a 404 without a transient-failure marker.
        # A successful-empty first observation is still inserted; this only
        # prevents a later incomplete payload from erasing already-known sets.
        strength_detail_partial = (
            activity_type == "strength_training"
            and isinstance(raw_data, dict)
            and (
                raw_data.get("strength_sets_fetch_failed") is True
                or not raw_data
                or raw_data.get("strength_sets_available") is False
            )
        )
        if strength_detail_partial:
            existing = find_activity_by_garmin_id(
                session,
                user_id=user_id,
                garmin_activity_id=int(activity_data["activity_id"]),
            )
            if existing is not None:
                merged_activity_data = _merge_partial_strength_activity(
                    existing.raw_json,
                    activity_data,
                )
                if merged_activity_data is None:
                    continue
                activity_data = merged_activity_data

        activity = upsert_activity(session, user_id=user_id, activity_data=activity_data, source_file=str(path))
        counts["activities"] += 1

        split_models = upsert_activity_splits(
            session,
            activity_id=activity.id,
            splits=activity_data.get("splits") or [],
            activity_type=activity.activity_type,
        )
        counts["splits"] += len(split_models)
        split_by_index = {split.split_index: split for split in split_models}

        for split_data in activity_data.get("splits") or []:
            split_model = split_by_index.get(split_data.get("split_index"))
            if not split_model:
                continue
            length_models = upsert_swimming_lengths(
                session,
                activity_split_id=split_model.id,
                lengths=split_data.get("lengths") or [],
            )
            counts["swimming_lengths"] += len(length_models)

    return counts


def import_processed_csv_file(
    session: Session,
    user_id,
    path: str | Path,
    feature_version: str = "processed_csv:v1",
) -> dict[str, int]:
    counts = {"rows_seen": 0, "features_saved": 0, "missing_activities": 0}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        for row in reader:
            counts["rows_seen"] += 1
            activity_id = row.get("activity_id")
            if not activity_id:
                continue
            activity = find_activity_by_garmin_id(
                session,
                user_id=user_id,
                garmin_activity_id=int(float(activity_id)),
            )
            if not activity:
                counts["missing_activities"] += 1
                continue
            save_activity_features(
                session,
                activity_id=activity.id,
                feature_version=feature_version,
                algorithm_version="csv-import",
                features={"processed_row": row, "source_file": str(path)},
            )
            counts["features_saved"] += 1
    return counts


def import_artifact_bundle(
    session: Session,
    user_id,
    *,
    user_files: list[str | Path] | None = None,
    raw_file: str | Path | None = None,
    processed_file: str | Path | None = None,
    feature_version: str = "processed_csv:v1",
) -> dict[str, Any]:
    results: dict[str, Any] = {}

    if user_files:
        snapshot_ids = []
        for user_file in user_files:
            snapshot = import_garmin_user_file(session, user_id, user_file)
            snapshot_ids.append(str(snapshot.id))
        results["user_snapshot_ids"] = snapshot_ids

    if raw_file:
        results["raw_import"] = import_garmin_raw_file(session, user_id, raw_file)

    if processed_file:
        results["processed_import"] = import_processed_csv_file(
            session,
            user_id,
            processed_file,
            feature_version=feature_version,
        )

    return results
