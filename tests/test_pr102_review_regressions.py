from __future__ import annotations

import json

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
from sqlalchemy import select

from src.db.models import Activity
from src.db.repositories import get_or_create_default_user
from src.services.db_importer import import_garmin_raw_file
from tests.db_test_utils import isolated_db_session


@pytest.fixture()
def db_session():
    yield from isolated_db_session()


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _strength_activity(*, sets: list[dict], load: int, include_failure_marker: bool = False) -> dict:
    raw_data = {
        "training_stress_score": load,
        "strength": {
            "total_sets": 2,
            "active_sets": 2 if sets else None,
            "total_reps": 18 if sets else None,
            "total_volume_kg": None,
            "sets": sets,
        },
        "strength_sets_available": bool(sets),
        "strength_raw_exercise_sets": sets,
    }
    if include_failure_marker:
        raw_data["strength_sets_fetch_failed"] = True
    if not sets:
        raw_data["strength_raw_summary"] = {
            "summaryDTO": {
                "activityTrainingLoad": load,
                "totalSets": 2,
                "totalReps": 18,
            }
        }
        raw_data["strength"].update({"total_sets": 2, "active_sets": 2, "total_reps": 18})
    return {
        "activity_id": 988,
        "type": "strength_training",
        "date": "2026-08-20",
        "distance": None,
        "duration": 45,
        "average_heart_rate": 121,
        "splits": [],
        "raw_data": raw_data,
    }


def test_empty_backfill_payload_without_failure_marker_preserves_existing_strength_sets(
    db_session,
    tmp_path,
) -> None:
    complete_sets = [
        {
            "set_index": 1,
            "set_type": "active",
            "exercise_names": ["Squat"],
            "category": None,
            "reps": 9,
            "weight_kg": None,
            "duration_sec": None,
        },
        {
            "set_index": 2,
            "set_type": "active",
            "exercise_names": ["Squat"],
            "category": None,
            "reps": 9,
            "weight_kg": None,
            "duration_sec": None,
        },
    ]
    complete_path = tmp_path / "complete.json"
    empty_backfill_path = tmp_path / "empty_backfill.json"
    _write_json(complete_path, [_strength_activity(sets=complete_sets, load=22)])
    _write_json(empty_backfill_path, [_strength_activity(sets=[], load=23)])
    user = get_or_create_default_user(db_session)

    first = import_garmin_raw_file(db_session, user.id, complete_path)
    second = import_garmin_raw_file(db_session, user.id, empty_backfill_path)

    assert first["activities"] == 1
    assert second["activities"] == 0
    activity = db_session.scalars(select(Activity)).one()
    assert activity.raw_json["raw_data"]["strength"]["sets"] == complete_sets
    assert activity.raw_json["raw_data"]["strength"]["total_reps"] == 18
    assert float(activity.training_stress_score) == 22


def test_first_seen_successful_empty_strength_payload_stays_successful_empty(db_session, tmp_path) -> None:
    empty_path = tmp_path / "first_seen_empty.json"
    _write_json(empty_path, [_strength_activity(sets=[], load=23)])
    user = get_or_create_default_user(db_session)

    counts = import_garmin_raw_file(db_session, user.id, empty_path)

    assert counts["activities"] == 1
    activity = db_session.scalars(select(Activity)).one()
    raw_data = activity.raw_json["raw_data"]
    assert raw_data["strength"]["sets"] == []
    assert raw_data["strength_sets_available"] is False
    assert "strength_sets_fetch_failed" not in raw_data
