import json
from contextlib import contextmanager
from datetime import date

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import func, select

from src.db.models import (
    Activity,
    ActivityFeature,
    ActivitySplit,
    LineNotification,
    SwimmingLength,
    UserProfileSnapshot,
)
from src.db.repositories import get_or_create_default_user
from src.services.db_importer import import_garmin_raw_file, import_garmin_user_file, import_processed_csv_file
from src.services.garmin_import_service import import_strength_backfill
from tests.db_test_utils import isolated_db_session


@pytest.fixture()
def db_session():
    yield from isolated_db_session()


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_importing_same_garmin_raw_file_twice_does_not_duplicate_activities(db_session, tmp_path):
    raw_path = tmp_path / "garmin_raw_20260510.json"
    _write_json(
        raw_path,
        [
            {
                "activity_id": 987,
                "type": "swimming",
                "date": "2026-05-10",
                "distance": 1.25,
                "duration": 30.0,
                "average_heart_rate": 145,
                "splits": [
                    {
                        "split_index": 1,
                        "distance": 0.3,
                        "duration": 7.2,
                        "pace": 2.4,
                        "lengths": [
                            {
                                "length_index": 1,
                                "distance": 25.0,
                                "duration": 35.8,
                                "swim_stroke": "BREASTSTROKE",
                                "strokes": 10,
                                "swolf": 46,
                                "avg_hr": 128,
                            }
                        ],
                    }
                ],
                "raw_data": {"avg_swolf": 47.0, "training_stress_score": 91.4},
            }
        ],
    )
    user = get_or_create_default_user(db_session)

    import_garmin_raw_file(db_session, user.id, raw_path)
    import_garmin_raw_file(db_session, user.id, raw_path)

    assert db_session.scalar(select(func.count()).select_from(Activity)) == 1
    assert db_session.scalar(select(func.count()).select_from(ActivitySplit)) == 1
    assert db_session.scalar(select(func.count()).select_from(SwimmingLength)) == 1
    activity = db_session.scalars(select(Activity)).one()
    assert activity.raw_json["raw_data"]["avg_swolf"] == 47.0


def test_strength_raw_payload_is_upserted_without_a_schema_migration(db_session, tmp_path):
    raw_path = tmp_path / "garmin_raw_strength_20260820.json"
    strength = {
        "total_sets": 3,
        "active_sets": 2,
        "total_reps": 18,
        "total_volume_kg": None,
        "sets": [{"set_index": 1, "set_type": "active", "exercise_names": [], "category": None, "reps": 9, "weight_kg": None, "duration_sec": None}],
    }
    _write_json(
        raw_path,
        [{
            "activity_id": 988,
            "type": "strength_training",
            "date": "2026-08-20",
            "distance": None,
            "duration": 45,
            "splits": [],
            "raw_data": {"training_stress_score": 22, "strength": strength},
        }],
    )
    user = get_or_create_default_user(db_session)

    import_garmin_raw_file(db_session, user.id, raw_path)
    import_garmin_raw_file(db_session, user.id, raw_path)

    activity = db_session.scalars(select(Activity)).one()
    assert activity.activity_type == "strength_training"
    assert activity.distance_km is None
    assert activity.raw_metrics["strength"] == strength
    assert activity.raw_json["raw_data"]["strength"] == strength


