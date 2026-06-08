from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List, Optional, Sequence

from src.preprocessing.coach_context_athlete_metrics import (
    _mechanics_assessment,
    _mechanics_tips,
)
from src.preprocessing.coach_context_sessions import _is_running_session_type
from src.preprocessing.coach_context_utils import (
    _normalize_activity_id,
    _round_or_none,
)

WEEKLY_TOTAL_KEYS = {
    "total_distance_km",
    "total_duration_min",
    "training_load",
    "derived_total_distance_km",
    "derived_total_duration_min",
    "derived_training_load",
}
SESSION_OUTPUT_KEYS = (
    "activity_id",
    "date",
    "type",
    "source_activity_type",
    "distance_km",
    "duration_min",
    "training_load",
    "avg_hr",
    "avg_pace",
    "training_effect_aerobic",
    "training_effect_anaerobic",
    "segments",
    "environment",
    "coaching_note",
)
SEGMENT_OUTPUT_KEYS = (
    "segment_type",
    "distance_km",
    "avg_pace",
    "avg_hr",
    "cadence",
    "stride_length_m",
    "note",
)


def overlay_deterministic(ai_value: Any, deterministic_value: Any) -> Any:
    if isinstance(ai_value, dict) and isinstance(deterministic_value, dict):
        merged = deepcopy(ai_value)
        for key, value in deterministic_value.items():
            merged[key] = overlay_deterministic(merged.get(key), value)
        return merged
    return deepcopy(deterministic_value)


def _enforce_running_mechanics(
    result: Dict[str, Any],
    deterministic_context: Dict[str, Any],
) -> None:
    context_mechanics = deterministic_context.get("running_mechanics") or {}
    if not context_mechanics:
        return

    ai_mechanics = result.get("running_mechanics") or {}
    mechanics = overlay_deterministic(ai_mechanics, context_mechanics)
    for key in (
        "cadence_avg",
        "ground_contact_ms",
        "vertical_oscillation_cm",
        "stride_length_m",
    ):
        if isinstance(mechanics.get(key), dict):
            mechanics[key]["assessment"] = _mechanics_assessment(key, mechanics[key].get("value"))
    mechanics["improvement_tips"] = _mechanics_tips(mechanics)

    result["running_mechanics"] = mechanics


def _session_lookup(sessions: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        _normalize_activity_id(session.get("activity_id")): session
        for session in sessions
        if isinstance(session, dict)
    }


