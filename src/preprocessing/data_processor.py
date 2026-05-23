import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SHORT_CYCLING_MAX_DISTANCE_KM = 3.0
ZONE_RANGE = range(1, 6)


def calculate_pace(
    duration_ms: Optional[float],
    distance_m: Optional[float],
    activity_type: str = "running",
) -> Optional[float]:
    if not duration_ms or not distance_m or distance_m <= 0:
        return None

    duration_min = duration_ms / 60000
    distance_km = distance_m / 1000

    if activity_type == "running":
        pace = duration_min / distance_km
        return round(pace, 2) if pace < 100.0 else 99.99

    if activity_type == "swimming":
        distance_100m = distance_m / 100
        pace_100m = duration_min / distance_100m
        return round(pace_100m, 2) if pace_100m < 100.0 else 99.99

    if activity_type == "cycling":
        hours = duration_min / 60
        speed_kmh = distance_km / hours
        return round(speed_kmh, 1) if speed_kmh > 0.1 else 0.1

    return None


def format_pace(value: Optional[float], activity_type: str = "running") -> str:
    if value is None:
        return "N/A"

    if activity_type == "cycling":
        return f"{value} km/h"

    total_seconds = int(round(value * 60))
    minutes, seconds = divmod(total_seconds, 60)
    suffix = "/100m" if activity_type == "swimming" else "/km"
    return f"{minutes}:{seconds:02d} {suffix}"


def classify_runner_type(cadence: Optional[float]) -> Optional[str]:
    if cadence is None:
        return None

    if cadence < 40:
        return "walking or resting"

    return "frequency_runner" if cadence >= 180 else "power_runner"


def calculate_hrr(resting_hr: Optional[float], max_hr: Optional[float]) -> Optional[float]:
    if not resting_hr or not max_hr:
        return None

    if resting_hr < 30 or resting_hr > 100:
        logger.warning("Unrealistic resting heart rate: %s", resting_hr)
        return None

    if max_hr < 120 or max_hr > 230:
        logger.warning("Unrealistic max heart rate: %s", max_hr)
        return None

    hrr = max_hr - resting_hr
    return round(hrr, 1) if hrr > 0 else None


def calculate_running_efficiency(
    vertical_oscillation: Optional[float],
    ground_contact_time: Optional[float],
) -> Optional[Dict[str, Any]]:
    efficiency: Dict[str, Any] = {}

    if vertical_oscillation is not None:
        if vertical_oscillation < 0 or vertical_oscillation > 20:
            logger.warning(
                "Unrealistic vertical oscillation: %s cm, skipping",
                vertical_oscillation,
            )
        else:
            efficiency["vertical_oscillation"] = round(vertical_oscillation, 1)

    if ground_contact_time is not None:
        if ground_contact_time < 100 or ground_contact_time > 500:
            logger.warning(
                "Unrealistic ground contact time: %s ms, skipping",
                ground_contact_time,
            )
        else:
            efficiency["ground_contact_time"] = round(ground_contact_time, 1)

    return efficiency or None


def calculate_cycling_efficiency(
    power_avg: Optional[float],
    power_max: Optional[float],
) -> Optional[Dict[str, Any]]:
    if not power_avg or not power_max or power_avg <= 0:
        return None

    if power_avg > 2000 or power_max > 3000 or power_avg < 0 or power_max < 0:
        logger.warning("Unrealistic power data: avg=%sW, max=%sW", power_avg, power_max)
        return None

    return {"power_ratio": round(power_max / power_avg, 2)}


def calculate_swimming_efficiency(avg_swolf: Optional[float]) -> Optional[Dict[str, Any]]:
    if avg_swolf is None:
        return None

    if avg_swolf <= 0 or avg_swolf >= 250:
        logger.warning("Unrealistic SWOLF: %s", avg_swolf)
        return None

    return {"avg_swolf": round(avg_swolf, 1)}


def _build_zone_data(raw_data: Dict[str, Any], zone_base: str) -> Dict[str, Any]:
    return {f"{zone_base}_zone_{index}": raw_data.get(f"{zone_base}_zone_{index}") for index in ZONE_RANGE}


def _format_splits_for_output(splits: List[Dict[str, Any]], activity_type: str) -> List[Dict[str, Any]]:
    formatted_splits: List[Dict[str, Any]] = []
    for split in splits:
        formatted_split = dict(split)
        pace = formatted_split.get("pace")
        if activity_type != "cycling" and isinstance(pace, (int, float)):
            formatted_split["pace"] = format_pace(float(pace), activity_type)
        formatted_splits.append(formatted_split)
    return formatted_splits


