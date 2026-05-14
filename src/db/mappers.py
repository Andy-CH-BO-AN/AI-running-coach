from __future__ import annotations

import math
import uuid
from datetime import date, datetime, time, timezone
from typing import Any

from src.db.models import utc_now


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _speed_kmh(distance_km: Any, duration_min: Any) -> float | None:
    distance = _num(distance_km)
    duration = _num(duration_min)
    if distance is None or duration is None or duration <= 0:
        return None
    return round(distance / (duration / 60), 3)


def _max_split_heart_rate(splits: list[dict[str, Any]] | None) -> float | None:
    max_value: float | None = None
    for split in splits or []:
        split_max = _num(split.get("max_heart_rate"))
        if split_max is not None and (max_value is None or split_max > max_value):
            max_value = split_max
    return max_value


def _aware_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    else:
        parsed = utc_now()

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _activity_started_at(activity_data: dict[str, Any]) -> datetime:
    return _aware_datetime(
        activity_data.get("started_at")
        or activity_data.get("start_time")
        or activity_data.get("startTimeLocal")
        or activity_data.get("date")
    )


def _user_profile_snapshot_values(
    user_id: uuid.UUID,
    profile_data: dict[str, Any],
    captured_at: datetime,
    source_file: str | None = None,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "captured_at": _aware_datetime(captured_at),
        "source_file": source_file,
        "max_heart_rate": _num(profile_data.get("max_heart_rate")),
        "resting_heart_rate": _num(profile_data.get("resting_heart_rate")),
        "vo2max_running": _num(profile_data.get("vo2max_running")),
        "lactate_threshold_speed_mps": _num(profile_data.get("lactate_threshold_speed_mps")),
        "lactate_threshold_pace": profile_data.get("lactate_threshold_pace"),
        "lactate_threshold_heart_rate": _num(profile_data.get("lactate_threshold_heart_rate")),
        "weight_kg": _num(profile_data.get("weight_kg")),
        "height_cm": _num(profile_data.get("height_cm")),
        "available_training_days": _jsonable(profile_data.get("available_training_days")),
        "preferred_long_training_days": _jsonable(profile_data.get("preferred_long_training_days")),
        "pr_running": _jsonable(profile_data.get("pr_running")),
        "pr_swimming": _jsonable(profile_data.get("pr_swimming")),
        "pr_cycling": _jsonable(profile_data.get("pr_cycling")),
        "raw_profile": _jsonable(profile_data),
    }


def _activity_values(
    user_id: uuid.UUID,
    activity_data: dict[str, Any],
    source_file: str | None = None,
) -> dict[str, Any]:
    raw_metrics = activity_data.get("raw_data") or activity_data.get("raw_metrics") or {}
    split_max_heart_rate = _max_split_heart_rate(activity_data.get("splits"))
    started_at = _activity_started_at(activity_data)
    duration_min = _num(_first_present(activity_data.get("duration"), activity_data.get("duration_min")))
    activity_type = activity_data.get("type") or activity_data.get("activity_type") or "unknown"
    distance_km = _num(_first_present(activity_data.get("distance"), activity_data.get("distance_km")))
    average_speed_kmh = None
    if activity_type == "cycling":
        average_speed_kmh = _num(
            _first_present(
                activity_data.get("average_speed_kmh"),
                raw_metrics.get("average_speed_kmh"),
                activity_data.get("average_pace"),
                _speed_kmh(distance_km, duration_min),
            )
        )
    return {
        "user_id": user_id,
        "garmin_activity_id": int(activity_data["activity_id"]),
        "activity_type": activity_type,
        "started_at": started_at,
        "activity_date": started_at.date(),
        "source_file": source_file,
        "distance_km": distance_km,
        "duration_min": duration_min,
        "duration_sec": _num(
            _first_present(activity_data.get("duration_sec"), duration_min * 60 if duration_min is not None else None)
        ),
        "average_pace_min_per_km": None
        if activity_type == "cycling"
        else _num(_first_present(activity_data.get("average_pace"), activity_data.get("average_pace_min_per_km"))),
        "average_speed_kmh": average_speed_kmh,
        "average_heart_rate": _num(_first_present(activity_data.get("average_heart_rate"), activity_data.get("avg_hr"))),
        "max_heart_rate": _num(
            _first_present(
                activity_data.get("max_heart_rate"),
                raw_metrics.get("max_heart_rate"),
                raw_metrics.get("maxHR"),
                split_max_heart_rate,
            )
        ),
        "average_power": _num(_first_present(activity_data.get("average_power"), raw_metrics.get("power_avg"))),
        "max_power": _num(_first_present(activity_data.get("max_power"), raw_metrics.get("power_max"))),
        "average_cadence": _num(_first_present(activity_data.get("average_cadence"), raw_metrics.get("cadence"))),
        "max_cadence": _num(_first_present(activity_data.get("max_cadence"), raw_metrics.get("max_cadence"))),
        "elevation_gain": _num(raw_metrics.get("elevation_gain")),
        "elevation_loss": _num(raw_metrics.get("elevation_loss")),
        "temperature": _num(raw_metrics.get("temperature")),
        "training_stress_score": _num(raw_metrics.get("training_stress_score")),
        "intensity_factor": _num(raw_metrics.get("intensity_factor")),
        "aerobic_training_effect": _num(raw_metrics.get("aerobic_training_effect")),
        "anaerobic_training_effect": _num(raw_metrics.get("anaerobic_training_effect")),
        "raw_metrics": _jsonable(raw_metrics),
        "raw_json": _jsonable(activity_data),
        "source": activity_data.get("source") or "garmin",
        "updated_at": utc_now(),
    }


