import uuid
from contextlib import contextmanager
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
from src.db.models import (
    AIReport,
    Activity,
    ActivityFeature,
    ActivitySplit,
    LineNotification,
    SwimmingLength,
    User,
)
from src.db.repositories import (
    SYSTEM_INITIALIZED_MARKER_ID,
    get_activity_with_splits,
    get_ai_report_by_idempotency_key,
    get_latest_resting_heart_rate,
    get_latest_user_profile,
    get_notified_activity_ids,
    get_or_create_default_user,
    get_profile_history,
    get_recent_activities,
    get_recent_max_heart_rate,
    insert_user_profile_snapshot,
    is_notification_system_initialized,
    list_pending_activity_notifications,
    list_pending_weekly_notifications,
    mark_notification_sent,
    prepare_activity_notification,
    prepare_weekly_notification,
    record_notification,
    save_activity_features,
    save_ai_report,
    save_weekly_summary,
    seed_baseline_notifications,
    upsert_activity,
    upsert_activity_splits,
    upsert_swimming_lengths,
    upsert_user,
)
from src.services.ai_report_resolution import (
    AIReportDraft,
    AIReportSpec,
    ActivityAINotificationPreparer,
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
        idempotency_key="activity:123:coach:v1:input-a",
        model_name="gemini",
        prompt_version="coach:v1",
        activity_id=activity_id,
        report_json={"score": float("inf")},
        output_path="output/report.json",
    )

    assert values["user_id"] == user_id
    assert values["idempotency_key"] == "activity:123:coach:v1:input-a"
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
        idempotency_key="activity:123:delete-test",
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
        idempotency_key="activity:123:user-delete-test",
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


def test_ai_reports_allow_multiple_logical_versions_for_same_activity(db_session):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(db_session, user.id, _activity_payload())

    save_ai_report(
        db_session,
        user.id,
        idempotency_key="activity:123:feature-v1:coach-v1:input-a",
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
        idempotency_key="activity:123:feature-v1:coach-v2:input-a",
        report_scope="activity",
        report_text="report two",
        input_json={"activity_id": 123},
        model_name="gemini-2",
        prompt_version="coach:v2",
        activity_id=activity.id,
    )

    assert db_session.scalar(select(func.count()).select_from(AIReport)) == 2


def test_ai_report_conflict_returns_canonical_persisted_row(db_session):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(db_session, user.id, _activity_payload())
    key = "activity:123:feature-v1:coach-v1:input-a"

    winner = save_ai_report(
        db_session,
        user.id,
        idempotency_key=key,
        report_scope="activity",
        report_text="canonical report",
        input_json={"activity_id": 123},
        model_name="canonical-model",
        prompt_version="coach:v1",
        activity_id=activity.id,
        report_json={"analysis": "canonical"},
    )
    conflict_result = save_ai_report(
        db_session,
        user.id,
        idempotency_key=key,
        report_scope="activity",
        report_text="losing draft",
        input_json={"activity_id": 123},
        model_name="losing-model",
        prompt_version="coach:v1",
        activity_id=activity.id,
        report_json={"analysis": "loser"},
    )

    assert conflict_result.id == winner.id
    assert conflict_result.report_text == "canonical report"
    assert conflict_result.model_name == "canonical-model"
    assert conflict_result.report_json == {"analysis": "canonical"}
    assert get_ai_report_by_idempotency_key(db_session, user.id, key).id == winner.id
    assert db_session.scalar(select(func.count()).select_from(AIReport)) == 1


def test_ai_report_idempotency_is_scoped_to_user(db_session):
    first_user = get_or_create_default_user(db_session)
    second_user = upsert_user(
        db_session,
        external_source="local",
        external_user_id="second-athlete",
    )
    key = "weekly:2026-08-03:coach-v1:input-a"
    first_summary = save_weekly_summary(
        db_session,
        first_user.id,
        week_start=date(2026, 8, 3),
        week_end=date(2026, 8, 9),
        summary_version="weekly:v1",
        summary_json={"week_start": "2026-08-03"},
    )
    second_summary = save_weekly_summary(
        db_session,
        second_user.id,
        week_start=date(2026, 8, 3),
        week_end=date(2026, 8, 9),
        summary_version="weekly:v1",
        summary_json={"week_start": "2026-08-03"},
    )

    first_report = save_ai_report(
        db_session,
        first_user.id,
        idempotency_key=key,
        report_scope="weekly",
        report_text="first athlete",
        input_json={"week_start": "2026-08-03"},
        weekly_summary_id=first_summary.id,
    )
    second_report = save_ai_report(
        db_session,
        second_user.id,
        idempotency_key=key,
        report_scope="weekly",
        report_text="second athlete",
        input_json={"week_start": "2026-08-03"},
        weekly_summary_id=second_summary.id,
    )

    assert first_report.id != second_report.id
    assert get_ai_report_by_idempotency_key(db_session, first_user.id, key).id == first_report.id
    assert get_ai_report_by_idempotency_key(db_session, second_user.id, key).id == second_report.id


