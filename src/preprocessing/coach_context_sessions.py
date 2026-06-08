from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from src.preprocessing.coach_context_types import (
    CoachEnvironment,
    CoachSegment,
    CoachSession,
)
from src.preprocessing.coach_context_utils import (
    _average,
    _format_pace_minutes,
    _get_any,
    _normalize_activity_id,
    _round_or_none,
    _safe_float,
    _stride_length_to_meters,
    _sum_numbers,
)

RUNNING_SESSION_TYPES = {"easy", "tempo", "interval", "long", "race"}


def _build_raw_lookup(raw_activities: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for activity in raw_activities or []:
        lookup[_normalize_activity_id(activity.get("activity_id"))] = activity
    return lookup


def _activity_type(processed: Dict[str, Any], raw: Dict[str, Any]) -> str:
    return str(processed.get("type") or raw.get("type") or "").lower()


def _session_type(processed: Dict[str, Any], raw: Dict[str, Any], max_hr: Optional[float]) -> str:
    activity_type = _activity_type(processed, raw)
    if activity_type in {"swimming", "lap_swimming"}:
        return "swim"
    if activity_type == "cycling":
        return "bike"
    if activity_type != "running":
        return "easy"

    distance_km = _safe_float(processed.get("distance_km")) or _safe_float(raw.get("distance")) or 0.0
    duration_min = _safe_float(raw.get("duration")) or _duration_from_splits(processed.get("splits")) or 0.0
    avg_hr = _safe_float(processed.get("avg_hr")) or _safe_float(raw.get("average_heart_rate"))
    avg_pace = _safe_float(processed.get("performance_value")) or _safe_float(raw.get("average_pace"))

    if distance_km >= 12 or duration_min >= 75:
        return "long"
    if max_hr and avg_hr and avg_hr >= max_hr * 0.88:
        return "interval" if duration_min <= 25 or distance_km <= 5 else "tempo"
    if avg_pace and duration_min <= 20 and (distance_km <= 1.5 or (max_hr and avg_hr and avg_hr >= max_hr * 0.82)):
        return "interval"
    return "easy"


def _duration_from_splits(splits: Any) -> Optional[float]:
    if not isinstance(splits, list):
        return None
    duration = _sum_numbers((split.get("duration") for split in splits if isinstance(split, dict)), digits=2)
    return duration if duration > 0 else None


def _training_load(processed: Dict[str, Any], raw: Dict[str, Any]) -> Optional[float]:
    return _round_or_none(
        _get_any(
            processed,
            "advanced_metrics.training_load",
            "advanced_metrics.training_stress_score",
            "training_load",
        )
        or _get_any(raw.get("raw_data") or {}, "training_stress_score"),
        1,
    )


def _training_effect(processed: Dict[str, Any], metric: str) -> Optional[float]:
    return _round_or_none(
        _get_any(
            processed,
            f"advanced_metrics.training_effect.{metric}",
            f"advanced_metrics.training_effect.{metric}",
        ),
        1,
    )


def _is_running_session_type(session_type: Optional[str]) -> bool:
    return (session_type or "") in RUNNING_SESSION_TYPES


def _segment_from_split(split: Dict[str, Any], *, include_running_metrics: bool) -> CoachSegment:
    segment: CoachSegment = {
        "segment_type": "lap",
        "split_index": split.get("split_index"),
        "distance_km": _round_or_none(split.get("distance"), 3),
        "duration_min": _round_or_none(split.get("duration"), 2),
        "avg_pace": _format_pace_minutes(split.get("pace")),
        "avg_hr": _round_or_none(split.get("average_heart_rate"), 0),
        "temperature_c": _round_or_none(split.get("temperature"), 1),
        "note": None,
    }
    if include_running_metrics:
        segment["cadence"] = _round_or_none(split.get("avg_cadence"), 1)
        segment["stride_length_m"] = _round_or_none(_stride_length_to_meters(_safe_float(split.get("stride_length"))), 2)
    return segment


def _build_segments(processed: Dict[str, Any], session_type: Optional[str]) -> List[CoachSegment]:
    splits = processed.get("splits")
    if not isinstance(splits, list):
        return []
    include_running_metrics = _is_running_session_type(session_type)
    return [
        _segment_from_split(split, include_running_metrics=include_running_metrics)
        for split in splits
        if isinstance(split, dict)
    ]


def _temperature_values(processed: Dict[str, Any], raw: Dict[str, Any]) -> List[float]:
    values: List[float] = []
    raw_temp = _safe_float((raw.get("raw_data") or {}).get("temperature"))
    if raw_temp is not None:
        values.append(raw_temp)
    splits = processed.get("splits")
    if isinstance(splits, list):
        values.extend(
            temp
            for temp in (_safe_float(split.get("temperature")) for split in splits if isinstance(split, dict))
            if temp is not None
        )
    return values


def _build_environment(processed: Dict[str, Any], raw: Dict[str, Any]) -> CoachEnvironment:
    temp = _average(_temperature_values(processed, raw), digits=1)
    humidity = _round_or_none((raw.get("raw_data") or {}).get("humidity"), 0)
    hr_impact = None
    if temp is not None and temp >= 27:
        hr_impact = f"{temp:g}°C 高溫環境，心率可能較涼爽條件偏高。"
    return {
        "estimated_temp_c": temp,
        "humidity_pct": humidity,
        "hr_impact": hr_impact,
    }


def _build_session(
    processed: Dict[str, Any],
    raw_lookup: Dict[str, Dict[str, Any]],
    max_hr: Optional[float],
) -> CoachSession:
    activity_id = processed.get("activity_id")
    raw = raw_lookup.get(_normalize_activity_id(activity_id), {})

    distance = _round_or_none(processed.get("distance_km") if "distance_km" in processed else raw.get("distance"), 2)
    duration = _round_or_none(raw.get("duration") or _duration_from_splits(processed.get("splits")), 1)
    load = _training_load(processed, raw)
    avg_hr = _round_or_none(processed.get("avg_hr") or raw.get("average_heart_rate"), 0)
    avg_pace = _format_pace_minutes(processed.get("performance_formatted") or processed.get("performance_value") or raw.get("average_pace"))
    missing_fields = [
        field_name
        for field_name, value in (
            ("distance_km", distance),
            ("duration_min", duration),
            ("training_load", load),
        )
        if value is None
    ]

    session_type = _session_type(processed, raw, max_hr)
    segments = _build_segments(processed, session_type)
    aerobic_te = _training_effect(processed, "aerobic")
    anaerobic_te = _training_effect(processed, "anaerobic")
    environment = _build_environment(processed, raw)

    return {
        "activity_id": activity_id,
        "date": processed.get("date") or raw.get("date"),
        "type": session_type,
        "source_activity_type": _activity_type(processed, raw) or None,
        "distance_km": distance if distance is not None else 0,
        "duration_min": duration if duration is not None else 0,
        "training_load": load if load is not None else 0,
        "avg_hr": avg_hr,
        "avg_pace": avg_pace,
        "training_effect_aerobic": aerobic_te,
        "training_effect_anaerobic": anaerobic_te,
        "segments": segments,
        "environment": environment,
        "coaching_note": None,
        "data_quality": {
            "status": "partial" if missing_fields else "complete",
            "missing_fields": missing_fields,
        },
    }
