from __future__ import annotations

from typing import Any

SHORT_CYCLING_MAX_DISTANCE_KM = 3.0


def numeric_distance_km(distance_km: Any) -> float | None:
    if distance_km is None:
        return None
    try:
        return float(distance_km)
    except (TypeError, ValueError):
        return None


def should_skip_short_cycling(activity_type: str | None, distance_km: Any) -> bool:
    numeric_distance = numeric_distance_km(distance_km)
    return (
        activity_type == "cycling"
        and numeric_distance is not None
        and numeric_distance <= SHORT_CYCLING_MAX_DISTANCE_KM
    )
