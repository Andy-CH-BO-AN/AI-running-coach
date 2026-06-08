from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from src.preprocessing.coach_context_types import (
    CoachSession,
    CoachSessionCounts,
    CoachWeek,
    EvidenceFact,
    HrZoneDistribution,
    NextWeekDaySeed,
    NextWeekPlanSeed,
)
from src.preprocessing.coach_context_utils import (
    WEEKDAY_LABELS,
    _format_week_label,
    _normalize_weekday,
    _parse_date,
    _round_or_none,
    _safe_float,
    _week_start_for,
)


def _risk_flags_for_week(week: Dict[str, Any], max_hr: Optional[float], baseline_load: Optional[float]) -> List[str]:
    flags = set()
    sessions = week["sessions"]
    running_distance = sum(session["distance_km"] for session in sessions if session.get("source_activity_type") == "running")
    if running_distance < 8 and sessions:
        flags.add("low_running_volume")

    for session in sessions:
        temp = _safe_float((session.get("environment") or {}).get("estimated_temp_c"))
        if temp is not None and temp >= 27:
            flags.add("heat_stress")
        avg_hr = _safe_float(session.get("avg_hr"))
        if session.get("type") == "long" and max_hr and avg_hr and avg_hr >= max_hr * 0.86:
            flags.add("high_intensity_long_run")

    load = _safe_float(week.get("derived_training_load")) or 0.0
    if baseline_load and load > baseline_load * 1.35 and load >= 80:
        flags.add("overreaching_risk")
    if "high_intensity_long_run" in flags or "overreaching_risk" in flags:
        flags.add("fatigue_risk")
    return sorted(flags)


def _build_week_session_counts(week_sessions: Sequence[CoachSession]) -> CoachSessionCounts:
    by_type: Dict[str, int] = {}
    by_source_activity_type: Dict[str, int] = {}
    for session in week_sessions:
        session_type = str(session.get("type") or "unknown")
        by_type[session_type] = by_type.get(session_type, 0) + 1

        source_activity_type = session.get("source_activity_type")
        if source_activity_type:
            normalized_source = str(source_activity_type)
            by_source_activity_type[normalized_source] = by_source_activity_type.get(normalized_source, 0) + 1

    return {
        "total": len(week_sessions),
        "by_type": dict(sorted(by_type.items())),
        "by_source_activity_type": dict(sorted(by_source_activity_type.items())),
    }


def _build_12week_summary(
    sessions: Sequence[CoachSession],
    today: date,
) -> List[Dict[str, Any]]:
    """Build 12-week weekly aggregates for sparkline trend charts on the dashboard."""
    current_week_start = _week_start_for(today)
    weeks: List[Dict[str, Any]] = []
    for offset in range(12):
        week_start = current_week_start - timedelta(days=offset * 7)
        week_end = week_start + timedelta(days=6)
        week_sessions = [
            s for s in sessions
            if (sd := _parse_date(s.get("date"))) is not None
            and week_start <= sd <= week_end
        ]
        weeks.append({
            "week_start": week_start.isoformat(),
            "week_label": _format_week_label(week_start),
            "derived_total_distance_km": _round_or_none(sum(s["distance_km"] for s in week_sessions), 2) or 0.0,
            "derived_training_load": _round_or_none(sum(s["training_load"] for s in week_sessions), 1) or 0.0,
            "sessions_count": len(week_sessions),
        })
    return list(reversed(weeks))  # chronological: oldest first


def _build_weekly_analysis(
    sessions: Sequence[CoachSession],
    today: date,
    max_hr: Optional[float],
) -> List[CoachWeek]:
    current_week_start = _week_start_for(today)
    buckets: List[CoachWeek] = []
    for offset in range(4):
        week_start = current_week_start - timedelta(days=offset * 7)
        week_end = week_start + timedelta(days=6)
        week_sessions = [
            session
            for session in sessions
            if (session_date := _parse_date(session.get("date"))) is not None
            and week_start <= session_date <= week_end
        ]
        week_sessions.sort(key=lambda session: (session.get("date") or "", str(session.get("activity_id") or "")))
        missing_fields = sorted(
            {
                field
                for session in week_sessions
                for field in (session.get("data_quality") or {}).get("missing_fields", [])
            }
        )
        derived = {
            "derived_total_distance_km": _round_or_none(sum(session["distance_km"] for session in week_sessions), 2) or 0.0,
            "derived_total_duration_min": _round_or_none(sum(session["duration_min"] for session in week_sessions), 1) or 0.0,
            "derived_training_load": _round_or_none(sum(session["training_load"] for session in week_sessions), 1) or 0.0,
        }
        buckets.append(
            {
                "week_label": _format_week_label(week_start),
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                **derived,
                "sessions": week_sessions,
                "session_counts": _build_week_session_counts(week_sessions),
                "data_quality": {
                    "status": "empty" if not week_sessions else "partial" if missing_fields else "complete",
                    "message": "無訓練紀錄"
                    if not week_sessions
                    else "部分資料不足"
                    if missing_fields
                    else "完整",
                    "missing_fields": missing_fields,
                },
                "risk_flags": [],
            }
        )

    nonzero_loads = [week["derived_training_load"] for week in buckets[1:] if week["derived_training_load"] > 0]
    baseline_load = sum(nonzero_loads) / len(nonzero_loads) if nonzero_loads else None
    for week in buckets:
        week["risk_flags"] = _risk_flags_for_week(week, max_hr=max_hr, baseline_load=baseline_load)
    return buckets


