import uuid
from datetime import date, datetime, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.db.mappers import (
    map_activity_feature_values,
    map_activity_values,
    map_ai_report_values,
    map_swimming_length_values,
    map_user_profile_snapshot_values,
    map_weekly_summary_values,
)
from src.db.models import AIReport, Activity, ActivityFeature, ActivitySplit, SwimmingLength, User
from src.db.repositories import (
    get_activity_with_splits,
    get_latest_resting_heart_rate,
    get_latest_user_profile,
    get_or_create_default_user,
    get_profile_history,
    get_recent_activities,
    get_recent_max_heart_rate,
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


def test_activity_values_maps_running_payload_without_db_roundtrip(db_session):
    user = get_or_create_default_user(db_session)
    payload = {
        **_activity_payload(activity_id=401),
        "duration_sec": 3001,
        "max_heart_rate": 181,
        "average_power": 250,
        "raw_data": {
            "training_stress_score": 72.5,
            "power_avg": 245,
            "power_max": 420,
            "cadence": 176,
            "max_cadence": 188,
            "temperature": 31,
        },
    }

    values = map_activity_values(user.id, payload, source_file="raw.json")

    assert values["user_id"] == user.id
    assert values["garmin_activity_id"] == 401
    assert values["activity_type"] == "running"
    assert values["source_file"] == "raw.json"
    assert values["duration_min"] == 50.0
    assert values["duration_sec"] == 3001.0
    assert values["average_pace_min_per_km"] == 5.0
    assert values["average_speed_kmh"] is None
    assert values["average_power"] == 250.0
    assert values["max_power"] == 420.0
    assert values["raw_metrics"]["training_stress_score"] == 72.5
    assert values["raw_json"]["activity_id"] == 401


def test_activity_values_keeps_cycling_speed_out_of_pace_columns(db_session):
    user = get_or_create_default_user(db_session)
    payload = {
        "activity_id": 402,
        "type": "cycling",
        "date": "2026-05-10",
        "distance": 20.0,
        "duration": 60.0,
        "average_pace": 20.0,
        "raw_data": {"average_speed_kmh": 20.0},
    }

    values = map_activity_values(user.id, payload)

    assert values["average_pace_min_per_km"] is None
    assert values["average_speed_kmh"] == 20.0


def test_user_profile_snapshot_values_preserves_raw_profile_and_capture_time(db_session):
    user = get_or_create_default_user(db_session)
    captured_at = datetime(2026, 5, 14, 8, 0, tzinfo=timezone.utc)
    profile = {
        "max_heart_rate": "200",
        "resting_heart_rate": 48,
        "vo2max_running": 53,
        "available_training_days": ["MONDAY", "WEDNESDAY"],
        "pr_running": {"5km": "19:57 (3:59 /km)"},
    }

    values = map_user_profile_snapshot_values(
        user_id=user.id,
        profile_data=profile,
        captured_at=captured_at,
        source_file="garmin_user.json",
    )

    assert values["user_id"] == user.id
    assert values["captured_at"] == captured_at
    assert values["source_file"] == "garmin_user.json"
    assert values["max_heart_rate"] == 200.0
    assert values["available_training_days"] == ["MONDAY", "WEDNESDAY"]
    assert values["raw_profile"] == profile


def test_swimming_length_values_normalize_fields_without_db_roundtrip():
    split_id = uuid.uuid4()
    payload = {
        "distance": "25",
        "duration": "36.5",
        "swim_stroke": "FREESTYLE",
        "strokes": "18",
        "swolf": "54",
        "avg_hr": "132",
        "extra": datetime(2026, 5, 10, tzinfo=timezone.utc),
    }

    values = map_swimming_length_values(split_id, payload, offset=2)

    assert values["activity_split_id"] == split_id
    assert values["length_index"] == 2
    assert values["distance_m"] == 25.0
    assert values["duration_sec"] == 36.5
    assert values["strokes"] == 18
    assert values["raw_json"]["extra"] == "2026-05-10T00:00:00+00:00"
    assert values["updated_at"].tzinfo is not None


def test_activity_feature_values_jsonify_features_without_db_roundtrip():
    activity_id = uuid.uuid4()

    values = map_activity_feature_values(
        activity_id,
        "v1",
        {"computed_on": date(2026, 5, 10), "bad_number": float("nan")},
        algorithm_version="algo:v1",
    )

    assert values["activity_id"] == activity_id
    assert values["feature_version"] == "v1"
    assert values["algorithm_version"] == "algo:v1"
    assert values["features"] == {"computed_on": "2026-05-10", "bad_number": None}
    assert values["computed_at"].tzinfo is not None


def test_weekly_summary_values_keep_known_metrics_without_db_roundtrip():
    user_id = uuid.uuid4()

    values = map_weekly_summary_values(
        user_id,
        date(2026, 5, 4),
        date(2026, 5, 10),
        "weekly:v1",
        {"generated_at": datetime(2026, 5, 10, tzinfo=timezone.utc)},
        total_distance_km=42.2,
        workout_count=5,
        ignored_metric=999,
    )

    assert values["user_id"] == user_id
    assert values["summary_json"] == {"generated_at": "2026-05-10T00:00:00+00:00"}
    assert values["total_distance_km"] == 42.2
    assert values["workout_count"] == 5
    assert "ignored_metric" not in values
    assert values["training_load"] is None
    assert values["computed_at"].tzinfo is not None


def test_ai_report_values_jsonify_payloads_without_db_roundtrip():
    user_id = uuid.uuid4()
    activity_id = uuid.uuid4()

    values = map_ai_report_values(
        user_id,
        "activity",
        "report",
        {"generated_at": datetime(2026, 5, 10, tzinfo=timezone.utc)},
        model_name="gemini",
        prompt_version="coach:v1",
        activity_id=activity_id,
        report_json={"score": float("inf")},
        output_path="output/report.json",
    )

    assert values["user_id"] == user_id
    assert values["activity_id"] == activity_id
    assert values["model_name"] == "gemini"
    assert values["input_json"] == {"generated_at": "2026-05-10T00:00:00+00:00"}
    assert values["report_json"] == {"score": None}
    assert values["output_path"] == "output/report.json"


def test_upsert_activity_updates_by_garmin_activity_id(db_session):
    user = get_or_create_default_user(db_session)

    first = upsert_activity(db_session, user.id, _activity_payload(average_heart_rate=150))
    second = upsert_activity(db_session, user.id, _activity_payload(average_heart_rate=155))

    assert first.id == second.id
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 1
    assert float(second.average_heart_rate) == 155.0
    assert second.raw_json["raw_data"]["hr_zone_2"] == 1800


def test_activity_required_fields_are_enforced_and_rollback_keeps_db_clean(db_session):
    user = get_or_create_default_user(db_session)
    invalid_activity = Activity(
        user_id=user.id,
        garmin_activity_id=777,
        started_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        raw_json={"activity_id": 777},
    )

    db_session.add(invalid_activity)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_get_recent_activities_returns_multiple_records_sorted_newest_first(db_session):
    user = get_or_create_default_user(db_session)
    for activity_id, activity_date in (
        (501, "2026-05-08"),
        (502, "2026-05-10"),
        (503, "2026-05-09"),
    ):
        upsert_activity(
            db_session,
            user.id,
            {
                **_activity_payload(activity_id=activity_id),
                "date": activity_date,
            },
        )

    activities = get_recent_activities(db_session, user.id, limit=2)

    assert [activity.garmin_activity_id for activity in activities] == [502, 503]


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


def test_activity_delete_cascades_children_and_preserves_ai_report_with_null_activity(db_session):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(db_session, user.id, _activity_payload())
    split = upsert_activity_splits(
        db_session,
        activity.id,
        [{"split_index": 1, "distance": 1.0, "duration": 5.0, "pace": 5.0}],
    )[0]
    upsert_swimming_lengths(db_session, split.id, [{"length_index": 1, "distance": 25.0, "duration": 35.0}])
    save_activity_features(db_session, activity.id, "v1", {"classification": {"workout_type": "easy"}})
    report = save_ai_report(
        db_session,
        user.id,
        report_scope="activity",
        report_text="report",
        input_json={"activity_id": 123},
        activity_id=activity.id,
    )

    db_session.delete(activity)
    db_session.flush()

    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    assert db_session.scalar(select(func.count()).select_from(ActivitySplit)) == 0
    assert db_session.scalar(select(func.count()).select_from(SwimmingLength)) == 0
    assert db_session.scalar(select(func.count()).select_from(ActivityFeature)) == 0
    db_session.refresh(report)
    assert report.activity_id is None


def test_user_delete_cascades_profile_activities_and_ai_reports(db_session):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(db_session, user.id, _activity_payload())
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {"resting_heart_rate": 48},
        datetime(2026, 5, 10, tzinfo=timezone.utc),
    )
    save_ai_report(
        db_session,
        user.id,
        report_scope="activity",
        report_text="report",
        input_json={"activity_id": 123},
        activity_id=activity.id,
    )

    db_session.delete(user)
    db_session.flush()

    assert db_session.scalar(select(func.count()).select_from(User)) == 0
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
    assert db_session.scalar(select(func.count()).select_from(AIReport)) == 0


