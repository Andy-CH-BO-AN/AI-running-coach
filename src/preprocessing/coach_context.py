from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import re
from typing import Any, Dict, List, Optional, Sequence

from src.preprocessing.coach_context_types import (
    CoachEnvironment,
    CoachSegment,
    CoachSession,
    CoachSessionCounts,
    CoachWeek,
    DeterministicCoachContext,
    EvidenceFact,
    HrZoneDistribution,
    NextWeekDaySeed,
    NextWeekPlanSeed,
)
from src.preprocessing.coach_context_utils import (
    WEEKDAY_LABELS,
    _average,
    _format_pace_minutes,
    _format_pace_seconds,
    _format_week_label,
    _normalize_activity_id,
    _normalize_weekday,
    _parse_date,
    _parse_pace_seconds,
    _resolve_today,
    _round_or_none,
    _safe_float,
    _sum_numbers,
    _week_start_for,
    _weighted_average,
)
ZONE_RANGE = range(1, 6)
ACTIVE_RUNNING_CADENCE_MIN = 120
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
PACE_ZONE_NAMES = {
    1: "恢復跑",
    2: "輕鬆有氧",
    3: "穩態/馬拉松配速",
    4: "乳酸閾值",
    5: "間歇/速度",
}
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


def _nested_get(payload: Dict[str, Any], path: Sequence[str]) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _get_any(payload: Dict[str, Any], *paths: str) -> Any:
    for path in paths:
        if path in payload:
            return payload[path]
        value = _nested_get(payload, path.split("."))
        if value is not None:
            return value
    return None


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


def _segment_from_split(split: Dict[str, Any]) -> CoachSegment:
    return {
        "segment_type": "lap",
        "split_index": split.get("split_index"),
        "distance_km": _round_or_none(split.get("distance"), 3),
        "duration_min": _round_or_none(split.get("duration"), 2),
        "avg_pace": _format_pace_minutes(split.get("pace")),
        "avg_hr": _round_or_none(split.get("average_heart_rate"), 0),
        "cadence": _round_or_none(split.get("avg_cadence"), 1),
        "stride_length_m": _round_or_none(_stride_length_to_meters(_safe_float(split.get("stride_length"))), 2),
        "temperature_c": _round_or_none(split.get("temperature"), 1),
        "note": None,
    }


def _build_segments(processed: Dict[str, Any]) -> List[CoachSegment]:
    splits = processed.get("splits")
    if not isinstance(splits, list):
        return []
    return [_segment_from_split(split) for split in splits if isinstance(split, dict)]


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
    segments = _build_segments(processed)

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
        "training_effect_aerobic": _training_effect(processed, "aerobic"),
        "training_effect_anaerobic": _training_effect(processed, "anaerobic"),
        "segments": segments,
        "environment": _build_environment(processed, raw),
        "coaching_note": None,
        "data_quality": {
            "status": "partial" if missing_fields else "complete",
            "missing_fields": missing_fields,
        },
    }


def _build_hr_zone_distribution(
    sessions: Sequence[CoachSession],
    processed_by_id: Dict[str, Dict[str, Any]],
) -> HrZoneDistribution:
    minutes_by_zone: Dict[int, float] = {zone: 0.0 for zone in ZONE_RANGE}
    for session in sessions:
        processed = processed_by_id.get(_normalize_activity_id(session.get("activity_id")), {})
        for zone in ZONE_RANGE:
            zone_seconds = _safe_float(
                _get_any(
                    processed,
                    f"advanced_metrics.hr_zones.hr_zone_{zone}",
                    f"advanced_metrics.hr_zones.hr_zone_{zone}",
                )
            )
            minutes_by_zone[zone] += (zone_seconds or 0.0) / 60

    total_minutes = sum(minutes_by_zone.values())
    percentages = {
        zone: _round_or_none(minutes / total_minutes * 100, 1) if total_minutes > 0 else 0.0
        for zone, minutes in minutes_by_zone.items()
    }
    if total_minutes > 0:
        rounding_delta = _round_or_none(100.0 - sum(percentages.values()), 1)
        if rounding_delta:
            largest_zone = max(minutes_by_zone, key=minutes_by_zone.get)
            percentages[largest_zone] = _round_or_none(percentages[largest_zone] + rounding_delta, 1) or 0.0

    easy_pct = percentages[1] + percentages[2]
    hard_pct = percentages[4] + percentages[5]
    return {
        "period_weeks": 4,
        "zones": [
            {
                "zone": zone,
                "name": ZONE_NAMES[zone],
                "minutes": _round_or_none(minutes_by_zone[zone], 1) or 0.0,
                "percentage": percentages[zone],
            }
            for zone in ZONE_RANGE
        ],
        "total_minutes": _round_or_none(total_minutes, 1) or 0.0,
        "is_polarized": easy_pct >= 75 and hard_pct <= 20 if total_minutes > 0 else False,
    }


