"""Deterministic facts for one completed training week.

This module projects the existing coach context instead of issuing a second
database aggregate.  Garmin facts stay in the shared deterministic context;
the AI only receives this immutable, explicitly scoped interpretation input.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from src.preprocessing.coach_context_utils import (
    WEEKDAY_LABELS,
    _normalize_weekday,
    _parse_date,
    _round_or_none,
    _safe_float,
    _week_start_for,
)

WEEKLY_SUMMARY_VERSION = "weekly:v4"


@dataclass(frozen=True, slots=True)
class CompletedWeekSummary:
    """One reusable deterministic weekly summary plus mapped DB metrics."""

    week_start: date
    week_end: date
    summary_json: dict[str, Any]
    metrics: dict[str, float | int | None]


def _number(value: Any) -> float:
    return _safe_float(value) or 0.0


def _sport_name(source_type: str) -> str:
    normalized = source_type.lower()
    if normalized == "running":
        return "跑步"
    if normalized in {"swimming", "lap_swimming"}:
        return "游泳"
    if normalized == "cycling":
        return "自行車"
    if normalized == "strength_training":
        return "肌力訓練"
    return source_type or "其他"


def _weekly_target(today: date) -> tuple[date, date]:
    week_start = _week_start_for(today) - timedelta(days=7)
    return week_start, week_start + timedelta(days=6)


def _find_week(
    weekly_analysis: Sequence[Mapping[str, Any]],
    week_start: date,
) -> Mapping[str, Any]:
    for week in weekly_analysis:
        if _parse_date(week.get("week_start")) == week_start:
            return week
    raise ValueError(
        "Deterministic context does not include the previous complete week"
    )


def _sport_totals(sessions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for session in sessions:
        source_type = str(session.get("source_activity_type") or "其他")
        entry = totals.setdefault(
            source_type,
            {
                "source_activity_type": source_type,
                "display_name": _sport_name(source_type),
                "count": 0,
                "distance_km": 0.0,
                "duration_min": 0.0,
                "training_load": 0.0,
            },
        )
        entry["count"] += 1
        entry["distance_km"] += _number(session.get("distance_km"))
        entry["duration_min"] += _number(session.get("duration_min"))
        entry["training_load"] += _number(session.get("training_load"))

    return [
        {
            **entry,
            "distance_km": (
                None
                if entry["source_activity_type"] == "strength_training"
                else _round_or_none(entry["distance_km"], 2) or 0.0
            ),
            "duration_min": _round_or_none(entry["duration_min"], 1) or 0.0,
            "training_load": _round_or_none(entry["training_load"], 1) or 0.0,
        }
        for _, entry in sorted(totals.items())
    ]


def _combined_sport_metrics(
    sport_totals: Sequence[Mapping[str, Any]],
    source_types: frozenset[str],
) -> dict[str, float | int]:
    """Return DB metrics for one sport, including its Garmin aliases."""
    matching = [
        entry
        for entry in sport_totals
        if str(entry.get("source_activity_type")) in source_types
    ]
    return {
        "distance_km": _round_or_none(
            sum(_number(entry.get("distance_km")) for entry in matching),
            2,
        )
        or 0.0,
        "count": sum(int(entry.get("count") or 0) for entry in matching),
    }


def _strength_training_summary(
    sessions: Sequence[Mapping[str, Any]],
) -> dict[str, int | float | None]:
    """Aggregate only complete Garmin strength session facts for weekly AI."""
    strength_sessions = [
        session
        for session in sessions
        if session.get("source_activity_type") == "strength_training"
    ]
    if not strength_sessions:
        return {
            "sessions_count": 0,
            "total_sets": None,
            "total_reps": None,
            "total_volume_kg": None,
        }
    complete = all(
        (session.get("data_quality") or {}).get("status") == "complete"
        and isinstance(session.get("strength"), Mapping)
        for session in strength_sessions
    )

    def aggregate(key: str) -> int | float | None:
        if not complete:
            return None
        values = [
            _safe_float((session.get("strength") or {}).get(key))
            for session in strength_sessions
        ]
        if any(value is None for value in values):
            return None
        total = sum(value or 0 for value in values)
        return int(total) if key != "total_volume_kg" else _round_or_none(total, 2)

    return {
        "sessions_count": len(strength_sessions),
        "total_sets": aggregate("total_sets"),
        "total_reps": aggregate("total_reps"),
        "total_volume_kg": aggregate("total_volume_kg"),
    }


def _load_metrics(
    weekly_analysis: Sequence[Mapping[str, Any]],
    week_start: date,
    sessions: Sequence[Mapping[str, Any]],
    current_load: float,
) -> dict[str, float | None]:
    previous_loads: list[float] = []
    for week in weekly_analysis:
        candidate_start = _parse_date(week.get("week_start"))
        if candidate_start is not None and candidate_start < week_start:
            previous_loads.append(_number(week.get("derived_training_load")))
    previous_loads = previous_loads[:3]
    chronic_load = (
        _round_or_none(sum(previous_loads) / len(previous_loads), 1)
        if previous_loads
        else None
    )
    acute_chronic_ratio = (
        _round_or_none(current_load / chronic_load, 2)
        if chronic_load and chronic_load > 0
        else None
    )

    daily_loads = {
        week_start + timedelta(days=offset): 0.0
        for offset in range(7)
    }
    for session in sessions:
        day = _parse_date(session.get("date"))
        if day not in daily_loads:
            continue
        daily_loads[day] += _number(
            session.get("training_load")
        )
    values = list(daily_loads.values())
    monotony: float | None = None
    if len(values) >= 2:
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        standard_deviation = math.sqrt(variance)
        if standard_deviation > 0:
            monotony = _round_or_none(mean / standard_deviation, 2)
    strain = (
        _round_or_none(current_load * monotony, 1)
        if monotony is not None
        else None
    )
    return {
        "acute_load": _round_or_none(current_load, 1) or 0.0,
        "chronic_load": chronic_load,
        "acute_chronic_ratio": acute_chronic_ratio,
        "monotony": monotony,
        "strain": strain,
        "previous_week_loads": [
            _round_or_none(value, 1) or 0.0 for value in previous_loads
        ],
    }


def _next_week_seed(
    athlete_profile: Mapping[str, Any],
    week_start: date,
) -> dict[str, Any]:
    next_start = week_start + timedelta(days=7)
    available_days = {
        normalized
        for value in athlete_profile.get("available_training_days") or []
        if (normalized := _normalize_weekday(value))
    }
    long_days = {
        normalized
        for value in athlete_profile.get("preferred_long_training_days") or []
        if (normalized := _normalize_weekday(value))
    }
    return {
        "week_start": next_start.isoformat(),
        "days": [
            {
                "date": (next_start + timedelta(days=offset)).isoformat(),
                "day_of_week": weekday,
                "available_for_training": not available_days or weekday in available_days,
                "preferred_long_run_day": weekday in long_days,
            }
            for offset, weekday in enumerate(WEEKDAY_LABELS)
        ],
    }


def build_completed_week_summary(
    deterministic_context: Mapping[str, Any],
    *,
    today: date,
) -> CompletedWeekSummary:
    """Project last Monday–Sunday from the shared deterministic context."""
    week_start, week_end = _weekly_target(today)
    weekly_analysis = deterministic_context.get("weekly_analysis") or []
    if not isinstance(weekly_analysis, Sequence):
        raise ValueError("Deterministic context has no weekly_analysis")
    week = _find_week(weekly_analysis, week_start)
    sessions = [
        dict(session)
        for session in week.get("sessions") or []
        if isinstance(session, Mapping)
    ]
    sport_totals = _sport_totals(sessions)
    strength_training = _strength_training_summary(sessions)
    total_distance = _number(week.get("derived_total_distance_km"))
    has_distance_bearing_session = any(
        _safe_float(session.get("distance_km")) is not None
        for session in sessions
    )
    total_duration = _number(week.get("derived_total_duration_min"))
    training_load = _number(week.get("derived_training_load"))
    load_metrics = _load_metrics(
        weekly_analysis,
        week_start,
        sessions,
        training_load,
    )
    counts = week.get("session_counts") if isinstance(week.get("session_counts"), Mapping) else {}
    running = _combined_sport_metrics(sport_totals, frozenset({"running"}))
    swimming = _combined_sport_metrics(
        sport_totals,
        frozenset({"swimming", "lap_swimming"}),
    )
    high_intensity_count = sum(
        1
        for session in sessions
        if _number(session.get("training_effect_anaerobic")) >= 2.0
        or _number(session.get("training_effect_aerobic")) >= 4.0
    )
    summary_json = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "week_label": week.get("week_label"),
        "totals": {
            "workout_count": int(counts.get("total", len(sessions))),
            "distance_km": (
                _round_or_none(total_distance, 2) or 0.0
                if has_distance_bearing_session or not sessions
                else None
            ),
            "duration_min": _round_or_none(total_duration, 1) or 0.0,
        },
        "sports": sport_totals,
        "sessions": sessions,
        "strength_training": strength_training,
        "training_load": {
            "garmin_weekly_load": _round_or_none(training_load, 1) or 0.0,
            **load_metrics,
        },
        "data_quality": dict(week.get("data_quality") or {}),
        "risk_flags": list(week.get("risk_flags") or []),
        "next_week_plan_seed": _next_week_seed(
            deterministic_context.get("athlete_profile") or {},
            week_start,
        ),
    }
    return CompletedWeekSummary(
        week_start=week_start,
        week_end=week_end,
        summary_json=summary_json,
        metrics={
            "total_distance_km": summary_json["totals"]["distance_km"],
            "total_duration_min": summary_json["totals"]["duration_min"],
            "running_distance_km": running["distance_km"],
            "swimming_distance_km": swimming["distance_km"],
            "workout_count": summary_json["totals"]["workout_count"],
            "running_count": running["count"],
            "swimming_count": swimming["count"],
            "high_intensity_count": high_intensity_count,
            # Coach context intentionally does not infer run workout labels.
            # Keep this nullable rather than declaring every run a long run.
            "long_run_count": None,
            "training_load": summary_json["training_load"]["garmin_weekly_load"],
            "acute_load": load_metrics["acute_load"],
            "chronic_load": load_metrics["chronic_load"],
            "acute_chronic_ratio": load_metrics["acute_chronic_ratio"],
            "monotony": load_metrics["monotony"],
            "strain": load_metrics["strain"],
        },
    )