def test_cycling_speed_values_are_persisted_without_polluting_pace_columns(db_session):
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
    assert float(activity.average_speed_kmh) == 20.0
    assert float(split.speed_kmh) == 20.0
    assert split.raw_json["pace"] == 20.0


def test_get_activity_with_splits_reads_nested_swimming_lengths(db_session):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(db_session, user.id, _activity_payload())
    split = upsert_activity_splits(
        db_session,
        activity.id,
        [{"split_index": 1, "distance": 1.0, "duration": 5.0, "pace": 5.0}],
    )[0]
    upsert_swimming_lengths(db_session, split.id, [{"length_index": 1, "distance": 25.0, "duration": 35.0}])

    loaded = get_activity_with_splits(db_session, activity.id)

    assert loaded.id == activity.id
    assert len(loaded.splits) == 1
    assert len(loaded.splits[0].swimming_lengths) == 1


def test_profile_snapshots_preserve_daily_vo2max_and_lactate_threshold_history(db_session):
    user = get_or_create_default_user(db_session)
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {
            "vo2max_running": 53,
            "lactate_threshold_pace": "04:24/km",
            "lactate_threshold_heart_rate": 191,
            "max_heart_rate": 200,
        },
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {
            "vo2max_running": 56,
            "lactate_threshold_pace": "04:18/km",
            "lactate_threshold_heart_rate": 193,
            "max_heart_rate": 202,
        },
        datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    history = get_profile_history(db_session, user.id)
    latest = get_latest_user_profile(db_session, user.id)

    assert len(history) == 2
    assert float(history[0].vo2max_running) == 53.0
    assert history[0].lactate_threshold_pace == "04:24/km"
    assert float(history[1].lactate_threshold_heart_rate) == 193.0
    assert float(latest.vo2max_running) == 56.0
    assert latest.lactate_threshold_pace == "04:18/km"
    assert latest.raw_profile["max_heart_rate"] == 202


