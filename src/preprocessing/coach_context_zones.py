from __future__ import annotations

from typing import Any, Sequence

from src.preprocessing.activity_window import NormalizedActivity
from src.preprocessing.coach_context_utils import (
    _round_or_none,
)

ZONE_RANGE = range(1, 6)


def build_time_in_zone_distribution(
    activities: Sequence[NormalizedActivity],
    *,
    metric_base: str,
    zone_names: dict[int, str],
    include_polarized: bool = False,
) -> dict[str, Any]:
    minutes_by_zone: dict[int, float] = {zone: 0.0 for zone in ZONE_RANGE}
    zone_seconds_by_activity = (
        activity.hr_zone_seconds
        if metric_base == "hr"
        else activity.power_zone_seconds
        for activity in activities
        if activity.processed_has_advanced_metrics
    )
    for zone_seconds in zone_seconds_by_activity:
        for zone in ZONE_RANGE:
            minutes_by_zone[zone] += (zone_seconds.get(zone) or 0.0) / 60

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

    distribution: dict[str, Any] = {
        "period_weeks": 4,
        "zones": [
            {
                "zone": zone,
                "name": zone_names[zone],
                "minutes": _round_or_none(minutes_by_zone[zone], 1) or 0.0,
                "percentage": percentages[zone],
            }
            for zone in ZONE_RANGE
        ],
        "total_minutes": _round_or_none(total_minutes, 1) or 0.0,
    }
    if include_polarized:
        easy_pct = percentages[1] + percentages[2]
        hard_pct = percentages[4] + percentages[5]
        distribution["is_polarized"] = easy_pct >= 75 and hard_pct <= 20 if total_minutes > 0 else False
    return distribution