def _build_load_assessment(weekly_analysis: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    current_load = weekly_analysis[0]["derived_training_load"] if weekly_analysis else 0.0
    previous_loads = [week["derived_training_load"] for week in weekly_analysis[1:] if week["derived_training_load"] > 0]
    average_previous = sum(previous_loads) / len(previous_loads) if previous_loads else current_load
    lower = _round_or_none(average_previous * 0.8, 1) if average_previous else 0.0
    upper = _round_or_none(average_previous * 1.3, 1) if average_previous else 0.0

    if current_load == 0:
        status = "undertraining"
    elif upper and current_load > upper * 1.2:
        status = "overtraining"
    elif upper and current_load > upper:
        status = "overreaching"
    elif lower and current_load < lower:
        status = "undertraining"
    else:
        status = "optimal"

    return {
        "current_tss_weekly": _round_or_none(current_load, 1) or 0.0,
        "optimal_tss_range": {"min": lower, "max": upper},
        "status": status,
        "baseline_previous_3_weeks": _round_or_none(average_previous, 1) if average_previous else 0.0,
    }


def _build_next_week_seed(today: date, user_data: Dict[str, Any]) -> NextWeekPlanSeed:
    next_week_start = _week_start_for(today) + timedelta(days=7)
    available_days = {
        normalized
        for normalized in (_normalize_weekday(day) for day in user_data.get("available_training_days") or [])
        if normalized
    }
    long_days = {
        normalized
        for normalized in (_normalize_weekday(day) for day in user_data.get("preferred_long_training_days") or [])
        if normalized
    }
    days: List[NextWeekDaySeed] = []
    for offset, weekday in enumerate(WEEKDAY_LABELS):
        day = next_week_start + timedelta(days=offset)
        days.append(
            {
                "date": day.isoformat(),
                "day_of_week": weekday,
                "available_for_training": not available_days or weekday in available_days,
                "preferred_long_run_day": weekday in long_days,
            }
        )
    return {"week_start": next_week_start.isoformat(), "days": days}


def _build_pb_validation_seed(user_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    personal_records = user_data.get("pr_running") or {}
    if not isinstance(personal_records, dict):
        return []
    return [
        {
            "event": event,
            "raw_value": value,
            "source_path": f"user_data.pr_running.{event}",
        }
        for event, value in personal_records.items()
    ]


def _build_evidence_facts(
    weekly_analysis: Sequence[CoachWeek],
    hr_zone_distribution: HrZoneDistribution,
    load_assessment: Dict[str, Any],
) -> List[EvidenceFact]:
    facts: List[EvidenceFact] = []
    current_week = weekly_analysis[0] if weekly_analysis else None
    if current_week:
        facts.append(
            {
                "fact_id": "current_week_load",
                "label": "本週訓練負荷",
                "value": current_week["derived_training_load"],
                "unit": "TSS",
                "source_path": "deterministic_context.weekly_analysis[0].derived_training_load",
            }
        )
        for flag in current_week.get("risk_flags", []):
            facts.append(
                {
                    "fact_id": flag,
                    "label": flag,
                    "value": True,
                    "unit": None,
                    "source_path": "deterministic_context.weekly_analysis[0].risk_flags",
                }
            )

    zones = hr_zone_distribution.get("zones") or []
    high_intensity_pct = sum(
        _safe_float(zone.get("percentage")) or 0
        for zone in zones
        if zone.get("zone") in (4, 5)
    )
    facts.append(
        {
            "fact_id": "high_intensity_percentage",
            "label": "Z4-Z5 心率時間佔比",
            "value": _round_or_none(high_intensity_pct, 1) or 0.0,
            "unit": "%",
            "source_path": "deterministic_context.hr_zone_distribution.zones",
        }
    )
    facts.append(
        {
            "fact_id": "load_status_seed",
            "label": "訓練負荷狀態 seed",
            "value": load_assessment.get("status"),
            "unit": None,
            "source_path": "deterministic_context.load_assessment.status",
        }
    )
    return facts