def test_strength_backfill_is_idempotent_seeds_old_activities_and_keeps_profile_snapshot(
    db_session,
    tmp_path,
    monkeypatch,
):
    profile_path = tmp_path / "garmin_user_20260101.json"
    raw_path = tmp_path / "garmin_raw_strength_20260820.json"
    _write_json(profile_path, {"vo2max_running": 53})
    _write_json(
        raw_path,
        [
            {
                "activity_id": activity_id,
                "type": "strength_training",
                "date": day,
                "duration": 45,
                "splits": [],
                "raw_data": {"strength": {"total_sets": 1, "active_sets": 1, "total_reps": 5, "total_volume_kg": None, "sets": []}},
            }
            for activity_id, day in [(1, "2026-07-01"), (2, "2026-08-04"), (3, "2026-08-10"), (4, "2026-08-18"), (5, "2026-08-19")]
        ],
    )
    user = get_or_create_default_user(db_session)
    import_garmin_user_file(db_session, user.id, profile_path)

    @contextmanager
    def session_local():
        yield db_session

    monkeypatch.setattr("src.services.garmin_import_service.SessionLocal", session_local)
    monkeypatch.setattr(
        "src.services.garmin_import_service.resolve_training_calendar_date",
        lambda: date(2026, 8, 20),
    )
    first = import_strength_backfill(
        user_path=tmp_path / "garmin_user_20260820.json",
        raw_path=raw_path,
        include_mirror_sync=False,
    )
    second = import_strength_backfill(
        user_path=tmp_path / "garmin_user_20260820.json",
        raw_path=raw_path,
        include_mirror_sync=False,
    )

    assert first["notification_baseline_seeded"] == 3  # activity 1/2 and sentinel
    assert first["notification_candidates_unseeded"] == 3
    assert second["notification_baseline_seeded"] == 0
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 5
    assert db_session.scalar(select(func.count()).select_from(LineNotification)) == 3
    snapshot = db_session.scalars(select(UserProfileSnapshot)).one()
    assert float(snapshot.vo2max_running) == 53


def test_import_garmin_user_file_preserves_raw_profile(db_session, tmp_path):
    user_path = tmp_path / "garmin_user_20260510.json"
    profile = {
        "max_heart_rate": 207,
        "resting_heart_rate": 47,
        "vo2max_running": 53,
        "pr_running": {"5km": "19:57 (3:59 /km)"},
    }
    _write_json(user_path, profile)
    user = get_or_create_default_user(db_session)

    import_garmin_user_file(db_session, user.id, user_path)

    snapshot = db_session.scalars(select(UserProfileSnapshot)).one()
    assert float(snapshot.vo2max_running) == 53.0
    assert snapshot.raw_profile == profile
    assert snapshot.captured_at.isoformat().startswith("2026-05-10")


def test_import_garmin_raw_file_skips_short_cycling_records(db_session, tmp_path):
    raw_path = tmp_path / "garmin_raw_20260510.json"
    _write_json(
        raw_path,
        [
            {
                "activity_id": 601,
                "type": "cycling",
                "date": "2026-05-10",
                "distance": "2.8",
                "duration": 12.0,
            },
            {
                "activity_id": 602,
                "type": "cycling",
                "date": "2026-05-11",
                "distance": 3.01,
                "duration": 12.0,
            },
        ],
    )
    user = get_or_create_default_user(db_session)

    counts = import_garmin_raw_file(db_session, user.id, raw_path)

    assert counts["activities"] == 1
    assert counts["skipped_short_cycling"] == 1
    activity = db_session.scalars(select(Activity)).one()
    assert activity.garmin_activity_id == 602


def test_import_processed_csv_persists_features_for_matching_activity(db_session, tmp_path):
    raw_path = tmp_path / "garmin_raw_20260510.json"
    _write_json(
        raw_path,
        [
            {
                "activity_id": 123,
                "type": "running",
                "date": "2026-05-10",
                "distance": 5.2,
                "duration": 26.0,
            }
        ],
    )
    csv_path = tmp_path / "processed_20260510.csv"
    csv_path.write_text(
        "activity_id,distance_km\n"
        "123.0,5.2\n"
        "999,8.1\n"
        ",1.0\n",
        encoding="utf-8",
    )
    user = get_or_create_default_user(db_session)
    import_garmin_raw_file(db_session, user.id, raw_path)

    counts = import_processed_csv_file(
        session=db_session,
        user_id=user.id,
        path=csv_path,
        feature_version="processed_csv:test",
    )

    assert counts == {"rows_seen": 3, "features_saved": 1, "missing_activities": 1}
    activity = db_session.scalars(
        select(Activity).where(Activity.garmin_activity_id == 123)
    ).one()
    feature = db_session.scalars(select(ActivityFeature)).one()
    assert feature.activity_id == activity.id
    assert feature.feature_version == "processed_csv:test"
    assert feature.algorithm_version == "csv-import"
    assert feature.features["processed_row"] == {
        "activity_id": "123.0",
        "distance_km": "5.2",
    }
    assert feature.features["source_file"] == str(csv_path)
