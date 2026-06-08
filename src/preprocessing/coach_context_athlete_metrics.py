from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from src.preprocessing.coach_context_types import CoachSession
from src.preprocessing.coach_context_utils import (
    _average,
    _format_pace_minutes,
    _format_pace_seconds,
    _get_any,
    _normalize_activity_id,
    _parse_pace_seconds,
    _round_or_none,
    _safe_float,
    _stride_length_to_meters,
    _weighted_average,
)

ZONE_RANGE = range(1, 6)
ACTIVE_RUNNING_CADENCE_MIN = 120
PACE_ZONE_NAMES = {
    1: "恢復跑",
    2: "輕鬆有氧",
    3: "穩態/馬拉松配速",
    4: "乳酸閾值",
    5: "間歇/速度",
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