def _output_segment(
    context_segment: Dict[str, Any],
    ai_segment: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    segment = {key: deepcopy(context_segment.get(key)) for key in SEGMENT_OUTPUT_KEYS}
    if ai_segment and segment.get("note") in (None, "") and ai_segment.get("note"):
        segment["note"] = ai_segment.get("note")
    return segment


def _output_session(
    context_session: Dict[str, Any],
    ai_session: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    session = {key: deepcopy(context_session.get(key)) for key in SESSION_OUTPUT_KEYS}
    if ai_session and ai_session.get("coaching_note"):
        session["coaching_note"] = ai_session.get("coaching_note")

    ai_segments = ai_session.get("segments") if isinstance(ai_session, dict) else []
    if not isinstance(ai_segments, list):
        ai_segments = []
    context_segments = context_session.get("segments") or []
    include_running_metrics = _is_running_session_type(context_session.get("type"))
    output_segments: List[Dict[str, Any]] = []
    for index, segment in enumerate(context_segments):
        if not isinstance(segment, dict):
            continue
        output_segment = _output_segment(
            segment,
            ai_segments[index] if index < len(ai_segments) and isinstance(ai_segments[index], dict) else None,
        )
        if not include_running_metrics:
            output_segment.pop("cadence", None)
            output_segment.pop("stride_length_m", None)
        output_segments.append(output_segment)
    session["segments"] = output_segments
    return session


def _enforce_weekly_analysis(
    report: Dict[str, Any],
    deterministic_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    ai_weeks = {
        week.get("week_start"): week
        for week in report.get("weekly_analysis", [])
        if isinstance(week, dict)
    }
    enforced_weeks: List[Dict[str, Any]] = []
    for context_week in deterministic_context.get("weekly_analysis", []):
        if not isinstance(context_week, dict):
            continue
        ai_week = ai_weeks.get(context_week.get("week_start"), {})
        week = deepcopy(ai_week) if isinstance(ai_week, dict) else {}
        for key in WEEKLY_TOTAL_KEYS:
            week.pop(key, None)

        ai_sessions = _session_lookup(week.get("sessions") or [])
        week["week_label"] = context_week.get("week_label")
        week["week_start"] = context_week.get("week_start")
        week.setdefault("key_observation", "")
        week.setdefault("weekly_assessment", "")
        week.setdefault("weekly_recommendation", "")
        raw_focuses = week.get("intensity_focuses")
        if not isinstance(raw_focuses, list):
            raw_focuses = []
        normalized_focuses = []
        for item in raw_focuses[:2]:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized_focuses.append(
                        {
                            "dimension": "intensity",
                            "headline": "強度重點",
                            "analysis": text,
                        }
                    )
                continue
            if not isinstance(item, dict):
                continue

            analysis = str(item.get("analysis") or item.get("text") or "").strip()
            if not analysis:
                continue
            normalized_focuses.append(
                {
                    "dimension": str(item.get("dimension") or "intensity"),
                    "headline": str(item.get("headline") or "強度重點").strip() or "強度重點",
                    "analysis": analysis,
                }
            )
        week["intensity_focuses"] = normalized_focuses
        raw_cross_training_focus = week.get("cross_training_focus")
        if isinstance(raw_cross_training_focus, dict):
            cross_analysis = str(raw_cross_training_focus.get("analysis") or "").strip()
            if cross_analysis:
                week["cross_training_focus"] = {
                    "activity_id": raw_cross_training_focus.get("activity_id"),
                    "headline": str(raw_cross_training_focus.get("headline") or "交叉訓練重點").strip()
                    or "交叉訓練重點",
                    "analysis": cross_analysis,
                }
            else:
                week["cross_training_focus"] = None
        else:
            week["cross_training_focus"] = None
        week["risk_flags"] = deepcopy(context_week.get("risk_flags") or [])
        week["sessions"] = [
            _output_session(context_session, ai_sessions.get(_normalize_activity_id(context_session.get("activity_id"))))
            for context_session in context_week.get("sessions", [])
            if isinstance(context_session, dict)
        ]
        enforced_weeks.append(week)
    return enforced_weeks


def _enforce_next_week_plan(
    report: Dict[str, Any],
    deterministic_context: Dict[str, Any],
) -> Dict[str, Any]:
    ai_plan = deepcopy(report.get("next_week_plan") or {})
    seed = deterministic_context.get("next_week_plan_seed") or {}
    ai_days = {
        day.get("date"): day
        for day in ai_plan.get("days", [])
        if isinstance(day, dict)
    }
    days: List[Dict[str, Any]] = []
    for seed_day in seed.get("days", []):
        if not isinstance(seed_day, dict):
            continue
        ai_day = deepcopy(ai_days.get(seed_day.get("date"), {}))
        ai_day["date"] = seed_day.get("date")
        ai_day["day_of_week"] = seed_day.get("day_of_week")
        ai_day.setdefault("session_type", "rest")
        ai_day.setdefault("title", "恢復日")
        ai_day.setdefault("description", "")
        ai_day.setdefault("distance_km", 0)
        ai_day.setdefault("duration_min", 0)
        ai_day.setdefault("intensity", "rest")
        ai_day.setdefault("key_workout", False)
        ai_day.setdefault("weather_consideration", "")
        days.append(ai_day)

    if days:
        ai_plan["week_start"] = seed.get("week_start")
        ai_plan["days"] = days
        ai_plan["total_distance_km"] = _round_or_none(sum(day.get("distance_km") or 0 for day in days), 2) or 0.0
    return ai_plan


def _session_identity(session: Dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (
        session.get("date"),
        session.get("type"),
        _round_or_none(session.get("distance_km"), 2),
        _round_or_none(session.get("duration_min"), 1),
    )


def _read_path_value(payload: Dict[str, Any], path: str) -> Any:
    current: Any = payload
    for segment in path.split("."):
        match = re.match(r"^([A-Za-z_]+)(?:\[(\d+)\])?$", segment)
        if not match:
            return None
        if not isinstance(current, dict):
            return None
        current = current.get(match.group(1))
        if match.group(2) is not None:
            if not isinstance(current, list):
                return None
            index = int(match.group(2))
            if index >= len(current):
                return None
            current = current[index]
    return current


def _weekly_session_references(
    report: Dict[str, Any],
) -> tuple[Dict[str, tuple[str, Dict[str, Any]]], Dict[tuple[Any, Any, Any, Any], tuple[str, Dict[str, Any]]]]:
    by_activity_id: Dict[str, tuple[str, Dict[str, Any]]] = {}
    by_identity: Dict[tuple[Any, Any, Any, Any], tuple[str, Dict[str, Any]]] = {}
    for week_index, week in enumerate(report.get("weekly_analysis") or []):
        if not isinstance(week, dict):
            continue
        for session_index, session in enumerate(week.get("sessions") or []):
            if not isinstance(session, dict):
                continue
            source_path = f"weekly_analysis[{week_index}].sessions[{session_index}]"
            activity_id = session.get("activity_id")
            if activity_id is not None:
                by_activity_id[_normalize_activity_id(activity_id)] = (source_path, session)
            by_identity[_session_identity(session)] = (source_path, session)
    return by_activity_id, by_identity


def _enforce_evidence_source_paths(report: Dict[str, Any]) -> None:
    by_activity_id, by_identity = _weekly_session_references(report)
    for evidence in report.get("evidence_links") or []:
        if not isinstance(evidence, dict):
            continue
        for session in evidence.get("supporting_sessions") or []:
            if not isinstance(session, dict):
                continue

            reference = None
            activity_id = session.get("activity_id")
            if activity_id is not None:
                reference = by_activity_id.get(_normalize_activity_id(activity_id))
            if reference is None:
                reference = by_identity.get(_session_identity(session))
            if reference is None:
                continue

            source_path, source_session = reference
            session["source_path"] = source_path
            for key in (
                "date",
                "type",
                "source_activity_type",
                "distance_km",
                "duration_min",
                "avg_hr",
                "avg_pace",
                "training_effect_aerobic",
                "training_effect_anaerobic",
                "activity_id",
            ):
                session[key] = deepcopy(source_session.get(key))


def _split_weekly_session_source_path(source_path: Any) -> tuple[str, str] | None:
    match = re.match(r"^(weekly_analysis\[\d+\]\.sessions\[\d+\])(?:\.(.+))?$", str(source_path or ""))
    if not match:
        return None
    return match.group(1), match.group(2) or ""


def _enforce_evidence_metric_source_paths(
    report: Dict[str, Any],
    original_report: Dict[str, Any] | None = None,
) -> None:
    by_activity_id, by_identity = _weekly_session_references(report)
    original_payload = original_report if isinstance(original_report, dict) else report
    for evidence in report.get("evidence_links") or []:
        if not isinstance(evidence, dict):
            continue
        for metric in evidence.get("supporting_metrics") or []:
            if not isinstance(metric, dict):
                continue

            source_path_parts = _split_weekly_session_source_path(metric.get("source_path"))
            if source_path_parts is None:
                continue

            original_session_path, field_suffix = source_path_parts
            reference = None

            activity_id = metric.get("activity_id")
            if activity_id is not None:
                reference = by_activity_id.get(_normalize_activity_id(activity_id))

            if reference is None:
                original_session = deepcopy(_read_path_value(original_payload, original_session_path) or {})
                if isinstance(original_session, dict):
                    reference = by_identity.get(_session_identity(original_session))

            if reference is None:
                continue

            session_source_path, _source_session = reference
            metric["source_path"] = (
                f"{session_source_path}.{field_suffix}" if field_suffix else session_source_path
            )


def enforce_deterministic_report_fields(
    report: Dict[str, Any],
    deterministic_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Overlay deterministic source-of-truth fields after AI analysis."""

    result = deepcopy(report) if isinstance(report, dict) else {}
    original_report = deepcopy(result)
    meta = deepcopy(result.get("meta") or {})
    context_meta = deterministic_context.get("meta") or {}
    for key in ("analysis_period_weeks", "today"):
        if key in context_meta:
            meta[key] = context_meta[key]
    result["meta"] = meta

    result["weekly_analysis"] = _enforce_weekly_analysis(result, deterministic_context)

    if deterministic_context.get("hr_zone_distribution"):
        hr_zone_distribution = deepcopy(result.get("hr_zone_distribution") or {})
        for key in ("period_weeks", "zones", "is_polarized"):
            if key in deterministic_context["hr_zone_distribution"]:
                hr_zone_distribution[key] = deepcopy(deterministic_context["hr_zone_distribution"][key])
        result["hr_zone_distribution"] = hr_zone_distribution

    if deterministic_context.get("power_zone_distribution"):
        power_zone_distribution = deepcopy(result.get("power_zone_distribution") or {})
        for key in ("period_weeks", "zones"):
            if key in deterministic_context["power_zone_distribution"]:
                power_zone_distribution[key] = deepcopy(deterministic_context["power_zone_distribution"][key])
        result["power_zone_distribution"] = power_zone_distribution

    if deterministic_context.get("physio_metrics"):
        result["physio_metrics"] = overlay_deterministic(
            result.get("physio_metrics") or {},
            deterministic_context["physio_metrics"],
        )

    _enforce_running_mechanics(result, deterministic_context)

    if deterministic_context.get("cross_training"):
        result["cross_training"] = overlay_deterministic(
            result.get("cross_training") or {},
            deterministic_context["cross_training"],
        )

    load_context = deterministic_context.get("load_assessment") or {}
    if load_context:
        load_assessment = deepcopy(result.get("load_assessment") or {})
        for key in ("current_tss_weekly", "optimal_tss_range", "status"):
            if key in load_context:
                load_assessment[key] = deepcopy(load_context[key])
        result["load_assessment"] = load_assessment

    result["next_week_plan"] = _enforce_next_week_plan(result, deterministic_context)
    _enforce_evidence_source_paths(result)
    _enforce_evidence_metric_source_paths(result, original_report=original_report)
    if deterministic_context.get("twelve_week_summary"):
        result["twelve_week_summary"] = deepcopy(deterministic_context["twelve_week_summary"])
    return result


_overlay_deterministic = overlay_deterministic
