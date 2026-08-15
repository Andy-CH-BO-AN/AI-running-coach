from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from src.db.models import (
    AIReport,
    Activity,
    ActivityFeature,
    ActivitySplit,
    LineNotification,
    SwimmingLength,
    User,
    UserProfileSnapshot,
    WeeklySummary,
    utc_now,
)
from src.db.mappers import (
    activity_values,
    map_activity_feature_values,
    map_ai_report_values,
    map_swimming_length_values,
    map_weekly_summary_values,
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


def find_activity_by_garmin_id(
    session: Session,
    user_id: uuid.UUID,
    garmin_activity_id: int,
) -> Activity | None:
    return session.scalars(
        select(Activity).where(
            Activity.user_id == user_id,
            Activity.garmin_activity_id == garmin_activity_id,
        )
    ).first()


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
        values = map_swimming_length_values(activity_split_id, length, offset=offset)
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
    values = map_activity_feature_values(
        activity_id,
        feature_version,
        features,
        algorithm_version,
    )
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
    values = map_weekly_summary_values(
        user_id,
        week_start,
        week_end,
        summary_version,
        summary_json,
        **metrics,
    )
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


def save_ai_report(
    session: Session,
    user_id: uuid.UUID,
    report_scope: str,
    report_text: str,
    input_json: dict[str, Any],
    idempotency_key: str,
    model_name: str = "unknown",
    prompt_version: str = "unknown",
    activity_id: uuid.UUID | None = None,
    weekly_summary_id: uuid.UUID | None = None,
    feature_version: str | None = None,
    report_json: dict[str, Any] | None = None,
    confidence: str | None = None,
    output_path: str | None = None,
) -> AIReport:
    if not idempotency_key.strip():
        raise ValueError("idempotency_key must not be empty")
    if report_scope == "activity":
        if activity_id is None or weekly_summary_id is not None:
            raise ValueError("Activity AI reports require only activity_id")
        activity = session.get(Activity, activity_id)
        if activity is None or activity.user_id != user_id:
            raise ValueError("Activity AI report subject must belong to user_id")
    elif report_scope == "weekly":
        if weekly_summary_id is None or activity_id is not None:
            raise ValueError("Weekly AI reports require only weekly_summary_id")
        summary = session.get(WeeklySummary, weekly_summary_id)
        if summary is None or summary.user_id != user_id:
            raise ValueError("Weekly AI report subject must belong to user_id")
    elif activity_id is not None or weekly_summary_id is not None:
        raise ValueError("Profile/custom AI reports cannot reference a training subject")

    values = map_ai_report_values(
        idempotency_key=idempotency_key,
        user_id=user_id,
        report_scope=report_scope,
        report_text=report_text,
        input_json=input_json,
        model_name=model_name,
        prompt_version=prompt_version,
        activity_id=activity_id,
        weekly_summary_id=weekly_summary_id,
        feature_version=feature_version,
        report_json=report_json,
        confidence=confidence,
        output_path=output_path,
    )
    stmt = (
        pg_insert(AIReport)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_ai_reports_user_idempotency_key")
        .returning(AIReport.id)
    )
    report_id = session.scalar(stmt)
    session.flush()
    report = (
        session.get(AIReport, report_id)
        if report_id is not None
        else get_ai_report_by_idempotency_key(
            session,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
    )
    if report is None:
        raise RuntimeError(
            "AI report idempotency conflict did not resolve to a persisted report"
        )
    session.refresh(report)
    expected_identity = (
        values["user_id"],
        values["idempotency_key"],
        values["report_scope"],
        values["activity_id"],
        values["weekly_summary_id"],
        values["prompt_version"],
        values["feature_version"],
        values["input_json"],
    )
    persisted_identity = (
        report.user_id,
        report.idempotency_key,
        report.report_scope,
        report.activity_id,
        report.weekly_summary_id,
        report.prompt_version,
        report.feature_version,
        report.input_json,
    )
    if persisted_identity != expected_identity:
        raise RuntimeError(
            "Canonical AI report does not match the requested report identity"
        )
    return report


def get_ai_report_by_idempotency_key(
    session: Session,
    user_id: uuid.UUID,
    idempotency_key: str,
) -> AIReport | None:
    return session.scalars(
        select(AIReport).where(
            AIReport.user_id == user_id,
            AIReport.idempotency_key == idempotency_key,
        )
    ).one_or_none()


def get_recent_activities(session: Session, user_id: uuid.UUID, limit: int = 20) -> list[Activity]:
    return list(
        session.scalars(
            select(Activity)
            .where(Activity.user_id == user_id)
            .order_by(desc(Activity.started_at), desc(Activity.garmin_activity_id))
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


# ──────────────────────────────────────────────────────────────────────────────
# LINE 通知狀態持久化
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_INITIALIZED_MARKER_ID: int = -1


def is_notification_system_initialized(session: Session) -> bool:
    """Return whether the explicit Activity baseline sentinel exists."""
    return session.scalar(
        select(LineNotification.id)
        .where(
            LineNotification.garmin_activity_id == SYSTEM_INITIALIZED_MARKER_ID,
            LineNotification.is_seed.is_(True),
        )
        .limit(1)
    ) is not None


def get_notified_activity_ids(session: Session) -> set[int]:
    """回傳所有已記錄（seed 或已通知）的 garmin_activity_id 集合。"""
    rows = session.execute(
        select(LineNotification.garmin_activity_id).where(
            LineNotification.garmin_activity_id.is_not(None)
        )
    ).scalars().all()
    return set(rows)


def get_activity_notification(
    session: Session,
    garmin_activity_id: int,
) -> LineNotification | None:
    return session.scalars(
        select(LineNotification).where(
            LineNotification.garmin_activity_id == garmin_activity_id
        )
    ).one_or_none()


def get_weekly_notification(
    session: Session,
    weekly_summary_id: uuid.UUID,
) -> LineNotification | None:
    return session.scalars(
        select(LineNotification).where(
            LineNotification.weekly_summary_id == weekly_summary_id
        )
    ).one_or_none()


def _validate_rendered_messages(rendered_messages: Sequence[str]) -> list[str]:
    if isinstance(rendered_messages, str):
        raise ValueError("rendered_messages must be a collection of messages")
    messages = list(rendered_messages)
    if not messages:
        raise ValueError("rendered_messages must contain at least one message")
    if any(not isinstance(message, str) or not message for message in messages):
        raise ValueError("rendered_messages must contain non-empty strings")
    return messages


def _validate_activity_report_subject(
    session: Session,
    *,
    ai_report_id: uuid.UUID,
    garmin_activity_id: int,
) -> None:
    report = session.get(AIReport, ai_report_id)
    if report is None or report.report_scope != "activity" or report.activity_id is None:
        raise ValueError("ai_report_id must reference an Activity AI report")
    activity = session.get(Activity, report.activity_id)
    if (
        activity is None
        or activity.garmin_activity_id != garmin_activity_id
        or activity.user_id != report.user_id
    ):
        raise ValueError("AI report does not match the Activity notification subject")


def get_prepared_activity_notification(
    session: Session,
    garmin_activity_id: int,
) -> LineNotification | None:
    """Return one validated prepared Activity delivery, if it exists."""
    notification = get_activity_notification(session, garmin_activity_id)
    if notification is None:
        return None
    session.refresh(notification)
    if (
        notification.is_seed
        or notification.ai_report_id is None
        or notification.rendered_messages is None
    ):
        return None
    _validate_rendered_messages(notification.rendered_messages)
    _validate_activity_report_subject(
        session,
        ai_report_id=notification.ai_report_id,
        garmin_activity_id=garmin_activity_id,
    )
    return notification


def get_prepared_weekly_notification(
    session: Session,
    weekly_summary_id: uuid.UUID,
) -> LineNotification | None:
    """Return one validated prepared weekly delivery, if it exists.

    A weekly summary itself remains recomputable.  The notification payload is
    deliberately a separate immutable snapshot so a failed LINE delivery can
    be retried without rebuilding facts or asking the model again.
    """
    notification = get_weekly_notification(session, weekly_summary_id)
    if notification is None:
        return None
    session.refresh(notification)
    if (
        notification.is_seed
        or notification.ai_report_id is None
        or notification.rendered_messages is None
    ):
        return None
    _validate_rendered_messages(notification.rendered_messages)
    _validate_weekly_report_subject(
        session,
        ai_report_id=notification.ai_report_id,
        weekly_summary_id=weekly_summary_id,
    )
    return notification


def _validate_weekly_report_subject(
    session: Session,
    *,
    ai_report_id: uuid.UUID,
    weekly_summary_id: uuid.UUID,
) -> None:
    report = session.get(AIReport, ai_report_id)
    summary = session.get(WeeklySummary, weekly_summary_id)
    if (
        report is None
        or summary is None
        or report.report_scope != "weekly"
        or report.weekly_summary_id != weekly_summary_id
        or report.user_id != summary.user_id
    ):
        raise ValueError("AI report does not match the weekly notification subject")


def prepare_activity_notification(
    session: Session,
    *,
    garmin_activity_id: int,
    ai_report_id: uuid.UUID,
    rendered_messages: Sequence[str],
) -> LineNotification:
    """Persist once and return the canonical immutable Activity delivery."""
    messages = _validate_rendered_messages(rendered_messages)
    _validate_activity_report_subject(
        session,
        ai_report_id=ai_report_id,
        garmin_activity_id=garmin_activity_id,
    )
    now = utc_now()
    stmt = (
        pg_insert(LineNotification)
        .values(
            id=uuid.uuid4(),
            garmin_activity_id=garmin_activity_id,
            weekly_summary_id=None,
            ai_report_id=ai_report_id,
            rendered_messages=messages,
            recorded_at=now,
            is_seed=False,
            sent_at=None,
            created_at=now,
        )
        .on_conflict_do_nothing(
            constraint="uq_line_notifications_garmin_activity_id"
        )
        .returning(LineNotification.id)
    )
    notification_id = session.scalar(stmt)
    session.flush()
    notification = (
        session.get(LineNotification, notification_id)
        if notification_id is not None
        else get_activity_notification(session, garmin_activity_id)
    )
    if notification is None:
        raise RuntimeError(
            "Activity notification conflict did not resolve to a persisted delivery"
        )
    session.refresh(notification)
    if notification.ai_report_id is None or notification.rendered_messages is None:
        raise ValueError("Canonical Activity notification is not a prepared delivery")
    _validate_rendered_messages(notification.rendered_messages)
    _validate_activity_report_subject(
        session,
        ai_report_id=notification.ai_report_id,
        garmin_activity_id=garmin_activity_id,
    )
    return notification


def prepare_weekly_notification(
    session: Session,
    *,
    weekly_summary_id: uuid.UUID,
    ai_report_id: uuid.UUID,
    rendered_messages: Sequence[str],
) -> LineNotification:
    """Persist once and return the canonical immutable weekly delivery."""
    messages = _validate_rendered_messages(rendered_messages)
    _validate_weekly_report_subject(
        session,
        ai_report_id=ai_report_id,
        weekly_summary_id=weekly_summary_id,
    )
    now = utc_now()
    stmt = (
        pg_insert(LineNotification)
        .values(
            id=uuid.uuid4(),
            garmin_activity_id=None,
            weekly_summary_id=weekly_summary_id,
            ai_report_id=ai_report_id,
            rendered_messages=messages,
            recorded_at=now,
            is_seed=False,
            sent_at=None,
            created_at=now,
        )
        .on_conflict_do_nothing(
            constraint="uq_line_notifications_weekly_summary_id"
        )
        .returning(LineNotification.id)
    )
    notification_id = session.scalar(stmt)
    session.flush()
    notification = (
        session.get(LineNotification, notification_id)
        if notification_id is not None
        else get_weekly_notification(session, weekly_summary_id)
    )
    if notification is None:
        raise RuntimeError(
            "Weekly notification conflict did not resolve to a persisted delivery"
        )
    session.refresh(notification)
    if notification.ai_report_id is None or notification.rendered_messages is None:
        raise ValueError("Canonical weekly notification is not a prepared delivery")
    _validate_rendered_messages(notification.rendered_messages)
    _validate_weekly_report_subject(
        session,
        ai_report_id=notification.ai_report_id,
        weekly_summary_id=weekly_summary_id,
    )
    return notification


def list_pending_activity_notifications(
    session: Session,
    *,
    limit: int | None = None,
) -> list[LineNotification]:
    stmt = (
        select(LineNotification)
        .where(
            LineNotification.garmin_activity_id.is_not(None),
            LineNotification.is_seed.is_(False),
            LineNotification.rendered_messages.is_not(None),
            LineNotification.sent_at.is_(None),
        )
        .order_by(LineNotification.recorded_at, LineNotification.id)
    )
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def list_pending_weekly_notifications(
    session: Session,
    *,
    user_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> list[LineNotification]:
    stmt = (
        select(LineNotification)
        .where(
            LineNotification.weekly_summary_id.is_not(None),
            LineNotification.is_seed.is_(False),
            LineNotification.rendered_messages.is_not(None),
            LineNotification.sent_at.is_(None),
        )
        .order_by(LineNotification.recorded_at, LineNotification.id)
    )
    if user_id is not None:
        stmt = stmt.join(
            WeeklySummary,
            LineNotification.weekly_summary_id == WeeklySummary.id,
        ).where(WeeklySummary.user_id == user_id)
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def mark_notification_sent(
    session: Session,
    notification_id: uuid.UUID,
    *,
    sent_at: datetime | None = None,
) -> LineNotification:
    """Record first successful delivery time without changing immutable payload."""
    stmt = (
        update(LineNotification)
        .where(
            LineNotification.id == notification_id,
            LineNotification.sent_at.is_(None),
        )
        .values(sent_at=sent_at or utc_now())
        .returning(LineNotification.id)
    )
    updated_id = session.scalar(stmt)
    session.flush()
    notification = session.get(LineNotification, updated_id or notification_id)
    if notification is None:
        raise LookupError(f"LINE notification not found: {notification_id}")
    session.refresh(notification)
    return notification


def seed_baseline_notifications(session: Session, activity_ids: list[int]) -> int:
    """批量建立 baseline seed 紀錄，並寫入系統初始化標記（SYSTEM_INITIALIZED_MARKER_ID = -1）。

    使用 INSERT ... ON CONFLICT DO NOTHING 確保冪等。
    即使 activity_ids 為空，也會寫入 sentinel 標記，避免未來出現第一筆活動時被誤判為首次初始化。
    回傳實際插入筆數。
    """
    to_insert = list(set(activity_ids))
    if SYSTEM_INITIALIZED_MARKER_ID not in to_insert:
        to_insert.append(SYSTEM_INITIALIZED_MARKER_ID)

    stmt = (
        pg_insert(LineNotification)
        .values([
            {
                "id": uuid.uuid4(),
                "garmin_activity_id": aid,
                "is_seed": True,
                "recorded_at": utc_now(),
                "created_at": utc_now(),
            }
            for aid in to_insert
        ])
        .on_conflict_do_nothing(index_elements=["garmin_activity_id"])
        .returning(LineNotification.id)
    )
    inserted_ids = session.execute(stmt).scalars().all()
    session.commit()
    return len(inserted_ids)


def record_notification(session: Session, garmin_activity_id: int) -> bool:
    """記錄 LINE 訊息已成功發送的活動（is_seed=False）。

    使用 INSERT ... ON CONFLICT DO NOTHING 確保冪等。
    回傳 True 表示成功插入，False 表示已存在。
    """
    now = utc_now()
    stmt = (
        pg_insert(LineNotification)
        .values(
            id=uuid.uuid4(),
            garmin_activity_id=garmin_activity_id,
            is_seed=False,
            recorded_at=now,
            sent_at=now,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["garmin_activity_id"])
        .returning(LineNotification.id)
    )
    inserted_ids = session.execute(stmt).scalars().all()
    session.commit()
    return len(inserted_ids) > 0