def test_ai_report_subject_must_belong_to_user(db_session):
    first_user = get_or_create_default_user(db_session)
    second_user = upsert_user(
        db_session,
        external_source="local",
        external_user_id="other-athlete",
    )
    activity = upsert_activity(db_session, second_user.id, _activity_payload())

    with pytest.raises(ValueError, match="belong to user_id"):
        save_ai_report(
            db_session,
            first_user.id,
            idempotency_key="activity:123:wrong-owner",
            report_scope="activity",
            report_text="wrong owner",
            input_json={"activity_id": 123},
            activity_id=activity.id,
        )


def test_generated_loser_never_reaches_persisted_activity_delivery(db_session):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(db_session, user.id, _activity_payload())
    key = "activity:123:feature-v1:coach-v1:input-a"
    lock_state = {"held": False}

    @contextmanager
    def session_factory():
        yield db_session

    @contextmanager
    def notification_lock():
        assert lock_state["held"] is False
        lock_state["held"] = True
        try:
            yield
        finally:
            lock_state["held"] = False

    def generate(_spec: AIReportSpec) -> AIReportDraft:
        assert lock_state["held"] is False
        save_ai_report(
            db_session,
            user.id,
            idempotency_key=key,
            report_scope="activity",
            report_text="canonical concurrent winner",
            input_json={"activity_id": 123},
            model_name="canonical-model",
            prompt_version="coach:v1",
            activity_id=activity.id,
            feature_version="feature:v1",
            report_json={"analysis": "canonical"},
        )
        db_session.commit()
        return AIReportDraft(
            report_text="losing generated draft",
            model_name="losing-model",
            report_json={"analysis": "loser"},
        )

    delivery = ActivityAINotificationPreparer(
        session_factory=session_factory,
        notification_lock=notification_lock,
        generate=generate,
        render=lambda report: [f"AI:{report.report_text}"],
    ).prepare(
        spec=AIReportSpec(
            idempotency_key=key,
            user_id=user.id,
            report_scope="activity",
            input_json={"activity_id": 123},
            prompt_version="coach:v1",
            activity_id=activity.id,
            feature_version="feature:v1",
        ),
        garmin_activity_id=123,
    )

    report = get_ai_report_by_idempotency_key(db_session, user.id, key)
    notification = db_session.get(LineNotification, delivery.notification_id)
    assert report is not None
    assert report.report_text == "canonical concurrent winner"
    assert db_session.scalar(select(func.count()).select_from(AIReport)) == 1
    assert notification.ai_report_id == report.id
    assert notification.rendered_messages == ["AI:canonical concurrent winner"]
    assert delivery.rendered_messages == ("AI:canonical concurrent winner",)


def test_activity_notification_conflict_reuses_canonical_payload_and_first_sent_time(
    db_session,
):
    user = get_or_create_default_user(db_session)
    activity = upsert_activity(db_session, user.id, _activity_payload())
    winner_report = save_ai_report(
        db_session,
        user.id,
        idempotency_key="activity:123:notification-winner",
        report_scope="activity",
        report_text="canonical report",
        input_json={"activity_id": 123},
        activity_id=activity.id,
    )
    loser_report = save_ai_report(
        db_session,
        user.id,
        idempotency_key="activity:123:notification-loser",
        report_scope="activity",
        report_text="loser report",
        input_json={"activity_id": 123},
        activity_id=activity.id,
    )

    winner = prepare_activity_notification(
        db_session,
        garmin_activity_id=123,
        ai_report_id=winner_report.id,
        rendered_messages=["canonical page 1", "canonical page 2"],
    )
    conflict_result = prepare_activity_notification(
        db_session,
        garmin_activity_id=123,
        ai_report_id=loser_report.id,
        rendered_messages=["loser page"],
    )

    assert conflict_result.id == winner.id
    assert conflict_result.ai_report_id == winner_report.id
    assert conflict_result.rendered_messages == [
        "canonical page 1",
        "canonical page 2",
    ]
    assert [row.id for row in list_pending_activity_notifications(db_session)] == [
        winner.id
    ]

    first_sent_at = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
    later_sent_at = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
    sent = mark_notification_sent(db_session, winner.id, sent_at=first_sent_at)
    sent_again = mark_notification_sent(db_session, winner.id, sent_at=later_sent_at)

    assert sent.sent_at == first_sent_at
    assert sent_again.sent_at == first_sent_at
    assert list_pending_activity_notifications(db_session) == []


