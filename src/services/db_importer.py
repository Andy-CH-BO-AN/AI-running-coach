from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Activity
from src.db.repositories import (
    insert_user_profile_snapshot,
    save_activity_features,
    upsert_activity,
    upsert_activity_splits,
    upsert_swimming_lengths,
)

FILENAME_DATE_RE = re.compile(r"(\d{8})")


def _load_json_file(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def _infer_captured_at(path: str | Path) -> datetime:
    match = FILENAME_DATE_RE.search(Path(path).name)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


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

    counts = {"activities": 0, "splits": 0, "swimming_lengths": 0}
    for activity_data in activities:
        if not isinstance(activity_data, dict) or activity_data.get("activity_id") is None:
            continue

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
            activity = session.scalars(
                select(Activity).where(
                    Activity.user_id == user_id,
                    Activity.garmin_activity_id == int(float(activity_id)),
                )
            ).first()
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