def _split_values(activity_id: uuid.UUID, split: dict[str, Any], activity_type: str | None = None) -> dict[str, Any]:
    duration_min = _num(_first_present(split.get("duration"), split.get("duration_min")))
    distance_km = _num(_first_present(split.get("distance"), split.get("distance_km")))
    speed_kmh = None
    if activity_type == "cycling":
        speed_kmh = _num(
            _first_present(
                split.get("speed_kmh"),
                split.get("pace"),
                split.get("pace_min_per_km"),
                _speed_kmh(distance_km, duration_min),
            )
        )
    structured_keys = {
        "split_index",
        "distance",
        "distance_km",
        "duration",
        "duration_min",
        "duration_sec",
        "pace",
        "pace_min_per_km",
        "speed_kmh",
        "average_heart_rate",
        "max_heart_rate",
        "average_power",
        "power_avg",
        "max_power",
        "power_max",
        "average_cadence",
        "avg_cadence",
        "max_cadence",
        "temperature",
        "stride_length",
        "ground_contact_time",
        "vertical_oscillation",
        "vertical_ratio",
    }
    return {
        "activity_id": activity_id,
        "split_index": int(split["split_index"]),
        "distance_km": distance_km,
        "duration_min": duration_min,
        "duration_sec": _num(
            _first_present(split.get("duration_sec"), duration_min * 60 if duration_min is not None else None)
        ),
        "pace_min_per_km": None
        if activity_type == "cycling"
        else _num(_first_present(split.get("pace"), split.get("pace_min_per_km"))),
        "speed_kmh": speed_kmh,
        "average_heart_rate": _num(split.get("average_heart_rate")),
        "max_heart_rate": _num(split.get("max_heart_rate")),
        "average_power": _num(_first_present(split.get("average_power"), split.get("power_avg"))),
        "max_power": _num(_first_present(split.get("max_power"), split.get("power_max"))),
        "average_cadence": _num(_first_present(split.get("average_cadence"), split.get("avg_cadence"))),
        "max_cadence": _num(split.get("max_cadence")),
        "temperature": _num(split.get("temperature")),
        "stride_length_cm": _num(split.get("stride_length")),
        "ground_contact_time_ms": _num(split.get("ground_contact_time")),
        "vertical_oscillation_cm": _num(split.get("vertical_oscillation")),
        "vertical_ratio": _num(split.get("vertical_ratio")),
        "metrics": _jsonable({key: value for key, value in split.items() if key not in structured_keys}),
        "raw_json": _jsonable(split),
        "updated_at": utc_now(),
    }
