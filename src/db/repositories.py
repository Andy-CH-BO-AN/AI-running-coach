from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from src.db.models import (
    AIReport,
    Activity,
    ActivityFeature,
    ActivitySplit,
    SwimmingLength,
    User,
    UserProfileSnapshot,
    WeeklySummary,
    utc_now,
)
from src.db.mappers import (
    activity_values,
    first_present,
    int_or_none,
    jsonable,
    num,
    split_values,
    user_profile_snapshot_values,
)


def get_or_create_default_user(session: Session) -> User:
    return upsert_user(
        session,
        external_source="local",
        external_user_id="default",
        display_name="Default local athlete",
    )


def upsert_user(
    session: Session,
    external_source: str = "garmin",
    external_user_id: str | None = None,
    display_name: str | None = None,
) -> User:
    stmt: Select[tuple[User]] = select(User).where(User.external_source == external_source)
    if external_user_id is None:
        stmt = stmt.where(User.external_user_id.is_(None))
    else:
        stmt = stmt.where(User.external_user_id == external_user_id)

    user = session.scalars(stmt).first()
    if user:
        if display_name is not None:
            user.display_name = display_name
        user.updated_at = utc_now()
        session.flush()
        return user

    user = User(
        external_source=external_source,
        external_user_id=external_user_id,
        display_name=display_name,
    )
    session.add(user)
    session.flush()
    return user


def insert_user_profile_snapshot(
    session: Session,
    user_id: uuid.UUID,
    profile_data: dict[str, Any],
    captured_at: datetime,
    source_file: str | None = None,
) -> UserProfileSnapshot:
    values = user_profile_snapshot_values(
        user_id=user_id,
        profile_data=profile_data,
        captured_at=captured_at,
        source_file=source_file,
    )
    stmt = pg_insert(UserProfileSnapshot).values(**values)
    excluded = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        constraint="uq_user_profile_snapshots_user_captured_at",
        set_={
            **{key: value for key, value in values.items() if key not in {"user_id", "captured_at", "resting_heart_rate"}},
            "resting_heart_rate": func.coalesce(
                func.least(UserProfileSnapshot.resting_heart_rate, excluded.resting_heart_rate),
                excluded.resting_heart_rate,
                UserProfileSnapshot.resting_heart_rate,
            ),
        },
    ).returning(UserProfileSnapshot.id)
    snapshot_id = session.scalar(stmt)
    session.flush()
    snapshot = session.get(UserProfileSnapshot, snapshot_id)
    session.refresh(snapshot)
    return snapshot


def get_latest_user_profile(session: Session, user_id: uuid.UUID) -> UserProfileSnapshot | None:
    return session.scalars(
        select(UserProfileSnapshot)
        .where(UserProfileSnapshot.user_id == user_id)
        .order_by(desc(UserProfileSnapshot.captured_at))
        .limit(1)
    ).first()


def get_profile_history(session: Session, user_id: uuid.UUID) -> list[UserProfileSnapshot]:
    return list(
        session.scalars(
            select(UserProfileSnapshot)
            .where(UserProfileSnapshot.user_id == user_id)
            .order_by(UserProfileSnapshot.captured_at)
        )
    )


def get_latest_resting_heart_rate(session: Session, user_id: uuid.UUID) -> float | None:
    value = session.scalar(
        select(UserProfileSnapshot.resting_heart_rate)
        .where(
            UserProfileSnapshot.user_id == user_id,
            UserProfileSnapshot.resting_heart_rate.is_not(None),
        )
        .order_by(desc(UserProfileSnapshot.captured_at))
        .limit(1)
    )
    return float(value) if value is not None else None


def get_recent_max_heart_rate(
    session: Session,
    user_id: uuid.UUID,
    *,
    lookback_days: int = 183,
    as_of_date: date | None = None,
) -> float | None:
    reference_date = as_of_date or datetime.now(timezone.utc).date()
    cutoff_date = reference_date - timedelta(days=lookback_days)
    activity_value = session.scalar(
        select(func.max(Activity.max_heart_rate)).where(
            Activity.user_id == user_id,
            Activity.activity_date >= cutoff_date,
            Activity.activity_date <= reference_date,
        )
    )
    split_value = session.scalar(
        select(func.max(ActivitySplit.max_heart_rate))
        .join(Activity, Activity.id == ActivitySplit.activity_id)
        .where(
            Activity.user_id == user_id,
            Activity.activity_date >= cutoff_date,
            Activity.activity_date <= reference_date,
        )
    )
    return num(max(num(activity_value) or 0, num(split_value) or 0)) or None


def upsert_activity(
    session: Session,
    user_id: uuid.UUID,
    activity_data: dict[str, Any],
    source_file: str | None = None,
) -> Activity:
    values = activity_values(user_id=user_id, activity_data=activity_data, source_file=source_file)
    stmt = pg_insert(Activity).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_activities_garmin_activity_id",
        set_={key: value for key, value in values.items() if key != "garmin_activity_id"},
    ).returning(Activity.id)
    activity_id = session.scalar(stmt)
    session.flush()
    activity = session.get(Activity, activity_id)
    session.refresh(activity)
    return activity


def upsert_activity_splits(
    session: Session,
    activity_id: uuid.UUID,
    splits: list[dict[str, Any]],
    activity_type: str | None = None,
) -> list[ActivitySplit]:
    if activity_type is None:
        activity = session.get(Activity, activity_id)
        activity_type = activity.activity_type if activity else None

    persisted: list[ActivitySplit] = []
    for split in splits or []:
        if split.get("split_index") is None:
            continue
        values = split_values(activity_id, split, activity_type=activity_type)
        stmt = pg_insert(ActivitySplit).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_activity_splits_activity_id_split_index",
            set_={key: value for key, value in values.items() if key not in {"activity_id", "split_index"}},
        ).returning(ActivitySplit.id)
        split_id = session.scalar(stmt)
        session.flush()
        model = session.get(ActivitySplit, split_id)
        session.refresh(model)
        persisted.append(model)
    return persisted


