"""Cloud entry point for the persisted weekly training report."""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Callable

from sqlalchemy.orm import Session

from src.agents.weekly_coach import generate_weekly_report
from src.db.repositories import (
    get_latest_user_profile,
    get_or_create_default_user,
    get_recent_activities,
)
from src.db.session import SessionLocal
from src.preprocessing.activity_window import normalize_activity_window
from src.preprocessing.coach_context import build_deterministic_coach_context
from src.services.weekly_training_report import (
    WeeklyTrainingReportResult,
    WeeklyTrainingReportRunner,
)

WEEKLY_ACTIVITY_WINDOW = 75


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required for weekly LINE delivery")
    return value


def _build_context_from_database(
    session: Session,
    *,
    today: date,
) -> tuple[Any, dict[str, Any]]:
    user = get_or_create_default_user(session)
    raw_activities = [
        dict(activity.raw_json)
        for activity in get_recent_activities(
            session,
            user.id,
            limit=WEEKLY_ACTIVITY_WINDOW,
        )
    ]
    profile = get_latest_user_profile(session, user.id)
    user_data = dict(profile.raw_profile) if profile is not None else {}
    context = build_deterministic_coach_context(
        normalize_activity_window(raw_activities),
        user_data=user_data,
        today=today,
    )
    return user, context


def execute_weekly_training_report(
    *,
    today: date | None = None,
    retry_only: bool = False,
    session_factory: Callable[[], Session] = SessionLocal,
    runner_factory: Callable[..., WeeklyTrainingReportRunner] = WeeklyTrainingReportRunner,
) -> WeeklyTrainingReportResult:
    """Build a weekly report from persisted Garmin data only.

    Database access is mandatory: unlike the legacy Daily activity notifier,
    this workflow does not offer stateless LINE delivery when persistence is
    unavailable.
    """
    resolved_today = today or date.today()
    runner = runner_factory(
        session_factory=session_factory,
        generate=generate_weekly_report,
        token=_required_env("LINE_CHANNEL_ACCESS_TOKEN"),
        group_id=_required_env("LINE_GROUP_ID"),
    )
    with session_factory() as session:
        if retry_only:
            user = get_or_create_default_user(session)
            session.commit()
            return runner.retry_pending(user_id=user.id)
        user, context = _build_context_from_database(session, today=resolved_today)
        session.commit()

    return runner.run(
        user_id=user.id,
        deterministic_context=context,
        today=resolved_today,
    )
