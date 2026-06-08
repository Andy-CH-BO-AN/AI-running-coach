from __future__ import annotations

from typing import Any

RUNNING_PR_DISTANCES_KM = {
    1: 1.0,
    2: 1.60934,
    3: 5.0,
    4: 10.0,
    5: 21.0975,
    6: 42.195,
}


def format_garmin_value(value: float, typeId: int) -> tuple[str, str]:
    """
    Format Garmin personal-record values and derived pace labels.

    The argument name `typeId` mirrors Garmin's payload key and is kept for
    compatibility with existing callers/tests.
    """
    if typeId in RUNNING_PR_DISTANCES_KM:
        total_seconds = round(value)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        formatted_value = f"{minutes}:{seconds:02d}"

        distance_km = RUNNING_PR_DISTANCES_KM.get(typeId)
        pace = ""
        if distance_km:
            pace_seconds = total_seconds / distance_km
            pace = f"{int(pace_seconds // 60)}:{int(pace_seconds % 60):02d} /km"

        return formatted_value, pace

    if typeId in [7, 8]:
        value_km = value / 1000
        return f"{value_km:.2f} km", ""

    if typeId == 14:
        return f"{int(value):,} 步", ""

    if typeId in [18, 20, 22]:
        total_seconds = round(value)
        return f"{total_seconds // 60}:{total_seconds % 60:02d}", ""

    if typeId == 17:
        return f"{int(value)} m", ""

    if typeId == 13:
        value_m = int(value // 1000) if value > 5000 else int(value)
        return f"{value_m} m", ""

    if typeId == 15:
        return f"{int(value)} 天", ""

    if value == int(value):
        return str(int(value)), ""
    return str(round(value, 2)), ""


def find_nested_value(data: Any, target_key: str) -> Any:
    """Recursively search dict/list payloads and return the first non-None match."""
    if isinstance(data, dict):
        if target_key in data and data[target_key] is not None:
            return data[target_key]

        for value in data.values():
            found = find_nested_value(value, target_key)
            if found is not None:
                return found

    elif isinstance(data, list):
        for item in data:
            found = find_nested_value(item, target_key)
            if found is not None:
                return found

    return None


def get_activity_value(source: Any, *keys: str) -> Any:
    """Fetch the first matching value from a Garmin activity payload."""
    for key in keys:
        value = find_nested_value(source, key)
        if value is not None:
            return value
    return None


def extract_zone_seconds(zone_payload: Any, zone_base: str) -> dict[str, Any]:
    """
    Normalize Garmin time-in-zone payloads.

    Expected API payload shape:
      [
        {"zoneNumber": 1, "secsInZone": 273.906, ...},
        ...
      ]

    Returns both the internal normalized keys and Garmin-compatible keys.
    """
    zone_data = {f"{zone_base}_zone_{index}": None for index in range(1, 6)}
    zone_data.update({f"{zone_base}TimeInZone_{index}": None for index in range(1, 6)})

    if isinstance(zone_payload, list):
        for entry in zone_payload:
            if not isinstance(entry, dict):
                continue
            zone_number = entry.get("zoneNumber")
            secs_in_zone = entry.get("secsInZone")
            if zone_number in range(1, 6):
                zone_data[f"{zone_base}_zone_{zone_number}"] = secs_in_zone
                zone_data[f"{zone_base}TimeInZone_{zone_number}"] = secs_in_zone
        return zone_data

    if isinstance(zone_payload, dict):
        for index in range(1, 6):
            zone_data[f"{zone_base}_zone_{index}"] = get_activity_value(
                zone_payload,
                f"{zone_base}TimeInZone_{index}",
                f"{zone_base}_zone_{index}",
                f"secsInZone_{index}",
                f"zone_{index}",
            )
            zone_data[f"{zone_base}TimeInZone_{index}"] = zone_data[f"{zone_base}_zone_{index}"]

    return zone_data