def test_get_latest_resting_heart_rate_uses_most_recent_non_null_snapshot(db_session):
    user = get_or_create_default_user(db_session)
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {"resting_heart_rate": 48},
        datetime(2026, 5, 10, tzinfo=timezone.utc),
    )
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {"resting_heart_rate": None},
        datetime(2026, 5, 11, tzinfo=timezone.utc),
    )
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {"resting_heart_rate": 51},
        datetime(2026, 5, 12, tzinfo=timezone.utc),
    )

    assert get_latest_resting_heart_rate(db_session, user.id) == 51.0


def test_profile_snapshot_upsert_keeps_smaller_same_day_resting_heart_rate(db_session):
    user = get_or_create_default_user(db_session)
    captured_at = datetime(2026, 5, 10, tzinfo=timezone.utc)
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {"resting_heart_rate": 52},
        captured_at,
    )
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {"resting_heart_rate": 48},
        captured_at,
    )
    insert_user_profile_snapshot(
        db_session,
        user.id,
        {"resting_heart_rate": None},
        captured_at,
    )

    latest = get_latest_user_profile(db_session, user.id)
    assert float(latest.resting_heart_rate) == 48.0


def test_get_recent_max_heart_rate_only_uses_recent_half_year_activities(db_session):
    user = get_or_create_default_user(db_session)
    upsert_activity(
        db_session,
        user.id,
        {
            **_activity_payload(activity_id=201),
            "date": "2025-10-01",
            "max_heart_rate": 205,
        },
    )
    upsert_activity(
        db_session,
        user.id,
        {
            **_activity_payload(activity_id=202),
            "date": "2026-05-01",
            "max_heart_rate": 188,
        },
    )
    upsert_activity(
        db_session,
        user.id,
        {
            **_activity_payload(activity_id=203),
            "date": "2026-05-10",
            "max_heart_rate": 192,
        },
    )
    upsert_activity(
        db_session,
        user.id,
        {
            **_activity_payload(activity_id=204),
            "date": "2026-05-20",
            "max_heart_rate": 210,
        },
    )

    result = get_recent_max_heart_rate(
        db_session,
        user.id,
        as_of_date=datetime(2026, 5, 13, tzinfo=timezone.utc).date(),
    )

    assert result == 192.0


def test_get_recent_max_heart_rate_falls_back_to_splits_when_activity_max_is_missing(db_session):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(
        db_session,
        user.id,
        {
            **_activity_payload(activity_id=301),
            "date": "2026-05-10",
        },
    )
    upsert_activity_splits(
        db_session,
        activity.id,
        [
            {
                "split_index": 1,
                "distance": 1.0,
                "duration": 5.0,
                "pace": 5.0,
                "max_heart_rate": 186,
            },
            {
                "split_index": 2,
                "distance": 1.0,
                "duration": 5.0,
                "pace": 5.0,
                "max_heart_rate": 194,
            },
        ],
    )

    result = get_recent_max_heart_rate(
        db_session,
        user.id,
        as_of_date=datetime(2026, 5, 13, tzinfo=timezone.utc).date(),
    )

    assert result == 194.0


def test_upsert_activity_derives_max_heart_rate_from_splits(db_session):
    user = get_or_create_default_user(db_session)

    activity = upsert_activity(
        db_session,
        user.id,
        {
            **_activity_payload(activity_id=302),
            "splits": [
                {"split_index": 1, "distance": 1.0, "duration": 5.0, "pace": 5.0, "max_heart_rate": 181},
                {"split_index": 2, "distance": 1.0, "duration": 5.0, "pace": 5.0, "max_heart_rate": 193},
            ],
        },
    )

    assert float(activity.max_heart_rate) == 193.0


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