def _build_base_activity(item: Dict[str, Any]) -> Dict[str, Any]:
    activity_type = item.get("type", "running")
    distance_km = item.get("distance", 0)
    duration_min = item.get("duration", 0)
    performance_value = calculate_pace(
        duration_ms=duration_min * 60000,
        distance_m=distance_km * 1000,
        activity_type=activity_type,
    )

    return {
        "activity_id": item.get("activity_id"),
        "type": activity_type,
        "date": item.get("date"),
        "distance_km": round(distance_km, 2),
        "performance_value": performance_value,
        "performance_formatted": format_pace(performance_value, activity_type),
        "avg_hr": item.get("average_heart_rate"),
        "max_hr": item.get("max_heart_rate"),
        "splits": _format_splits_for_output(item.get("splits") or [], activity_type),
    }


def _build_running_metrics(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    cadence = raw_data.get("cadence")
    vertical_oscillation = raw_data.get("vertical_oscillation")
    ground_contact_time = raw_data.get("ground_contact_time")

    activity: Dict[str, Any] = {
        "advanced_metrics": {
            "avg_cadence": cadence,
            "max_cadence": raw_data.get("max_cadence"),
            "vertical_oscillation": vertical_oscillation,
            "ground_contact_time": ground_contact_time,
            "stride_length": raw_data.get("stride_length"),
            "elevation_gain": raw_data.get("elevation_gain"),
            "elevation_loss": raw_data.get("elevation_loss"),
            "power_avg": raw_data.get("power_avg"),
            "power_max": raw_data.get("power_max"),
            "training_effect": {
                "aerobic": raw_data.get("aerobic_training_effect"),
                "anaerobic": raw_data.get("anaerobic_training_effect"),
            },
            "training_load": raw_data.get("training_stress_score"),
            "hr_zones": _build_zone_data(raw_data, "hr"),
            "power_zones": _build_zone_data(raw_data, "power"),
        }
    }

    if cadence is not None:
        activity["runner_type"] = classify_runner_type(cadence)

    efficiency = calculate_running_efficiency(vertical_oscillation, ground_contact_time)
    if efficiency:
        activity["running_efficiency"] = efficiency

    return activity


def _build_swimming_metrics(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    activity: Dict[str, Any] = {
        "advanced_metrics": {
            "stroke_count": raw_data.get("total_strokes"),
            "avg_swolf": raw_data.get("avg_swolf"),
            "pool_length": raw_data.get("pool_length"),
            "stroke_style": raw_data.get("avg_stroke_type"),
            "hr_zones": _build_zone_data(raw_data, "hr"),
            "power_zones": _build_zone_data(raw_data, "power"),
        }
    }

    efficiency = calculate_swimming_efficiency(raw_data.get("avg_swolf"))
    if efficiency:
        activity["swimming_efficiency"] = efficiency

    return activity


def _build_cycling_metrics(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    power_avg = raw_data.get("power_avg")
    power_max = raw_data.get("power_max")

    activity: Dict[str, Any] = {
        "advanced_metrics": {
            "elevation_gain": raw_data.get("elevation_gain"),
            "elevation_loss": raw_data.get("elevation_loss"),
            "hr_zones": _build_zone_data(raw_data, "hr"),
            "power_zones": _build_zone_data(raw_data, "power"),
            "power_avg": power_avg,
            "power_max": power_max,
            "avg_cadence": raw_data.get("cadence"),
        }
    }

    efficiency = calculate_cycling_efficiency(power_avg, power_max)
    if efficiency:
        activity["cycling_efficiency"] = efficiency

    return activity


def _build_activity_type_details(activity_type: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
    if activity_type == "running":
        return _build_running_metrics(raw_data)
    if activity_type == "swimming":
        return _build_swimming_metrics(raw_data)
    if activity_type == "cycling":
        return _build_cycling_metrics(raw_data)
    return {}


def should_skip_short_cycling(activity_type: str | None, distance_km: Optional[float]) -> bool:
    return activity_type == "cycling" and distance_km is not None and distance_km <= SHORT_CYCLING_MAX_DISTANCE_KM


def _should_skip_activity(item: Dict[str, Any]) -> bool:
    return should_skip_short_cycling(item.get("type"), item.get("distance"))


def preprocess_data(raw_activities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    processed: List[Dict[str, Any]] = []

    for item in raw_activities:
        if _should_skip_activity(item):
            continue

        activity_type = item.get("type", "running")
        processed_item = _build_base_activity(item)
        raw_data = item.get("raw_data") or {}
        processed_item.update(_build_activity_type_details(activity_type, raw_data))
        processed.append(processed_item)

    return processed
