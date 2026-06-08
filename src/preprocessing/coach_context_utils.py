from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Optional, Sequence

WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKDAY_ALIASES = {
    "MONDAY": "Mon",
    "TUESDAY": "Tue",
    "WEDNESDAY": "Wed",
    "THURSDAY": "Thu",
    "FRIDAY": "Fri",
    "SATURDAY": "Sat",
    "SUNDAY": "Sun",
    "MON": "Mon",
    "TUE": "Tue",
    "WED": "Wed",
    "THU": "Thu",
    "FRI": "Fri",
    "SAT": "Sat",
    "SUN": "Sun",
}


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _round_or_none(value: Any, digits: int = 1) -> Optional[float]:
    number = _safe_float(value)
    if number is None:
        return None
    quantizer = Decimal("1") if digits == 0 else Decimal(f"1e-{digits}")
    rounded = Decimal(str(number)).quantize(quantizer, rounding=ROUND_HALF_UP)
    return int(rounded) if digits == 0 else float(rounded)


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str) or not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value[:10] if fmt == "%Y-%m-%d" else value, fmt).date()
        except ValueError:
            continue
    return None


def _resolve_today(today: Any, activities: Sequence[dict[str, Any]]) -> date:
    parsed_today = _parse_date(today)
    if parsed_today:
        return parsed_today

    activity_dates = [
        parsed_date
        for parsed_date in (_parse_date(activity.get("date")) for activity in activities)
        if parsed_date is not None
    ]
    if activity_dates:
        return max(activity_dates)
    return date.today()


def _week_start_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _format_week_label(week_start: date) -> str:
    week_end = week_start + timedelta(days=6)
    return f"{week_start.strftime('%m/%d')}-{week_end.strftime('%m/%d')}"


def _normalize_activity_id(value: Any) -> str:
    return "" if value is None else str(value)


def _nested_get(payload: dict[str, Any], path: Sequence[str]) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _get_any(payload: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        if path in payload:
            return payload[path]
        value = _nested_get(payload, path.split("."))
        if value is not None:
            return value
    return None


def _stride_length_to_meters(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return value / 100 if value > 10 else value


def _format_pace_minutes(value: Any) -> Optional[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.upper() == "N/A":
            return None
        return stripped.replace(" /km", "").replace("/km", "").replace(" /100m", "").replace("/100m", "")

    pace = _safe_float(value)
    if pace is None or pace <= 0:
        return None
    total_seconds = int(round(pace * 60))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _parse_pace_seconds(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        pace = _safe_float(value)
        return int(round(pace * 60)) if pace and pace > 0 else None

    text = str(value).strip().replace(" /km", "").replace("/km", "")
    if not text:
        return None
    pieces = text.split(":")
    try:
        if len(pieces) == 2:
            return int(pieces[0]) * 60 + int(round(float(pieces[1])))
        if len(pieces) == 3:
            return int(pieces[0]) * 3600 + int(pieces[1]) * 60 + int(round(float(pieces[2])))
    except ValueError:
        return None
    return None


def _format_pace_seconds(seconds: Optional[int]) -> Optional[str]:
    if seconds is None or seconds <= 0:
        return None
    minutes, remaining_seconds = divmod(int(round(seconds)), 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _normalize_weekday(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return WEEKDAY_ALIASES.get(value.strip().upper())


def _average(values: Iterable[Any], digits: int = 1) -> Optional[float]:
    numbers = [number for number in (_safe_float(value) for value in values) if number is not None]
    if not numbers:
        return None
    return _round_or_none(sum(numbers) / len(numbers), digits)


def _weighted_average(values: Iterable[tuple[Any, Any]], digits: int = 1) -> Optional[float]:
    weighted_sum = 0.0
    weight_sum = 0.0
    for value, weight in values:
        number = _safe_float(value)
        numeric_weight = _safe_float(weight)
        if number is None:
            continue
        if numeric_weight is None or numeric_weight <= 0:
            numeric_weight = 1.0
        weighted_sum += number * numeric_weight
        weight_sum += numeric_weight
    if weight_sum == 0:
        return None
    return _round_or_none(weighted_sum / weight_sum, digits)


def _sum_numbers(values: Iterable[Any], digits: int = 1) -> float:
    total = sum(number for number in (_safe_float(value) for value in values) if number is not None)
    return _round_or_none(total, digits) or 0.0