def upsert_swimming_lengths(
    session: Session,
    activity_split_id: uuid.UUID,
    lengths: list[dict[str, Any]],
) -> list[SwimmingLength]:
    persisted: list[SwimmingLength] = []
    for offset, length in enumerate(lengths or [], start=1):
        length_index = length.get("length_index") or offset
        values = {
            "activity_split_id": activity_split_id,
            "length_index": int(length_index),
            "distance_m": num(first_present(length.get("distance"), length.get("distance_m"))),
            "duration_sec": num(first_present(length.get("duration"), length.get("duration_sec"))),
            "swim_stroke": length.get("swim_stroke"),
            "strokes": int_or_none(length.get("strokes")),
            "swolf": num(length.get("swolf")),
            "avg_hr": num(length.get("avg_hr")),
            "raw_json": jsonable(length),
            "updated_at": utc_now(),
        }
        stmt = pg_insert(SwimmingLength).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_swimming_lengths_split_id_length_index",
            set_={key: value for key, value in values.items() if key not in {"activity_split_id", "length_index"}},
        ).returning(SwimmingLength.id)
        length_id = session.scalar(stmt)
        session.flush()
        model = session.get(SwimmingLength, length_id)
        session.refresh(model)
        persisted.append(model)
    return persisted


def save_activity_features(
    session: Session,
    activity_id: uuid.UUID,
    feature_version: str,
    features: dict[str, Any],
    algorithm_version: str | None = None,
) -> ActivityFeature:
    values = {
        "activity_id": activity_id,
        "feature_version": feature_version,
        "algorithm_version": algorithm_version,
        "computed_at": utc_now(),
        "features": jsonable(features),
    }
    stmt = pg_insert(ActivityFeature).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_activity_features_activity_version",
        set_={
            "algorithm_version": algorithm_version,
            "computed_at": values["computed_at"],
            "features": values["features"],
        },
    ).returning(ActivityFeature.id)
    feature_id = session.scalar(stmt)
    session.flush()
    feature = session.get(ActivityFeature, feature_id)
    session.refresh(feature)
    return feature


def save_weekly_summary(
    session: Session,
    user_id: uuid.UUID,
    week_start: date,
    week_end: date,
    summary_version: str,
    summary_json: dict[str, Any],
    **metrics: Any,
) -> WeeklySummary:
    values = {
        "user_id": user_id,
        "week_start": week_start,
        "week_end": week_end,
        "summary_version": summary_version,
        "computed_at": utc_now(),
        "summary_json": jsonable(summary_json),
        **{key: metrics.get(key) for key in _weekly_metric_keys()},
    }
    stmt = pg_insert(WeeklySummary).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_weekly_summaries_user_week_version",
        set_={key: value for key, value in values.items() if key not in {"user_id", "week_start", "summary_version"}},
    ).returning(WeeklySummary.id)
    summary_id = session.scalar(stmt)
    session.flush()
    summary = session.get(WeeklySummary, summary_id)
    session.refresh(summary)
    return summary


def _weekly_metric_keys() -> tuple[str, ...]:
    return (
        "total_distance_km",
        "total_duration_min",
        "running_distance_km",
        "swimming_distance_km",
        "workout_count",
        "running_count",
        "swimming_count",
        "high_intensity_count",
        "long_run_count",
        "training_load",
        "acute_load",
        "chronic_load",
        "acute_chronic_ratio",
        "monotony",
        "strain",
    )


def save_ai_report(
    session: Session,
    user_id: uuid.UUID,
    report_scope: str,
    report_text: str,
    input_json: dict[str, Any],
    model_name: str = "unknown",
    prompt_version: str = "unknown",
    activity_id: uuid.UUID | None = None,
    weekly_summary_id: uuid.UUID | None = None,
    feature_version: str | None = None,
    report_json: dict[str, Any] | None = None,
    confidence: str | None = None,
    output_path: str | None = None,
) -> AIReport:
    report = AIReport(
        user_id=user_id,
        activity_id=activity_id,
        weekly_summary_id=weekly_summary_id,
        report_scope=report_scope,
        model_name=model_name,
        prompt_version=prompt_version,
        feature_version=feature_version,
        input_json=jsonable(input_json),
        report_json=jsonable(report_json) if report_json is not None else None,
        report_text=report_text,
        confidence=confidence,
        output_path=output_path,
    )
    session.add(report)
    session.flush()
    return report


def get_recent_activities(session: Session, user_id: uuid.UUID, limit: int = 20) -> list[Activity]:
    return list(
        session.scalars(
            select(Activity)
            .where(Activity.user_id == user_id)
            .order_by(desc(Activity.started_at))
            .limit(limit)
        )
    )


def get_activity_with_splits(session: Session, activity_id: uuid.UUID) -> Activity | None:
    return session.scalars(
        select(Activity)
        .where(Activity.id == activity_id)
        .options(selectinload(Activity.splits).selectinload(ActivitySplit.swimming_lengths))
    ).first()


def get_weekly_training_summary(session: Session, user_id: uuid.UUID, week_start: date) -> WeeklySummary | None:
    return session.scalars(
        select(WeeklySummary)
        .where(WeeklySummary.user_id == user_id, WeeklySummary.week_start == week_start)
        .order_by(desc(WeeklySummary.computed_at))
        .limit(1)
    ).first()
