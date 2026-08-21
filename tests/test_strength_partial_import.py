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


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _strength_payload(*, failed: bool, sets: list[dict], total_reps: int | None, load: int):
    return {
        "activity_id": 988,
        "type": "strength_training",
        "date": "2026-08-20",
        "distance": None,
        "duration": 45,
        "average_heart_rate": 121,
        "splits": [],
        "raw_data": {
            "training_stress_score": load,
            "strength": {
                "total_sets": 2,
                "active_sets": 2 if sets else None,
                "total_reps": total_reps,
                "total_volume_kg": None,
                "sets": sets,
            },
            "strength_sets_available": bool(sets),
            "strength_sets_fetch_failed": failed,
            "strength_raw_exercise_sets": sets,
        },
    }


def _strength_summary_failure_payload():
    return {
        "activity_id": 988,
        "type": "strength_training",
        "date": "2026-08-20",
        "distance": None,
        "duration": 45,
        "average_heart_rate": 121,
        "splits": [],
        "raw_data": {},
    }


def _summary_success_sets_failure_payload(*, load: int = 31):
    payload = _strength_payload(failed=True, sets=[], total_reps=24, load=load)
    raw_data = payload["raw_data"]
    raw_data["aerobic_training_effect"] = 2.3
    raw_data["anaerobic_training_effect"] = 0.7
    raw_data["strength"].update({"total_sets": 4, "active_sets": 4})
    raw_data["strength_raw_summary"] = {
        "summaryDTO": {
            "activityTrainingLoad": load,
            "aerobicTrainingEffect": 2.3,
            "anaerobicTrainingEffect": 0.7,
            "totalSets": 4,
            "totalReps": 24,
        }
    }
    return payload


def test_transient_strength_set_failure_preserves_sets_and_applies_corrected_summary(db_session, tmp_path):
    complete_path = tmp_path / "garmin_raw_strength_complete.json"
    partial_path = tmp_path / "garmin_raw_strength_partial.json"
    complete_sets = [
        {"set_index": 1, "set_type": "active", "exercise_names": ["Squat"], "category": None, "reps": 9, "weight_kg": None, "duration_sec": None},
        {"set_index": 2, "set_type": "active", "exercise_names": ["Squat"], "category": None, "reps": 9, "weight_kg": None, "duration_sec": None},
    ]
    _write_json(complete_path, [_strength_payload(failed=False, sets=complete_sets, total_reps=18, load=20)])
    corrected = _summary_success_sets_failure_payload(load=35)
    _write_json(partial_path, [corrected])
    user = get_or_create_default_user(db_session)

    first = import_garmin_raw_file(db_session, user.id, complete_path)
    second = import_garmin_raw_file(db_session, user.id, partial_path)
    third = import_garmin_raw_file(db_session, user.id, partial_path)

    assert first["activities"] == 1
    assert second["activities"] == 1
    assert third["activities"] == 0
    activity = db_session.scalars(select(Activity)).one()
    raw_data = activity.raw_json["raw_data"]
    assert raw_data["strength"]["sets"] == complete_sets
    assert raw_data["strength_raw_exercise_sets"] == complete_sets
    assert raw_data["strength"]["total_reps"] == 24
    assert raw_data["strength_raw_summary"]["summaryDTO"]["activityTrainingLoad"] == 35
    assert float(activity.training_stress_score) == 35


def test_transient_strength_summary_failure_does_not_replace_existing_complete_activity(db_session, tmp_path):
    complete_path = tmp_path / "garmin_raw_strength_complete.json"
    partial_path = tmp_path / "garmin_raw_strength_summary_failed.json"
    complete_sets = [
        {"set_index": 1, "set_type": "active", "exercise_names": ["Squat"], "category": None, "reps": 9, "weight_kg": None, "duration_sec": None},
        {"set_index": 2, "set_type": "active", "exercise_names": ["Squat"], "category": None, "reps": 9, "weight_kg": None, "duration_sec": None},
    ]
    _write_json(complete_path, [_strength_payload(failed=False, sets=complete_sets, total_reps=18, load=22)])
    _write_json(partial_path, [_strength_summary_failure_payload()])
    user = get_or_create_default_user(db_session)

    import_garmin_raw_file(db_session, user.id, complete_path)
    second = import_garmin_raw_file(db_session, user.id, partial_path)

    assert second["activities"] == 0
    activity = db_session.scalars(select(Activity)).one()
    assert activity.raw_json["raw_data"]["strength"]["sets"] == complete_sets
    assert activity.raw_json["raw_data"]["strength"]["total_reps"] == 18
    assert float(activity.training_stress_score) == 22


def test_existing_partial_strength_activity_is_enriched_by_new_summary_facts(db_session, tmp_path):
    failed_path = tmp_path / "garmin_raw_strength_summary_failed.json"
    enriched_path = tmp_path / "garmin_raw_strength_summary_recovered.json"
    _write_json(failed_path, [_strength_summary_failure_payload()])
    _write_json(enriched_path, [_summary_success_sets_failure_payload()])
    user = get_or_create_default_user(db_session)

    first = import_garmin_raw_file(db_session, user.id, failed_path)
    second = import_garmin_raw_file(db_session, user.id, enriched_path)

    assert first["activities"] == 1
    assert second["activities"] == 1
    activity = db_session.scalars(select(Activity)).one()
    raw_data = activity.raw_json["raw_data"]
    assert float(activity.training_stress_score) == 31
    assert raw_data["aerobic_training_effect"] == 2.3
    assert raw_data["anaerobic_training_effect"] == 0.7
    assert raw_data["strength"]["total_sets"] == 4
    assert raw_data["strength"]["total_reps"] == 24
    assert raw_data["strength"]["sets"] == []
    assert raw_data["strength_sets_fetch_failed"] is True


def test_first_seen_partial_strength_activity_is_still_inserted(db_session, tmp_path):
    partial_path = tmp_path / "garmin_raw_strength_partial.json"
    _write_json(partial_path, [_strength_payload(failed=True, sets=[], total_reps=None, load=23)])
    user = get_or_create_default_user(db_session)

    counts = import_garmin_raw_file(db_session, user.id, partial_path)

    assert counts["activities"] == 1
    activity = db_session.scalars(select(Activity)).one()
    assert activity.raw_json["raw_data"]["strength_sets_fetch_failed"] is True
    assert activity.raw_json["raw_data"]["strength"]["sets"] == []


def test_first_seen_strength_summary_failure_is_still_inserted_as_partial(db_session, tmp_path):
    partial_path = tmp_path / "garmin_raw_strength_summary_failed.json"
    _write_json(partial_path, [_strength_summary_failure_payload()])
    user = get_or_create_default_user(db_session)

    counts = import_garmin_raw_file(db_session, user.id, partial_path)

    assert counts["activities"] == 1
    activity = db_session.scalars(select(Activity)).one()
    assert activity.raw_json["raw_data"] == {}
    assert activity.distance_km is None
    assert activity.duration_min == 45