def test_activity_notification_conflict_rejects_stale_owner_payload(db_session):
    first_user = get_or_create_default_user(db_session)
    second_user = upsert_user(
        db_session,
        external_source="local",
        external_user_id="reassigned-athlete",
    )
    activity = upsert_activity(db_session, first_user.id, _activity_payload())
    first_report = save_ai_report(
        db_session,
        first_user.id,
        idempotency_key="activity:123:first-owner",
        report_scope="activity",
        report_text="first owner report",
        input_json={"activity_id": 123},
        activity_id=activity.id,
    )
    first_notification = prepare_activity_notification(
        db_session,
        garmin_activity_id=123,
        ai_report_id=first_report.id,
        rendered_messages=["first owner payload"],
    )

    reassigned_activity = upsert_activity(
        db_session,
        second_user.id,
        _activity_payload(),
    )
    second_report = save_ai_report(
        db_session,
        second_user.id,
        idempotency_key="activity:123:second-owner",
        report_scope="activity",
        report_text="second owner report",
        input_json={"activity_id": 123},
        activity_id=reassigned_activity.id,
    )

    with pytest.raises(ValueError, match="does not match"):
        prepare_activity_notification(
            db_session,
            garmin_activity_id=123,
            ai_report_id=second_report.id,
            rendered_messages=["second owner payload"],
        )

    db_session.refresh(first_notification)
    assert reassigned_activity.id == activity.id
    assert first_notification.ai_report_id == first_report.id
    assert first_notification.rendered_messages == ["first owner payload"]


def test_activity_notification_rejects_ai_report_for_another_activity(db_session):
    user = get_or_create_default_user(db_session)
    other_activity = upsert_activity(
        db_session,
        user.id,
        _activity_payload(activity_id=999),
    )
    report = save_ai_report(
        db_session,
        user.id,
        idempotency_key="activity:999:notification-subject",
        report_scope="activity",
        report_text="other activity",
        input_json={"activity_id": 999},
        activity_id=other_activity.id,
    )

    with pytest.raises(ValueError, match="does not match"):
        prepare_activity_notification(
            db_session,
            garmin_activity_id=123,
            ai_report_id=report.id,
            rendered_messages=["wrong subject"],
        )


def test_weekly_notification_rejects_ai_report_for_another_summary(db_session):
    user = get_or_create_default_user(db_session)
    first_summary = save_weekly_summary(
        db_session,
        user.id,
        week_start=date(2026, 8, 3),
        week_end=date(2026, 8, 9),
        summary_version="weekly:v1",
        summary_json={"week_start": "2026-08-03"},
    )
    second_summary = save_weekly_summary(
        db_session,
        user.id,
        week_start=date(2026, 8, 10),
        week_end=date(2026, 8, 16),
        summary_version="weekly:v1",
        summary_json={"week_start": "2026-08-10"},
    )
    report = save_ai_report(
        db_session,
        user.id,
        idempotency_key="weekly:2026-08-03:notification-subject",
        report_scope="weekly",
        report_text="first week",
        input_json={"week_start": "2026-08-03"},
        weekly_summary_id=first_summary.id,
    )

    with pytest.raises(ValueError, match="does not match"):
        prepare_weekly_notification(
            db_session,
            weekly_summary_id=second_summary.id,
            ai_report_id=report.id,
            rendered_messages=["wrong week"],
        )


def test_weekly_notification_conflict_rejects_stale_owner_payload(db_session):
    first_user = get_or_create_default_user(db_session)
    second_user = upsert_user(
        db_session,
        external_source="local",
        external_user_id="weekly-reassigned-athlete",
    )
    summary = save_weekly_summary(
        db_session,
        first_user.id,
        week_start=date(2026, 8, 3),
        week_end=date(2026, 8, 9),
        summary_version="weekly:v1",
        summary_json={"workout_count": 3},
    )
    first_report = save_ai_report(
        db_session,
        first_user.id,
        idempotency_key="weekly:2026-08-03:first-owner",
        report_scope="weekly",
        report_text="first owner report",
        input_json={"workout_count": 3},
        weekly_summary_id=summary.id,
    )
    first_notification = prepare_weekly_notification(
        db_session,
        weekly_summary_id=summary.id,
        ai_report_id=first_report.id,
        rendered_messages=["first owner weekly payload"],
    )

    summary.user_id = second_user.id
    db_session.flush()
    second_report = save_ai_report(
        db_session,
        second_user.id,
        idempotency_key="weekly:2026-08-03:second-owner",
        report_scope="weekly",
        report_text="second owner report",
        input_json={"workout_count": 3},
        weekly_summary_id=summary.id,
    )

    with pytest.raises(ValueError, match="does not match"):
        prepare_weekly_notification(
            db_session,
            weekly_summary_id=summary.id,
            ai_report_id=second_report.id,
            rendered_messages=["second owner weekly payload"],
        )

    db_session.refresh(first_notification)
    assert first_notification.ai_report_id == first_report.id
    assert first_notification.rendered_messages == ["first owner weekly payload"]


