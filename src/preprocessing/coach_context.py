from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Sequence

from src.preprocessing.activity_window import ActivityWindow, NormalizedActivity
from src.preprocessing.coach_context_types import (
    DeterministicCoachContext,
    HrZoneDistribution,
)
from src.preprocessing.coach_context_utils import (
    _parse_date,
    _resolve_today,
    _round_or_none,
)
from src.preprocessing.coach_context_athlete_metrics import (
    _build_cross_training,
    _build_physio_metrics,
    _build_running_mechanics,
)
from src.preprocessing.coach_context_enforcement import enforce_deterministic_report_fields
from src.preprocessing.coach_context_sessions import _build_session
from src.preprocessing.coach_context_weekly import (
    _build_12week_summary,
    _build_evidence_facts,
    _build_load_assessment,
    _build_next_week_seed,
    _build_pb_validation_seed,
    _build_weekly_analysis,
)
from src.preprocessing.coach_context_zones import build_time_in_zone_distribution

ZONE_NAMES = {
    1: "Z1 恢復",
    2: "Z2 有氧",
    3: "Z3 節奏",
    4: "Z4 閾值",
    5: "Z5 高強度",
}
POWER_ZONE_NAMES = {
    1: "Z1 恢復",
    2: "Z2 耐力",
    3: "Z3 節奏",
    4: "Z4 閾值",
    5: "Z5 無氧",
}


def _build_hr_zone_distribution(
    activities: Sequence[NormalizedActivity],
) -> HrZoneDistribution:
    return build_time_in_zone_distribution(
        activities,
        metric_base="hr",
        zone_names=ZONE_NAMES,
        include_polarized=True,
    )


def _build_power_zone_distribution(
    activities: Sequence[NormalizedActivity],
) -> Dict[str, Any]:
    return build_time_in_zone_distribution(
        activities,
        metric_base="power",
        zone_names=POWER_ZONE_NAMES,
    )


def _activities_in_analysis_weeks(
    activities: Sequence[NormalizedActivity],
    weekly_analysis: Sequence[Dict[str, Any]],
) -> tuple[NormalizedActivity, ...]:
    if not weekly_analysis:
        return ()
    period_start = _parse_date(weekly_analysis[-1].get("week_start"))
    period_end = _parse_date(weekly_analysis[0].get("week_end"))
    if period_start is None or period_end is None:
        return ()
    return tuple(
        activity
        for activity in activities
        if (activity_date := _parse_date(activity.date)) is not None
        and period_start <= activity_date <= period_end
    )


def build_deterministic_coach_context(
    activity_window: ActivityWindow,
    user_data: Optional[Dict[str, Any]] = None,
    today: Any = None,
) -> DeterministicCoachContext:
    """Build deterministic coach context from one normalized Activity window."""

    user_data = user_data or {}
    resolved_today = _resolve_today(
        today,
        [{"date": activity.date} for activity in activity_window.activities],
    )

    sessions = [_build_session(activity) for activity in activity_window.activities]
    weekly_analysis = _build_weekly_analysis(sessions, today=resolved_today)
    four_week_activities = _activities_in_analysis_weeks(
        activity_window.activities,
        weekly_analysis,
    )
    hr_zone_distribution = _build_hr_zone_distribution(four_week_activities)
    power_zone_distribution = _build_power_zone_distribution(four_week_activities)
    load_assessment = _build_load_assessment(weekly_analysis)

    return {
        "meta": {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "today": resolved_today.isoformat(),
            "analysis_period_weeks": 4,
            "source": "deterministic_coach_context:v1",
        },
        "deterministic_fields": [
            "weekly_analysis[].week_start/week_end",
            "weekly_analysis[].session_counts",
            "weekly_analysis[].sessions[]",
            "weekly_analysis[].derived_total_distance_km",
            "weekly_analysis[].derived_total_duration_min",
            "weekly_analysis[].derived_training_load",
            "hr_zone_distribution.zones[].minutes",
            "hr_zone_distribution.zones[].percentage",
            "power_zone_distribution.zones[].minutes",
            "power_zone_distribution.zones[].percentage",
            "physio_metrics.pace_zones",
            "running_mechanics",
            "load_assessment.current_tss_weekly",
            "next_week_plan_seed.week_start/days[].date",
        ],
        "athlete_profile": {
            "weight_kg": _round_or_none(user_data.get("weight_kg"), 1),
            "height_cm": _round_or_none(user_data.get("height_cm"), 1),
            "available_training_days": user_data.get("available_training_days") or [],
            "preferred_long_training_days": user_data.get("preferred_long_training_days") or [],
        },
        "physio_metrics": _build_physio_metrics(user_data),
        "pb_validation_seed": _build_pb_validation_seed(user_data),
        "weekly_analysis": weekly_analysis,
        "hr_zone_distribution": hr_zone_distribution,
        "power_zone_distribution": power_zone_distribution,
        "running_mechanics": _build_running_mechanics(four_week_activities),
        "cross_training": _build_cross_training(four_week_activities),
        "load_assessment": load_assessment,
        "next_week_plan_seed": _build_next_week_seed(resolved_today, user_data),
        "twelve_week_summary": _build_12week_summary(sessions, today=resolved_today),
        "evidence_facts": _build_evidence_facts(
            weekly_analysis=weekly_analysis,
            hr_zone_distribution=hr_zone_distribution,
            load_assessment=load_assessment,
        ),
    }
