from __future__ import annotations

from typing import Any, List, Optional

from src.preprocessing.activity_window import NormalizedActivity, NormalizedSegment
from src.preprocessing.coach_context_types import (
    CoachEnvironment,
    CoachSegment,
    CoachSession,
)
from src.preprocessing.coach_context_utils import (
    _format_pace_minutes,
    _round_or_none,
    _safe_float,
)


def _is_running_source_activity(source_activity_type: Optional[str]) -> bool:
    return (source_activity_type or "").lower() == "running"


def _is_swimming_source_activity(source_activity_type: Optional[str]) -> bool:
    return (source_activity_type or "").lower() in {"swimming", "lap_swimming"}


def _pace_seconds_per_100m(
    duration_min: Any,
    distance_km: Any,
) -> Optional[int]:
    """Calculate an aggregate swimming pace from deterministic context facts."""

    duration = _safe_float(duration_min)
    distance = _safe_float(distance_km)
    if duration is None or distance is None or duration < 0 or distance <= 0:
        return None
    return round(duration * 60 / (distance * 10))


def _segment_from_normalized(
    split: NormalizedSegment,
    *,
    include_running_metrics: bool,
    include_swimming_timing: bool,
) -> CoachSegment:
    segment: CoachSegment = {
        "segment_type": "rest"
        if include_swimming_timing and split.interval_type == "rest"
        else "lap",
        "split_index": split.split_index,
        "distance_km": _round_or_none(split.distance_km, 3),
        "duration_min": _round_or_none(split.duration_min, 2),
        "avg_pace": _format_pace_minutes(split.pace_formatted or split.pace_value),
        "speed_kmh": _round_or_none(split.speed_kmh, 1),
        "avg_hr": _round_or_none(split.avg_hr_bpm, 0),
        "temperature_c": _round_or_none(split.temperature_c, 1),
        "note": None,
    }
    if include_running_metrics:
        segment["cadence"] = _round_or_none(
            split.processed_avg_cadence_spm,
            1,
        )
        segment["stride_length_m"] = _round_or_none(split.stride_length_m, 2)
    if include_swimming_timing:
        elapsed_duration = _round_or_none(split.elapsed_duration_min, 4)
        if elapsed_duration is not None:
            segment["elapsed_duration_min"] = elapsed_duration
    return segment


def _build_segments(activity: NormalizedActivity) -> List[CoachSegment]:
    include_running_metrics = _is_running_source_activity(activity.activity_type)
    include_swimming_timing = _is_swimming_source_activity(activity.activity_type)
    return [
        _segment_from_normalized(
            split,
            include_running_metrics=include_running_metrics,
            include_swimming_timing=include_swimming_timing,
        )
        for split in activity.segments
    ]


def _build_environment(activity: NormalizedActivity) -> CoachEnvironment:
    temp = _round_or_none(activity.temperature_c, 1)
    humidity = _round_or_none(activity.humidity_pct, 0)
    hr_impact = None
    if temp is not None and temp >= 27:
        hr_impact = f"{temp:g}°C 高溫環境，心率可能較涼爽條件偏高。"
    return {
        "estimated_temp_c": temp,
        "humidity_pct": humidity,
        "hr_impact": hr_impact,
    }


def _build_session(activity: NormalizedActivity) -> CoachSession:
    distance = (
        round(activity.distance_km, 2)
        if activity.distance_km is not None
        else None
    )
    duration = _round_or_none(activity.duration_min, 1)
    load = _round_or_none(activity.training_load, 1)
    avg_hr = _round_or_none(activity.avg_hr_bpm, 0)
    avg_pace = _format_pace_minutes(
        activity.processed_performance_formatted
        or activity.processed_performance_value
    )
    missing_fields = [
        field_name
        for field_name, value in (
            ("distance_km", distance),
            ("duration_min", duration),
            ("training_load", load),
        )
        if value is None
    ]

    source_activity_type = activity.activity_type or None
    include_training_effect = activity.processed_activity_type == "running"
    session: CoachSession = {
        "activity_id": activity.activity_id,
        "date": activity.date,
        "source_activity_type": source_activity_type,
        "distance_km": distance if distance is not None else 0,
        "duration_min": duration if duration is not None else 0,
        "training_load": load if load is not None else 0,
        "avg_hr": avg_hr,
        "avg_pace": avg_pace,
        "training_effect_aerobic": _round_or_none(
            activity.training_effect_aerobic, 1
        ) if include_training_effect else None,
        "training_effect_anaerobic": _round_or_none(
            activity.training_effect_anaerobic, 1
        ) if include_training_effect else None,
        "segments": _build_segments(activity),
        "environment": _build_environment(activity),
        "coaching_note": None,
        "data_quality": {
            "status": "partial" if missing_fields else "complete",
            "missing_fields": missing_fields,
        },
    }
    if _is_swimming_source_activity(source_activity_type):
        elapsed_duration = _round_or_none(activity.elapsed_duration_min, 4)
        swim_duration = _round_or_none(activity.moving_duration_min, 4)
        rest_duration = _round_or_none(activity.rest_duration_min, 4)
        swim_timings = {
            "elapsed_duration_min": elapsed_duration,
            "swim_duration_min": swim_duration,
            "rest_duration_min": rest_duration,
            "elapsed_pace_seconds_per_100m": _pace_seconds_per_100m(
                elapsed_duration,
                distance,
            ),
        }
        if swim_duration is not None:
            swim_timings["swim_pace_seconds_per_100m"] = (
                _pace_seconds_per_100m(swim_duration, distance)
            )
        session.update(
            (key, value)
            for key, value in swim_timings.items()
            if value is not None
        )
    return session
