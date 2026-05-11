from datetime import datetime, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import func, select

from src.db.models import AIReport, Activity, ActivityFeature, ActivitySplit, SwimmingLength
from src.db.repositories import (
    get_latest_user_profile,
    get_or_create_default_user,
    get_profile_history,
    insert_user_profile_snapshot,
    save_activity_features,
    save_ai_report,
    upsert_activity,
    upsert_activity_splits,
    upsert_swimming_lengths,
)
from tests.db_test_utils import isolated_db_session


@pytest.fixture()
def db_session():
    yield from isolated_db_session()


def _activity_payload(activity_id=123, average_heart_rate=150):
    return {
        "activity_id": activity_id,
        "type": "running",
        "date": "2026-05-10",
        "distance": 10.0,
        "duration": 50.0,
        "average_pace": 5.0,
        "average_heart_rate": average_heart_rate,
        "raw_data": {
            "training_stress_score": 72.5,
            "power_avg": 245,
            "power_max": 420,
            "hr_zone_2": 1800,
        },
    }


def test_upsert_activity_updates_by_garmin_activity_id(db_session):
    user = get_or_create_default_user(db_session)

    first = upsert_activity(db_session, user.id, _activity_payload(average_heart_rate=150))
    second = upsert_activity(db_session, user.id, _activity_payload(average_heart_rate=155))

    assert first.id == second.id
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 1
    assert float(second.average_heart_rate) == 155.0
    assert second.raw_json["raw_data"]["hr_zone_2"] == 1800


def test_activity_splits_and_swimming_lengths_are_idempotent(db_session):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(db_session, user.id, _activity_payload())
    splits = [
        {
            "split_index": 1,
            "distance": 0.3,
            "duration": 7.2,
            "pace": 2.4,
            "average_heart_rate": 130,
            "lengths": [{"length_index": 1, "distance": 25.0, "duration": 35.0, "swim_stroke": "FREESTYLE"}],
        }
    ]

    first_split = upsert_activity_splits(db_session, activity.id, splits)[0]
    second_split = upsert_activity_splits(db_session, activity.id, [{**splits[0], "average_heart_rate": 132}])[0]
    upsert_swimming_lengths(db_session, first_split.id, splits[0]["lengths"])
    upsert_swimming_lengths(db_session, second_split.id, [{**splits[0]["lengths"][0], "duration": 36.0}])

    assert first_split.id == second_split.id
    assert db_session.scalar(select(func.count()).select_from(ActivitySplit)) == 1
    assert db_session.scalar(select(func.count()).select_from(SwimmingLength)) == 1
    length = db_session.scalars(select(SwimmingLength)).one()
    assert float(length.duration_sec) == 36.0


def test_cycling_pace_values_are_not_persisted_to_min_per_km_columns(db_session):
    user = get_or_create_default_user(db_session)
    cycling_payload = {
        "activity_id": 456,
        "type": "cycling",
        "date": "2026-05-10",
        "distance": 20.0,
        "duration": 60.0,
        "average_pace": 20.0,
        "raw_data": {"average_speed_kmh": 20.0},
    }

    activity = upsert_activity(db_session, user.id, cycling_payload)
    split = upsert_activity_splits(
        db_session,
        activity.id,
        [{"split_index": 1, "distance": 10.0, "duration": 30.0, "pace": 20.0}],
    )[0]

    assert activity.average_pace_min_per_km is None
    assert split.pace_min_per_km is None
    assert split.raw_json["pace"] == 20.0


def test_profile_snapshots_preserve_vo2max_history(db_session):
    user = get_or_create_default_user(db_session)
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {"vo2max_running": 53, "max_heart_rate": 200},
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {"vo2max_running": 56, "max_heart_rate": 202},
        datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    history = get_profile_history(db_session, user.id)
    latest = get_latest_user_profile(db_session, user.id)

    assert len(history) == 2
    assert float(history[0].vo2max_running) == 53.0
    assert float(latest.vo2max_running) == 56.0
    assert latest.raw_profile["max_heart_rate"] == 202


def test_activity_features_allow_multiple_versions(db_session):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(db_session, user.id, _activity_payload())

    save_activity_features(db_session, activity.id, "v1", {"classification": {"workout_type": "easy"}})
    save_activity_features(db_session, activity.id, "v2", {"classification": {"workout_type": "tempo"}})

    assert db_session.scalar(select(func.count()).select_from(ActivityFeature)) == 2


def test_ai_reports_allow_multiple_model_prompt_rows_for_same_activity(db_session):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(db_session, user.id, _activity_payload())

    save_ai_report(
        db_session,
        user.id,
        report_scope="activity",
        report_text="report one",
        input_json={"activity_id": 123},
        model_name="gemini-1",
        prompt_version="coach:v1",
        activity_id=activity.id,
    )
    save_ai_report(
        db_session,
        user.id,
        report_scope="activity",
        report_text="report two",
        input_json={"activity_id": 123},
        model_name="gemini-2",
        prompt_version="coach:v2",
        activity_id=activity.id,
    )

    assert db_session.scalar(select(func.count()).select_from(AIReport)) == 2