def _build_power_zone_distribution(
    sessions: Sequence[CoachSession],
    processed_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    minutes_by_zone: Dict[int, float] = {zone: 0.0 for zone in ZONE_RANGE}
    for session in sessions:
        processed = processed_by_id.get(_normalize_activity_id(session.get("activity_id")), {})
        for zone in ZONE_RANGE:
            zone_seconds = _safe_float(
                _get_any(
                    processed,
                    f"advanced_metrics.power_zones.power_zone_{zone}",
                    f"advanced_metrics.power_zones.power_zone_{zone}",
                )
            )
            minutes_by_zone[zone] += (zone_seconds or 0.0) / 60

    total_minutes = sum(minutes_by_zone.values())
    percentages = {
        zone: _round_or_none(minutes / total_minutes * 100, 1) if total_minutes > 0 else 0.0
        for zone, minutes in minutes_by_zone.items()
    }
    if total_minutes > 0:
        rounding_delta = _round_or_none(100.0 - sum(percentages.values()), 1)
        if rounding_delta:
            largest_zone = max(minutes_by_zone, key=minutes_by_zone.get)
            percentages[largest_zone] = _round_or_none(percentages[largest_zone] + rounding_delta, 1) or 0.0

    return {
        "period_weeks": 4,
        "zones": [
            {
                "zone": zone,
                "name": POWER_ZONE_NAMES[zone],
                "minutes": _round_or_none(minutes_by_zone[zone], 1) or 0.0,
                "percentage": percentages[zone],
            }
            for zone in ZONE_RANGE
        ],
        "total_minutes": _round_or_none(total_minutes, 1) or 0.0,
    }


def _resolve_resting_heart_rate(
    user_data: Dict[str, Any],
    sessions: Sequence[CoachSession],
) -> tuple[float | None, str | None]:
    resting_hr = _safe_float(
        _get_any(
            user_data,
            "resting_heart_rate",
            "restingHeartRate",
            "userData.restingHeartRate",
        )
    )
    if resting_hr and 30 <= resting_hr <= 100:
        return resting_hr, str(user_data.get("resting_heart_rate_source") or "garmin")

    low_activity_hr_values = [
        avg_hr
        for session in sessions
        if session.get("type") not in {"interval", "tempo", "race", "swim", "rest"}
        for avg_hr in [_safe_float(session.get("avg_hr"))]
        if avg_hr and 80 <= avg_hr <= 170
    ]
    if not low_activity_hr_values:
        return None, None

    estimated = min(max(min(low_activity_hr_values) - 40, 40), 70)
    return estimated, "estimated_from_lowest_activity_avg_hr"


def _build_pace_zones(
    user_data: Dict[str, Any],
    resting_heart_rate: float | None = None,
) -> List[Dict[str, Any]]:
    threshold_seconds = _parse_pace_seconds(user_data.get("lactate_threshold_pace"))
    max_hr = _safe_float(user_data.get("max_heart_rate"))
    resting_hr = resting_heart_rate
    hrr = max_hr - resting_hr if max_hr and resting_hr and max_hr > resting_hr else None

    pace_offsets = {
        1: (135, 90),
        2: (90, 45),
        3: (45, 10),
        4: (10, -20),
        5: (-20, None),
    }
    hrr_ranges = {
        1: (0.60, 0.70),
        2: (0.70, 0.80),
        3: (0.80, 0.87),
        4: (0.87, 0.94),
        5: (0.94, 1.00),
    }

    zones: List[Dict[str, Any]] = []
    for zone in ZONE_RANGE:
        slow_offset, fast_offset = pace_offsets[zone]
        pace_min = _format_pace_seconds(threshold_seconds + slow_offset) if threshold_seconds else None
        pace_max = _format_pace_seconds(threshold_seconds + fast_offset) if threshold_seconds and fast_offset is not None else None
        hr_min = hr_max = None
        if hrr is not None and resting_hr is not None:
            hr_min = _round_or_none(resting_hr + hrr * hrr_ranges[zone][0], 0)
            hr_max = _round_or_none(resting_hr + hrr * hrr_ranges[zone][1], 0)
        zones.append(
            {
                "zone": zone,
                "name": PACE_ZONE_NAMES[zone],
                "pace_min": pace_min,
                "pace_max": pace_max,
                "hr_min": hr_min,
                "hr_max": hr_max,
                "is_reasonable": threshold_seconds is not None,
                "note": "快端無上限，畫面應以「快於」呈現。" if zone == 5 else None,
            }
        )
    return zones


def _build_physio_metrics(
    user_data: Dict[str, Any],
    sessions: Sequence[CoachSession] | None = None,
) -> Dict[str, Any]:
    resting_hr, resting_hr_source = _resolve_resting_heart_rate(user_data, sessions or [])
    return {
        "vo2max": {
            "value": _round_or_none(user_data.get("vo2max_running") or user_data.get("vo2max"), 1),
            "unit": "ml/kg/min",
        },
        "lactate_threshold": {
            "heart_rate": {
                "value": _round_or_none(user_data.get("lactate_threshold_heart_rate"), 0),
                "unit": "bpm",
            },
            "pace": {
                "value": _format_pace_minutes(user_data.get("lactate_threshold_pace")),
                "unit": "/km",
            },
        },
        "max_heart_rate": {"value": _round_or_none(user_data.get("max_heart_rate"), 0), "unit": "bpm"},
        "resting_heart_rate": {
            "value": _round_or_none(resting_hr, 0),
            "unit": "bpm",
            "source": resting_hr_source,
        },
        "pace_zones": _build_pace_zones(user_data, resting_hr),
    }


def _is_active_running_segment(split: Dict[str, Any]) -> bool:
    cadence = _safe_float(split.get("avg_cadence"))
    return cadence is not None and cadence >= ACTIVE_RUNNING_CADENCE_MIN


def _active_running_segments(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    for record in records:
        splits = record.get("splits")
        if not isinstance(splits, list):
            continue
        segments.extend(
            split
            for split in splits
            if isinstance(split, dict) and _is_active_running_segment(split)
        )
    return segments


def _metric_from_active_segments(
    segments: Sequence[Dict[str, Any]],
    metric: str,
    digits: int = 1,
) -> Optional[float]:
    return _weighted_average(
        (
            (split.get(metric), split.get("duration"))
            for split in segments
            if _safe_float(split.get(metric)) is not None
        ),
        digits=digits,
    )


def _stride_length_to_meters(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return value / 100 if value > 10 else value


def _stride_from_active_segments(segments: Sequence[Dict[str, Any]]) -> Optional[float]:
    return _weighted_average(
        (
            (_stride_length_to_meters(_safe_float(split.get("stride_length"))), split.get("duration"))
            for split in segments
            if _safe_float(split.get("stride_length")) is not None
        ),
        digits=2,
    )


def _mechanics_assessment(key: str, value: Any) -> Optional[str]:
    number = _safe_float(value)
    if number is None:
        return "資料不足，暫不解讀。"
    if key == "cadence_avg":
        if number >= 170:
            return "有效跑步段步頻落在合理範圍，休息段已排除。"
        if number >= 160:
            return "有效跑步段步頻略低，可用 strides 與短坡衝刺提升節奏。"
        return "有效跑步段步頻偏低，建議先檢查是否受疲勞或慢跑配速影響。"
    if key == "ground_contact_ms":
        if number <= 250:
            return "觸地時間良好，顯示支撐期控制穩定。"
        if number <= 280:
            return "觸地時間尚可，可透過短衝與彈跳訓練再縮短。"
        return "觸地時間偏長，可能代表推蹬效率或疲勞狀態需要留意。"
    if key == "vertical_oscillation_cm":
        if number <= 8.5:
            return "垂直振幅良好，跑動能量沒有明顯向上浪費。"
        if number <= 10:
            return "垂直振幅尚可，需留意速度提升時是否過度彈跳。"
        return "垂直振幅偏高，建議用節奏跑與核心穩定降低上下起伏。"
    if key == "stride_length_m":
        if number >= 1.2:
            return "有效跑步段步幅充足，速度段已有明顯推進。"
        if number >= 0.9:
            return "有效跑步段步幅合理，可隨速度課逐步提升推進效率。"
        return "有效跑步段步幅偏短，建議搭配加速跑與臀腿力量訓練。"
    return None


def _mechanics_tips(mechanics: Dict[str, Any]) -> List[str]:
    tips: List[str] = []
    cadence = _safe_float((mechanics.get("cadence_avg") or {}).get("value"))
    ground_contact = _safe_float((mechanics.get("ground_contact_ms") or {}).get("value"))
    stride = _safe_float((mechanics.get("stride_length_m") or {}).get("value"))

    if cadence is not None and cadence < 170:
        tips.append("在輕鬆跑後加入 4-6 組 strides，讓有效跑步段步頻自然接近 170+ spm。")
    if ground_contact is not None and ground_contact > 260:
        tips.append("加入短坡衝刺、跳繩或快速觸地 drills，改善支撐期反應。")
    if stride is not None and stride < 0.9:
        tips.append("用加速跑與臀腿力量訓練提升有效步幅，不要用跨大步硬拉配速。")

    if not tips:
        tips.append("維持目前有效跑步段步頻與步幅，優先把品質穩定複製到節奏跑與間歇主課表。")
    return tips[:3]


def _build_running_mechanics(sessions: Sequence[Dict[str, Any]], processed_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    running_records = [
        processed_by_id.get(_normalize_activity_id(session.get("activity_id")), {})
        for session in sessions
        if session.get("source_activity_type") == "running"
    ]
    active_segments = _active_running_segments(running_records)

    cadence = _metric_from_active_segments(active_segments, "avg_cadence", 1) or _average(
        (_get_any(record, "advanced_metrics.avg_cadence") for record in running_records),
        1,
    )
    ground_contact = _metric_from_active_segments(active_segments, "ground_contact_time", 1) or _average(
        (_get_any(record, "advanced_metrics.ground_contact_time") for record in running_records),
        1,
    )
    vertical_oscillation = _metric_from_active_segments(active_segments, "vertical_oscillation", 1) or _average(
        (_get_any(record, "advanced_metrics.vertical_oscillation") for record in running_records),
        1,
    )
    stride_length_m = _stride_from_active_segments(active_segments)
    if stride_length_m is None:
        stride_length_cm = _average((_get_any(record, "advanced_metrics.stride_length") for record in running_records), 1)
        stride_length_m = _round_or_none(_stride_length_to_meters(stride_length_cm), 2)

    score_inputs = [value for value in (cadence, ground_contact, vertical_oscillation, stride_length_m) if value is not None]
    economy_score = None
    if score_inputs:
        score = 75
        if cadence is not None:
            score += 8 if 170 <= cadence <= 185 else -6
        if ground_contact is not None:
            score += 7 if ground_contact <= 260 else -6
        if vertical_oscillation is not None:
            score += 5 if vertical_oscillation <= 8.5 else -4
        economy_score = max(0, min(100, _round_or_none(score, 0) or 0))

    return {
        "cadence_avg": {"value": cadence, "unit": "spm"},
        "ground_contact_ms": {"value": ground_contact, "unit": "ms"},
        "vertical_oscillation_cm": {"value": vertical_oscillation, "unit": "cm"},
        "stride_length_m": {"value": stride_length_m, "unit": "m"},
        "running_economy_score": economy_score,
    }


def _enforce_running_mechanics(
    result: Dict[str, Any],
    deterministic_context: Dict[str, Any],
) -> None:
    context_mechanics = deterministic_context.get("running_mechanics") or {}
    if not context_mechanics:
        return

    ai_mechanics = result.get("running_mechanics") or {}
    mechanics = _overlay_deterministic(ai_mechanics, context_mechanics)
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


def _build_cross_training(sessions: Sequence[Dict[str, Any]], processed_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    swim_records = [
        processed_by_id.get(_normalize_activity_id(session.get("activity_id")), {})
        for session in sessions
        if session.get("type") == "swim"
    ]
    bike_records = [
        processed_by_id.get(_normalize_activity_id(session.get("activity_id")), {})
        for session in sessions
        if session.get("type") == "bike"
    ]
    return {
        "swimming": {
            "sessions_count": len(swim_records),
            "avg_swolf": _average((_get_any(record, "advanced_metrics.avg_swolf") for record in swim_records), 1),
            "avg_stroke_rate": _average((_get_any(record, "advanced_metrics.avg_stroke_cadence") for record in swim_records), 1),
        },
        "cycling": {
            "sessions_count": len(bike_records),
            "avg_power_w": _average((_get_any(record, "advanced_metrics.power_avg") for record in bike_records), 0),
            "avg_cadence": _average((_get_any(record, "advanced_metrics.avg_cadence") for record in bike_records), 1),
        },
    }


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


def _overlay_deterministic(ai_value: Any, deterministic_value: Any) -> Any:
    if isinstance(ai_value, dict) and isinstance(deterministic_value, dict):
        merged = deepcopy(ai_value)
        for key, value in deterministic_value.items():
            merged[key] = _overlay_deterministic(merged.get(key), value)
        return merged
    return deepcopy(deterministic_value)


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
    session["segments"] = [
        _output_segment(segment, ai_segments[index] if index < len(ai_segments) and isinstance(ai_segments[index], dict) else None)
        for index, segment in enumerate(context_segments)
        if isinstance(segment, dict)
    ]
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


def _weekly_session_references(report: Dict[str, Any]) -> tuple[Dict[str, tuple[str, Dict[str, Any]]], Dict[tuple[Any, Any, Any, Any], tuple[str, Dict[str, Any]]]]:
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
        result["physio_metrics"] = _overlay_deterministic(
            result.get("physio_metrics") or {},
            deterministic_context["physio_metrics"],
        )

    _enforce_running_mechanics(result, deterministic_context)

    if deterministic_context.get("cross_training"):
        result["cross_training"] = _overlay_deterministic(
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


def build_deterministic_coach_context(
    processed_data: List[Dict[str, Any]],
    user_data: Optional[Dict[str, Any]] = None,
    raw_activities: Optional[List[Dict[str, Any]]] = None,
    today: Any = None,
) -> DeterministicCoachContext:
    """Build deterministic coach context from local data before Gemini analysis."""

    user_data = user_data or {}
    raw_lookup = _build_raw_lookup(raw_activities)
    resolved_today = _resolve_today(today, processed_data)
    max_hr = _safe_float(user_data.get("max_heart_rate"))

    sessions = [
        _build_session(processed, raw_lookup=raw_lookup, max_hr=max_hr)
        for processed in processed_data
    ]
    processed_by_id = {
        _normalize_activity_id(processed.get("activity_id")): processed
        for processed in processed_data
    }
    weekly_analysis = _build_weekly_analysis(sessions, today=resolved_today, max_hr=max_hr)
    four_week_sessions = [
        session
        for week in weekly_analysis
        for session in week["sessions"]
    ]
    hr_zone_distribution = _build_hr_zone_distribution(four_week_sessions, processed_by_id)
    power_zone_distribution = _build_power_zone_distribution(four_week_sessions, processed_by_id)
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
        "physio_metrics": _build_physio_metrics(user_data, sessions),
        "pb_validation_seed": _build_pb_validation_seed(user_data),
        "weekly_analysis": weekly_analysis,
        "hr_zone_distribution": hr_zone_distribution,
        "power_zone_distribution": power_zone_distribution,
        "running_mechanics": _build_running_mechanics(four_week_sessions, processed_by_id),
        "cross_training": _build_cross_training(four_week_sessions, processed_by_id),
        "load_assessment": load_assessment,
        "next_week_plan_seed": _build_next_week_seed(resolved_today, user_data),
        "twelve_week_summary": _build_12week_summary(sessions, today=resolved_today),
        "evidence_facts": _build_evidence_facts(
            weekly_analysis=weekly_analysis,
            hr_zone_distribution=hr_zone_distribution,
            load_assessment=load_assessment,
        ),
    }