def test_weekly_notification_does_not_initialize_activity_baseline(db_session):
    user = get_or_create_default_user(db_session)
    summary = save_weekly_summary(
        db_session,
        user.id,
        week_start=date(2026, 8, 3),
        week_end=date(2026, 8, 9),
        summary_version="weekly:v1",
        summary_json={"week_start": "2026-08-03"},
    )
    report = save_ai_report(
        db_session,
        user.id,
        idempotency_key="weekly:2026-08-03:coach-v1:input-a",
        report_scope="weekly",
        report_text="weekly report",
        input_json={"week_start": "2026-08-03"},
        weekly_summary_id=summary.id,
    )

    notification = prepare_weekly_notification(
        db_session,
        weekly_summary_id=summary.id,
        ai_report_id=report.id,
        rendered_messages=["weekly page"],
    )

    assert notification.garmin_activity_id is None
    assert [row.id for row in list_pending_weekly_notifications(db_session)] == [
        notification.id
    ]
    assert is_notification_system_initialized(db_session) is False
    assert get_notified_activity_ids(db_session) == set()


def test_weekly_summary_recomputes_without_mutating_sent_notification(db_session):
    user = get_or_create_default_user(db_session)
    summary = save_weekly_summary(
        db_session,
        user.id,
        week_start=date(2026, 8, 3),
        week_end=date(2026, 8, 9),
        summary_version="weekly:v1",
        summary_json={"workout_count": 3},
        workout_count=3,
        total_distance_km=21.0,
    )
    report = save_ai_report(
        db_session,
        user.id,
        idempotency_key="weekly:2026-08-03:immutable-delivery",
        report_scope="weekly",
        report_text="original weekly analysis",
        input_json={"workout_count": 3},
        weekly_summary_id=summary.id,
    )
    notification = prepare_weekly_notification(
        db_session,
        weekly_summary_id=summary.id,
        ai_report_id=report.id,
        rendered_messages=["original weekly payload"],
    )
    sent_at = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
    mark_notification_sent(db_session, notification.id, sent_at=sent_at)

    recomputed = save_weekly_summary(
        db_session,
        user.id,
        week_start=date(2026, 8, 3),
        week_end=date(2026, 8, 9),
        summary_version="weekly:v1",
        summary_json={"workout_count": 4},
        workout_count=4,
        total_distance_km=28.0,
    )
    db_session.refresh(notification)

    assert recomputed.id == summary.id
    assert recomputed.workout_count == 4
    assert float(recomputed.total_distance_km) == 28.0
    assert notification.ai_report_id == report.id
    assert notification.rendered_messages == ["original weekly payload"]
    assert notification.sent_at == sent_at


def test_line_notification_repository_empty_context_seeding_and_record(db_session):
    """驗證 LINE 通知 DB 函式：空 context 初始化、sentinel 標記、去重寫入與 idempotency。"""
    assert is_notification_system_initialized(db_session) is False

    # 首次執行空 context：寫入 sentinel 標記 (-1)
    inserted = seed_baseline_notifications(db_session, [])
    assert inserted == 1
    assert is_notification_system_initialized(db_session) is True

    notified = get_notified_activity_ids(db_session)
    assert SYSTEM_INITIALIZED_MARKER_ID in notified

    # 記錄一筆 LINE 發送成功 (1001)
    recorded = record_notification(db_session, 1001)
    assert recorded is True
    assert 1001 in get_notified_activity_ids(db_session)
    sent_row = db_session.scalar(
        select(LineNotification).where(LineNotification.garmin_activity_id == 1001)
    )
    assert sent_row.sent_at is not None

    # 再次記錄同筆活動 1001，ON CONFLICT DO NOTHING 不重複寫入
    recorded_again = record_notification(db_session, 1001)
    assert recorded_again is False
