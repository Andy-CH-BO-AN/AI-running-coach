"""Cloud entry point for the persisted weekly training report."""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.agents.weekly_coach import generate_weekly_report
from src.db.repositories import (
    get_activities_in_time_window,
    get_latest_user_profile,
    get_or_create_default_user,
)
from src.db.session import SessionLocal
from src.pipeline.goal_prompt import GoalPromptOverrides
from src.preprocessing.activity_window import normalize_activity_window
from src.preprocessing.coach_context import build_deterministic_coach_context
from src.services.weekly_training_report import (
    WeeklyTrainingReportResult,
    WeeklyTrainingReportRunner,
)

WEEKLY_REPORT_TIMEZONE = ZoneInfo("Asia/Taipei")
# Current week + completed report week + three chronic-baseline weeks.
WEEKLY_ANALYSIS_WEEKS = 5


def _default_weekly_report_date(now: datetime | None = None) -> date:
    """Resolve manual and scheduled runs against the report's local calendar."""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return instant.astimezone(WEEKLY_REPORT_TIMEZONE).date()


def _weekly_activity_window(today: date) -> tuple[datetime, datetime]:
    """Return the complete local-calendar window needed for a weekly report."""
    current_week_start = today - timedelta(days=today.weekday())
    earliest_week_start = current_week_start - timedelta(
        days=7 * (WEEKLY_ANALYSIS_WEEKS - 1)
    )
    window_start = datetime.combine(
        earliest_week_start, time.min, tzinfo=WEEKLY_REPORT_TIMEZONE
    ).astimezone(timezone.utc)
    window_end = datetime.combine(
        today + timedelta(days=1), time.min, tzinfo=WEEKLY_REPORT_TIMEZONE
    ).astimezone(timezone.utc)
    return window_start, window_end


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
    window_start, window_end = _weekly_activity_window(today)
    raw_activities = [
        dict(activity.raw_json)
        for activity in get_activities_in_time_window(
            session,
            user.id,
            started_at_on_or_after=window_start,
            started_at_before=window_end,
        )
    ]
    profile = get_latest_user_profile(session, user.id)
    user_data = dict(profile.raw_profile) if profile is not None else {}
    context = build_deterministic_coach_context(
        normalize_activity_window(raw_activities),
        user_data=user_data,
        today=today,
        weekly_analysis_weeks=WEEKLY_ANALYSIS_WEEKS,
    )
    return user, context


def execute_weekly_training_report(
    *,
    today: date | None = None,
    retry_only: bool = False,
    session_factory: Callable[[], Session] = SessionLocal,
    runner_factory: Callable[..., WeeklyTrainingReportRunner] = WeeklyTrainingReportRunner,
    goal_overrides: GoalPromptOverrides | None = None,
) -> WeeklyTrainingReportResult:
    """Build a weekly report from persisted Garmin data only.

    Database access is mandatory: unlike the legacy Daily activity notifier,
    this workflow does not offer stateless LINE delivery when persistence is
    unavailable.
    """
    resolved_today = today or _default_weekly_report_date()
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
        core_goal=goal_overrides.core_goal if goal_overrides else None,
        training_preferences=(
            goal_overrides.training_preferences if goal_overrides else None
        ),
    )
