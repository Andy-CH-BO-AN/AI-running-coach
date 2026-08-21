"""Deterministic normalization for Garmin strength-training payloads.

Garmin has used more than one wrapper and field spelling for exercise sets.
This module deliberately keeps the accepted surface small: values must be
finite and non-negative and weight is usable only when its unit is explicit.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


_SUMMARY_WRAPPERS = (
    "summaryDTO",
    "activityInfo",
    "activity_info",
    "activityDTO",
    "activityDetail",
    "activityDetails",
    "summary",
)
_SET_WRAPPERS = (
    "exerciseSets",
    "exerciseSetDTOs",
    "exerciseSetSummaries",
    "exerciseSetSummariesDTO",
    "sets",
    "setDTOs",
)


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _summary_value(payload: Any, *keys: str) -> Any:
    if not isinstance(payload, Mapping):
        return None
    value = _first(payload, *keys)
    if value is not None:
        return value
    for wrapper in _SUMMARY_WRAPPERS:
        value = _summary_value(payload.get(wrapper), *keys)
        if value is not None:
            return value
    return None


def _nested_mapping(mapping: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _string_list(value: Any) -> list[str]:
    values = value if isinstance(value, Sequence) and not isinstance(value, str) else [value]
    return [item.strip() for item in values if isinstance(item, str) and item.strip()]


def _weight_kg(set_payload: Mapping[str, Any]) -> float | None:
    """Return weight in kg only for a source that explicitly names its unit."""
    nested = _nested_mapping(set_payload, "weight", "weightDTO", "weightInfo")
    raw = _first(set_payload, "weightKg", "weight_kg")
    unit: Any = "kg" if raw is not None else None
    if raw is None:
        raw = _first(set_payload, "weightInGrams", "weightGrams", "weight_g")
        unit = "g" if raw is not None else None
    if raw is None:
        raw = _first(set_payload, "weightLb", "weightLbs", "weight_lb")
        unit = "lb" if raw is not None else None
    if raw is None and nested:
        raw = _first(nested, "value", "weight", "amount")
        unit = _first(nested, "unit", "weightUnit", "unitKey")
    if raw is None:
        raw = _first(set_payload, "weight", "weightValue", "weightValueInUnit")
        unit = unit or _first(set_payload, "weightUnit", "unit", "weightUnitKey")
    value = _number(raw)
    if value is None or not isinstance(unit, str):
        return None
    normalized = unit.strip().lower()
    if normalized in {"kg", "kilogram", "kilograms"}:
        return round(value, 4)
    if normalized in {"g", "gram", "grams"}:
        return round(value / 1000, 4)
    if normalized in {"lb", "lbs", "pound", "pounds"}:
        return round(value * 0.45359237, 4)
    return None


def _set_payloads(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in _SET_WRAPPERS:
        value = payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            return _set_payloads(value)
    for wrapper in ("exerciseSetSummary", "exerciseSetSummaryDTO", "data"):
        nested = payload.get(wrapper)
        if nested is not None:
            parsed = _set_payloads(nested)
            if parsed:
                return parsed
    return []


def _normalize_set(set_payload: Mapping[str, Any], index: int) -> dict[str, Any]:
    exercise = _nested_mapping(set_payload, "exercise", "exerciseDTO", "exerciseInfo")
    names = _string_list(
        _first(set_payload, "exerciseNames", "exerciseName", "exercise_name")
        or _first(exercise, "exerciseNames", "exerciseName", "name")
    )
    category = _first(set_payload, "category", "exerciseCategory", "categoryName")
    if category is None:
        category = _first(exercise, "category", "exerciseCategory", "categoryName")
    set_type = _first(set_payload, "setType", "set_type", "type")
    normalized_type = str(set_type).strip().lower() if set_type is not None else "unknown"
    if normalized_type not in {"active", "rest"}:
        normalized_type = "unknown"
    duration = _first(set_payload, "durationSec", "durationSeconds", "duration", "timeSeconds")
    return {
        "set_index": _integer(_first(set_payload, "setIndex", "set_index", "index")) or index,
        "set_type": normalized_type,
        "exercise_names": names,
        "category": category.strip() if isinstance(category, str) and category.strip() else None,
        "reps": _integer(_first(set_payload, "reps", "repCount", "repetitionCount", "totalReps")) or 0,
        "weight_kg": _weight_kg(set_payload),
        "duration_sec": _number(duration),
    }


def _volume_kg(summary: Any) -> float | None:
    value = _summary_value(summary, "totalVolumeKg", "totalVolume_kg")
    if value is not None:
        return _number(value)
    value = _summary_value(summary, "totalVolumeInGrams", "totalVolumeGrams", "totalVolume_g")
    if value is not None:
        value = _number(value)
        return round(value / 1000, 4) if value is not None else None
    value = _summary_value(summary, "totalVolumeLb", "totalVolumeLbs", "totalVolume_lb")
    if value is not None:
        value = _number(value)
        return round(value * 0.45359237, 4) if value is not None else None
    raw = _summary_value(summary, "totalVolume")
    unit = _summary_value(summary, "totalVolumeUnit", "volumeUnit", "totalVolumeUnitKey")
    if raw is None or not isinstance(unit, str):
        return None
    return _weight_kg({"weight": raw, "weightUnit": unit})


def parse_strength_training(
    summary: Any,
    exercise_sets: Any,
) -> dict[str, Any]:
    """Produce the public strength contract without deriving unverified volume."""
    sets = [_normalize_set(item, index) for index, item in enumerate(_set_payloads(exercise_sets), start=1)]
    active_sets = [item for item in sets if item["set_type"] == "active"]
    total_sets = _integer(_summary_value(summary, "totalSets", "total_sets", "setCount"))
    active_count = _integer(_summary_value(summary, "activeSets", "active_sets"))
    total_reps = _integer(_summary_value(summary, "totalReps", "total_reps", "repCount"))
    return {
        "total_sets": total_sets if total_sets is not None else len(active_sets),
        "active_sets": active_count if active_count is not None else len(active_sets),
        "total_reps": total_reps if total_reps is not None else sum(item["reps"] for item in active_sets),
        "total_volume_kg": _volume_kg(summary),
        "sets": sets,
    }
