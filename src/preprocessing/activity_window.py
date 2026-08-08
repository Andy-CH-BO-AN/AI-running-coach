from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from src.preprocessing.activity_policy import should_skip_short_cycling

ZONE_RANGE = range(1, 6)


def calculate_pace(
    duration_ms: float | None,
    distance_m: float | None,
    activity_type: str = "running",
) -> float | None:
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


def format_pace(value: float | None, activity_type: str = "running") -> str:
    if value is None:
        return "N/A"

    if activity_type == "cycling":
        return f"{value} km/h"

    total_seconds = int(round(value * 60))
    minutes, seconds = divmod(total_seconds, 60)
    suffix = "/100m" if activity_type == "swimming" else "/km"
    return f"{minutes}:{seconds:02d} {suffix}"


def classify_runner_type(cadence: float | None) -> str | None:
    if cadence is None:
        return None
    if cadence < 40:
        return "walking or resting"
    return "frequency_runner" if cadence >= 180 else "power_runner"


def _optional_metric_is_present(value: Any) -> bool:
    return value is not None and value != ""


def _validated_optional_metric(
    value: Any,
    *,
    metric_name: str,
    minimum: float,
    maximum: float,
    minimum_inclusive: bool = True,
    maximum_inclusive: bool = True,
    invalid_metrics: list[str] | None = None,
) -> float | None:
    if not _optional_metric_is_present(value):
        return None
    number = _number(value)
    minimum_valid = (
        number is not None
        and (number >= minimum if minimum_inclusive else number > minimum)
    )
    maximum_valid = (
        number is not None
        and (number <= maximum if maximum_inclusive else number < maximum)
    )
    if minimum_valid and maximum_valid:
        return number
    if invalid_metrics is not None and metric_name not in invalid_metrics:
        invalid_metrics.append(metric_name)
    return None


def _validated_vertical_oscillation(
    value: Any,
    invalid_metrics: list[str] | None = None,
) -> float | None:
    return _validated_optional_metric(
        value,
        metric_name="vertical_oscillation_cm",
        minimum=0,
        maximum=20,
        invalid_metrics=invalid_metrics,
    )


def _validated_ground_contact_time(
    value: Any,
    invalid_metrics: list[str] | None = None,
) -> float | None:
    return _validated_optional_metric(
        value,
        metric_name="ground_contact_time_ms",
        minimum=100,
        maximum=500,
        invalid_metrics=invalid_metrics,
    )


def _validated_power_avg(
    value: Any,
    invalid_metrics: list[str] | None = None,
) -> float | None:
    return _validated_optional_metric(
        value,
        metric_name="power_avg_w",
        minimum=0,
        maximum=2000,
        minimum_inclusive=False,
        invalid_metrics=invalid_metrics,
    )


def _validated_power_max(
    value: Any,
    invalid_metrics: list[str] | None = None,
) -> float | None:
    return _validated_optional_metric(
        value,
        metric_name="power_max_w",
        minimum=0,
        maximum=3000,
        minimum_inclusive=False,
        invalid_metrics=invalid_metrics,
    )


def _validated_swolf(
    value: Any,
    invalid_metrics: list[str] | None = None,
) -> float | None:
    return _validated_optional_metric(
        value,
        metric_name="avg_swolf",
        minimum=0,
        maximum=250,
        minimum_inclusive=False,
        maximum_inclusive=False,
        invalid_metrics=invalid_metrics,
    )


def _running_efficiency_from_validated(
    vertical_oscillation: float | None,
    ground_contact_time: float | None,
) -> dict[str, Any] | None:
    efficiency: dict[str, Any] = {}
    if vertical_oscillation is not None:
        efficiency["vertical_oscillation"] = round(vertical_oscillation, 1)
    if ground_contact_time is not None:
        efficiency["ground_contact_time"] = round(ground_contact_time, 1)
    return efficiency or None


def calculate_running_efficiency(
    vertical_oscillation: float | None,
    ground_contact_time: float | None,
) -> dict[str, Any] | None:
    return _running_efficiency_from_validated(
        _validated_vertical_oscillation(vertical_oscillation),
        _validated_ground_contact_time(ground_contact_time),
    )


def calculate_cycling_efficiency(
    power_avg: float | None,
    power_max: float | None,
) -> dict[str, Any] | None:
    validated_avg = _validated_power_avg(power_avg)
    validated_max = _validated_power_max(power_max)
    if validated_avg is None or validated_max is None:
        return None
    return {"power_ratio": round(validated_max / validated_avg, 2)}


def calculate_swimming_efficiency(avg_swolf: float | None) -> dict[str, Any] | None:
    validated = _validated_swolf(avg_swolf)
    if validated is None:
        return None
    return {"avg_swolf": round(validated, 1)}


class ActivityWindowError(ValueError):
    """Raised when the provider-selected Activity window is not coherent."""


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _first_present_value(*values: Any) -> Any:
    for value in values:
        if _optional_metric_is_present(value):
            return value
    return None


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _stride_length_m(value: Any) -> float | None:
    stride = _number(value)
    if stride is None:
        return None
    return stride / 100 if stride > 10 else stride


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return _json_scalar(value)


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_activity_id(value: Any, *, index: int) -> str:
    if value is None:
        raise ActivityWindowError(
            f"activity at index {index}: activity_id is required"
        )
    if isinstance(value, bool):
        raise ActivityWindowError(
            f"activity at index {index}: activity_id must not be bool"
        )

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ActivityWindowError(
                f"activity at index {index}: activity_id must not be empty"
            )
    elif isinstance(value, (int, float, Decimal)):
        text = str(value)
    else:
        raise ActivityWindowError(
            f"activity at index {index}: unsupported activity_id type "
            f"{type(value).__name__}"
        )

    try:
        numeric = Decimal(text)
    except InvalidOperation:
        return f"text:{text}"

    if not numeric.is_finite():
        raise ActivityWindowError(
            f"activity at index {index}: activity_id must be finite"
        )
    if numeric != numeric.to_integral_value():
        raise ActivityWindowError(
            f"activity at index {index}: activity_id must be an integer when numeric"
        )
    return f"number:{int(numeric)}"


def canonical_activity_id(value: Any) -> str:
    """Return the lookup key used by ActivityWindow for a valid identity."""

    return _canonical_activity_id(value, index=0)


def _sport_family(activity_type: str) -> str:
    if activity_type in {"swimming", "lap_swimming"}:
        return "swimming"
    return activity_type


def _zone_seconds(
    raw_data: Mapping[str, Any],
    base: str,
    *,
    available: bool,
) -> Mapping[int, float | None]:
    return MappingProxyType(
        {
            zone: (
                _number(raw_data.get(f"{base}_zone_{zone}"))
                if available
                else None
            )
            for zone in ZONE_RANGE
        }
    )


@dataclass(frozen=True, slots=True)
class NormalizedSegment:
    split_index: Any
    interval_type: str | None
    distance_km: float | None
    duration_min: float | None
    elapsed_duration_min: float | None
    moving_duration_min: float | None
    pace_value: float | None
    pace_formatted: str | None
    speed_kmh: float | None
    avg_hr_bpm: float | None
    max_hr_bpm: float | None
    avg_cadence_spm: float | None
    processed_avg_cadence_spm: float | None
    max_cadence_spm: float | None
    stride_length_m: float | None
    ground_contact_time_ms: float | None
    vertical_oscillation_cm: float | None
    temperature_c: float | None
    power_avg_w: float | None
    power_max_w: float | None
    processed_power_avg_w: float | None
    processed_power_max_w: float | None
    elevation_gain_m: float | None
    elevation_loss_m: float | None
    swim_stroke: str | None
    avg_swolf: float | None
    total_strokes: float | None
    active_lengths: float | None
    invalid_optional_metrics: tuple[str, ...]
    _source_projection: Mapping[str, Any] = field(
        repr=False,
        compare=False,
        hash=False,
    )

    def processed_data(self, projection_activity_type: Any) -> dict[str, Any]:
        projection = _thaw_json(self._source_projection)
        if projection_activity_type != "cycling" and self.pace_value is not None:
            projection["pace"] = format_pace(
                self.pace_value,
                projection_activity_type,
            )
        return projection


@dataclass(frozen=True, slots=True)
class NormalizedActivity:
    source_index: int
    activity_id: Any
    canonical_id: str
    activity_type: str
    date: Any
    distance_km: float | None
    duration_min: float | None
    elapsed_duration_min: float | None
    moving_duration_min: float | None
    rest_duration_min: float | None
    avg_hr_bpm: float | None
    max_hr_bpm: float | None
    performance_value: float | None
    performance_formatted: str
    processed_activity_type: Any
    processed_performance_value: float | None
    processed_performance_formatted: str
    training_load: float | None
    training_effect_aerobic: float | None
    training_effect_anaerobic: float | None
    hr_zone_seconds: Mapping[int, float | None]
    power_zone_seconds: Mapping[int, float | None]
    temperature_c: float | None
    humidity_pct: float | None
    avg_cadence_spm: float | None
    processed_avg_cadence_spm: float | None
    max_cadence_spm: float | None
    vertical_oscillation_cm: float | None
    ground_contact_time_ms: float | None
    stride_length_m: float | None
    elevation_gain_m: float | None
    elevation_loss_m: float | None
    power_avg_w: float | None
    power_max_w: float | None
    processed_power_avg_w: float | None
    processed_power_max_w: float | None
    intensity_factor: float | None
    total_strokes: float | None
    avg_swolf: float | None
    pool_length_m: float | None
    stroke_style: str | None
    avg_stroke_cadence_spm: float | None
    invalid_optional_metrics: tuple[str, ...]
    segments: tuple[NormalizedSegment, ...]
    runner_type: str | None
    running_efficiency: Mapping[str, Any] | None = field(
        repr=False,
        compare=False,
        hash=False,
    )
    swimming_efficiency: Mapping[str, Any] | None = field(
        repr=False,
        compare=False,
        hash=False,
    )
    cycling_efficiency: Mapping[str, Any] | None = field(
        repr=False,
        compare=False,
        hash=False,
    )
    _processed_projection: Mapping[str, Any] = field(
        repr=False,
        compare=False,
        hash=False,
    )

    @property
    def processed_has_advanced_metrics(self) -> bool:
        return self.processed_activity_type in {"running", "swimming", "cycling"}

    def processed_data(self) -> dict[str, Any]:
        return _thaw_json(self._processed_projection)


@dataclass(frozen=True, slots=True)
class ActivityWindow:
    activities: tuple[NormalizedActivity, ...]
    by_id: Mapping[str, NormalizedActivity] = field(
        repr=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "activities", tuple(self.activities))
        object.__setattr__(
            self,
            "by_id",
            MappingProxyType(dict(self.by_id)),
        )

    def processed_data(self) -> list[dict[str, Any]]:
        """Return a new JSON-safe processed projection on every call."""

        return [activity.processed_data() for activity in self.activities]


def _normalized_activity_type(value: Any) -> str:
    if value is None:
        return "running"
    normalized = str(value).strip().lower()
    return normalized or "running"


def _normalized_segment(
    split: Mapping[str, Any],
    *,
    activity_type: str,
) -> NormalizedSegment:
    pace_value = _number(split.get("pace"))
    family = _sport_family(activity_type)
    is_running = family == "running"
    is_swimming = family == "swimming"
    is_cycling = family == "cycling"
    invalid_optional_metrics: list[str] = []
    vertical_oscillation = (
        _validated_vertical_oscillation(
            split.get("vertical_oscillation"),
            invalid_optional_metrics,
        )
        if is_running
        else None
    )
    ground_contact_time = (
        _validated_ground_contact_time(
            split.get("ground_contact_time"),
            invalid_optional_metrics,
        )
        if is_running
        else None
    )
    power_avg_source = _first_present_value(
        split.get("power_avg"),
        split.get("average_power"),
    )
    power_max_source = _first_present_value(
        split.get("power_max"),
        split.get("max_power"),
    )
    power_avg = (
        _validated_power_avg(power_avg_source, invalid_optional_metrics)
        if is_running or is_cycling
        else None
    )
    power_max = (
        _validated_power_max(power_max_source, invalid_optional_metrics)
        if is_running or is_cycling
        else None
    )
    avg_swolf = (
        _validated_swolf(split.get("avg_swolf"), invalid_optional_metrics)
        if is_swimming
        else None
    )
    return NormalizedSegment(
        split_index=_json_scalar(split.get("split_index")),
        interval_type=_string(split.get("interval_type")),
        distance_km=_number(split.get("distance")),
        duration_min=_number(split.get("duration")),
        elapsed_duration_min=_number(split.get("elapsed_duration")),
        moving_duration_min=_number(split.get("moving_duration")),
        pace_value=pace_value,
        pace_formatted=(
            format_pace(pace_value, family)
            if pace_value is not None and family != "cycling"
            else None
        ),
        speed_kmh=_first_number(split.get("speed_kmh")),
        avg_hr_bpm=_number(split.get("average_heart_rate")),
        max_hr_bpm=_number(split.get("max_heart_rate")),
        avg_cadence_spm=_first_number(
            split.get("avg_cadence"),
            split.get("average_cadence"),
        ),
        processed_avg_cadence_spm=_number(split.get("avg_cadence")),
        max_cadence_spm=_number(split.get("max_cadence")),
        stride_length_m=_stride_length_m(split.get("stride_length")),
        ground_contact_time_ms=ground_contact_time,
        vertical_oscillation_cm=vertical_oscillation,
        temperature_c=_number(split.get("temperature")),
        power_avg_w=power_avg,
        power_max_w=power_max,
        processed_power_avg_w=_validated_power_avg(split.get("power_avg")),
        processed_power_max_w=_validated_power_max(split.get("power_max")),
        elevation_gain_m=_number(split.get("elevation_gain")),
        elevation_loss_m=_number(split.get("elevation_loss")),
        swim_stroke=_string(split.get("swim_stroke")),
        avg_swolf=avg_swolf,
        total_strokes=_number(split.get("total_strokes")),
        active_lengths=_number(split.get("active_lengths")),
        invalid_optional_metrics=tuple(invalid_optional_metrics),
        _source_projection=_freeze_json(split),
    )


def _freeze_optional_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    return _freeze_json(value) if value else None


def _sum_segment_duration(
    segments: Sequence[NormalizedSegment],
) -> float | None:
    durations = [
        segment.duration_min
        for segment in segments
        if segment.duration_min is not None
    ]
    return sum(durations) if durations else None


def _rest_duration_from_segments(
    segments: Sequence[NormalizedSegment],
) -> float | None:
    values = [
        segment.elapsed_duration_min
        if segment.elapsed_duration_min is not None
        else segment.duration_min
        for segment in segments
        if segment.interval_type == "rest"
    ]
    present_values = [value for value in values if value is not None]
    return sum(present_values) if present_values else None


def _environment_temperature(
    raw_temperature: Any,
    segments: Sequence[NormalizedSegment],
) -> float | None:
    temperatures = [
        value
        for value in (
            _number(raw_temperature),
            *(segment.temperature_c for segment in segments),
        )
        if value is not None
    ]
    return sum(temperatures) / len(temperatures) if temperatures else None


def _processed_zone_data(
    raw_data: Mapping[str, Any],
    base: str,
) -> dict[str, Any]:
    return {
        f"{base}_zone_{zone}": raw_data.get(f"{base}_zone_{zone}")
        for zone in ZONE_RANGE
    }


def _processed_advanced_metrics(
    processed_activity_type: Any,
    raw_data: Mapping[str, Any],
) -> dict[str, Any]:
    zones = {
        "hr_zones": _processed_zone_data(raw_data, "hr"),
        "power_zones": _processed_zone_data(raw_data, "power"),
    }
    if processed_activity_type == "running":
        return {
            "avg_cadence": raw_data.get("cadence"),
            "max_cadence": raw_data.get("max_cadence"),
            "vertical_oscillation": raw_data.get("vertical_oscillation"),
            "ground_contact_time": raw_data.get("ground_contact_time"),
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
            **zones,
        }
    if processed_activity_type == "swimming":
        return {
            "stroke_count": raw_data.get("total_strokes"),
            "avg_swolf": raw_data.get("avg_swolf"),
            "pool_length": raw_data.get("pool_length"),
            "stroke_style": raw_data.get("avg_stroke_type"),
            **zones,
        }
    if processed_activity_type == "cycling":
        return {
            "elevation_gain": raw_data.get("elevation_gain"),
            "elevation_loss": raw_data.get("elevation_loss"),
            **zones,
            "power_avg": raw_data.get("power_avg"),
            "power_max": raw_data.get("power_max"),
            "avg_cadence": raw_data.get("cadence"),
        }
    return {}


def _processed_activity_projection(
    item: Mapping[str, Any],
    raw_data: Mapping[str, Any],
    segments: Sequence[NormalizedSegment],
    *,
    processed_activity_type: Any,
    processed_performance_value: float | None,
    processed_runner_type: str | None,
    processed_running_efficiency: Mapping[str, Any] | None,
    processed_swimming_efficiency: Mapping[str, Any] | None,
    processed_cycling_efficiency: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    distance_km = _number(item.get("distance")) or 0
    projection: dict[str, Any] = {
        "activity_id": item.get("activity_id"),
        "type": processed_activity_type,
        "date": item.get("date"),
        "distance_km": round(distance_km, 2),
        "performance_value": processed_performance_value,
        "performance_formatted": format_pace(
            processed_performance_value,
            processed_activity_type,
        ),
        "avg_hr": item.get("average_heart_rate"),
        "max_hr": item.get("max_heart_rate"),
        "splits": [
            segment.processed_data(processed_activity_type)
            for segment in segments
        ],
    }
    advanced_metrics = _processed_advanced_metrics(
        processed_activity_type,
        raw_data,
    )
    if advanced_metrics:
        projection["advanced_metrics"] = advanced_metrics
    if processed_activity_type == "running" and processed_runner_type is not None:
        projection["runner_type"] = processed_runner_type
    if (
        processed_activity_type == "running"
        and processed_running_efficiency is not None
    ):
        projection["running_efficiency"] = _thaw_json(
            processed_running_efficiency
        )
    if (
        processed_activity_type == "swimming"
        and processed_swimming_efficiency is not None
    ):
        projection["swimming_efficiency"] = _thaw_json(
            processed_swimming_efficiency
        )
    if (
        processed_activity_type == "cycling"
        and processed_cycling_efficiency is not None
    ):
        projection["cycling_efficiency"] = _thaw_json(
            processed_cycling_efficiency
        )
    return _freeze_json(projection)


def _normalized_activity(
    item: Mapping[str, Any],
    *,
    index: int,
    canonical_id: str,
) -> NormalizedActivity:
    activity_type = _normalized_activity_type(item.get("type"))
    family = _sport_family(activity_type)
    processed_activity_type = _json_scalar(
        item.get("type") if "type" in item else "running"
    )
    is_running = family == "running"
    is_swimming = family == "swimming"
    is_cycling = family == "cycling"
    has_canonical_metrics = is_running or is_swimming or is_cycling
    raw_data_value = item.get("raw_data")
    raw_data: Mapping[str, Any] = (
        raw_data_value if isinstance(raw_data_value, Mapping) else {}
    )
    raw_splits = item.get("splits")
    split_values = (
        raw_splits
        if isinstance(raw_splits, Sequence)
        and not isinstance(raw_splits, (str, bytes, bytearray))
        else ()
    )
    segments = tuple(
        _normalized_segment(split, activity_type=activity_type)
        for split in split_values
        if isinstance(split, Mapping)
    )

    distance_km = _first_number(item.get("distance"), item.get("distance_km"))
    duration_min = _first_number(item.get("duration"), item.get("duration_min"))
    if duration_min is None:
        duration_min = _sum_segment_duration(segments)
    rest_duration_min = _number(item.get("rest_duration"))
    if rest_duration_min is None:
        rest_duration_min = _rest_duration_from_segments(segments)
    performance_value = calculate_pace(
        duration_ms=duration_min * 60000 if duration_min is not None else None,
        distance_m=distance_km * 1000 if distance_km is not None else None,
        activity_type=family,
    )
    cadence = _first_number(raw_data.get("cadence"), raw_data.get("avg_cadence"))
    invalid_optional_metrics: list[str] = []
    vertical_oscillation = (
        _validated_vertical_oscillation(
            raw_data.get("vertical_oscillation"),
            invalid_optional_metrics,
        )
        if is_running
        else None
    )
    ground_contact_time = (
        _validated_ground_contact_time(
            raw_data.get("ground_contact_time"),
            invalid_optional_metrics,
        )
        if is_running
        else None
    )
    power_avg_source = _first_present_value(
        raw_data.get("power_avg"),
        raw_data.get("average_power"),
    )
    power_max_source = _first_present_value(
        raw_data.get("power_max"),
        raw_data.get("max_power"),
    )
    power_avg = (
        _validated_power_avg(power_avg_source, invalid_optional_metrics)
        if is_running or is_cycling
        else None
    )
    power_max = (
        _validated_power_max(power_max_source, invalid_optional_metrics)
        if is_running or is_cycling
        else None
    )
    avg_swolf = (
        _validated_swolf(raw_data.get("avg_swolf"), invalid_optional_metrics)
        if is_swimming
        else None
    )
    processed_distance_km = _number(item.get("distance")) or 0
    processed_duration_min = _number(item.get("duration"))
    processed_performance_value = calculate_pace(
        duration_ms=(
            processed_duration_min * 60000
            if processed_duration_min is not None
            else None
        ),
        distance_m=processed_distance_km * 1000,
        activity_type=processed_activity_type,
    )
    running_efficiency = _freeze_optional_mapping(
        _running_efficiency_from_validated(
            vertical_oscillation,
            ground_contact_time,
        )
        if is_running
        else None
    )
    swimming_efficiency = _freeze_optional_mapping(
        {"avg_swolf": round(avg_swolf, 1)}
        if is_swimming and avg_swolf is not None
        else None
    )
    cycling_efficiency = _freeze_optional_mapping(
        {"power_ratio": round(power_max / power_avg, 2)}
        if is_cycling and power_avg is not None and power_max is not None
        else None
    )
    runner_type = (
        classify_runner_type(cadence)
        if is_running and cadence is not None
        else None
    )
    processed_cadence = _number(raw_data.get("cadence"))
    processed_runner_type = (
        classify_runner_type(processed_cadence)
        if processed_activity_type == "running" and processed_cadence is not None
        else None
    )
    processed_running_efficiency = _freeze_optional_mapping(
        calculate_running_efficiency(
            _number(raw_data.get("vertical_oscillation")),
            _number(raw_data.get("ground_contact_time")),
        )
        if processed_activity_type == "running"
        else None
    )
    processed_swimming_efficiency = _freeze_optional_mapping(
        calculate_swimming_efficiency(_number(raw_data.get("avg_swolf")))
        if processed_activity_type == "swimming"
        else None
    )
    processed_cycling_efficiency = _freeze_optional_mapping(
        calculate_cycling_efficiency(
            _number(raw_data.get("power_avg")),
            _number(raw_data.get("power_max")),
        )
        if processed_activity_type == "cycling"
        else None
    )
    processed_projection = _processed_activity_projection(
        item,
        raw_data,
        segments,
        processed_activity_type=processed_activity_type,
        processed_performance_value=processed_performance_value,
        processed_runner_type=processed_runner_type,
        processed_running_efficiency=processed_running_efficiency,
        processed_swimming_efficiency=processed_swimming_efficiency,
        processed_cycling_efficiency=processed_cycling_efficiency,
    )

    return NormalizedActivity(
        source_index=index,
        activity_id=_json_scalar(item.get("activity_id")),
        canonical_id=canonical_id,
        activity_type=activity_type,
        date=_json_scalar(item.get("date")),
        distance_km=distance_km,
        duration_min=duration_min,
        elapsed_duration_min=_number(item.get("elapsed_duration")),
        moving_duration_min=_number(item.get("moving_duration")),
        rest_duration_min=rest_duration_min,
        avg_hr_bpm=_number(item.get("average_heart_rate")),
        max_hr_bpm=_number(item.get("max_heart_rate")),
        performance_value=performance_value,
        performance_formatted=format_pace(performance_value, family),
        processed_activity_type=processed_activity_type,
        processed_performance_value=processed_performance_value,
        processed_performance_formatted=format_pace(
            processed_performance_value,
            processed_activity_type,
        ),
        training_load=_number(raw_data.get("training_stress_score")),
        training_effect_aerobic=_number(raw_data.get("aerobic_training_effect")),
        training_effect_anaerobic=_number(raw_data.get("anaerobic_training_effect")),
        hr_zone_seconds=_zone_seconds(
            raw_data,
            "hr",
            available=has_canonical_metrics,
        ),
        power_zone_seconds=_zone_seconds(
            raw_data,
            "power",
            available=has_canonical_metrics,
        ),
        temperature_c=_environment_temperature(
            raw_data.get("temperature"),
            segments,
        ),
        humidity_pct=_number(raw_data.get("humidity")),
        avg_cadence_spm=cadence if is_running or is_cycling else None,
        processed_avg_cadence_spm=_number(raw_data.get("cadence")),
        max_cadence_spm=(
            _number(raw_data.get("max_cadence")) if is_running else None
        ),
        vertical_oscillation_cm=vertical_oscillation if is_running else None,
        ground_contact_time_ms=ground_contact_time if is_running else None,
        stride_length_m=(
            _stride_length_m(raw_data.get("stride_length"))
            if is_running
            else None
        ),
        elevation_gain_m=(
            _number(raw_data.get("elevation_gain"))
            if is_running or is_cycling
            else None
        ),
        elevation_loss_m=(
            _number(raw_data.get("elevation_loss"))
            if is_running or is_cycling
            else None
        ),
        power_avg_w=power_avg if is_running or is_cycling else None,
        power_max_w=power_max if is_running or is_cycling else None,
        processed_power_avg_w=(
            _validated_power_avg(raw_data.get("power_avg"))
            if is_running or is_cycling
            else None
        ),
        processed_power_max_w=(
            _validated_power_max(raw_data.get("power_max"))
            if is_running or is_cycling
            else None
        ),
        intensity_factor=(
            _number(raw_data.get("intensity_factor")) if is_running else None
        ),
        total_strokes=(
            _number(raw_data.get("total_strokes")) if is_swimming else None
        ),
        avg_swolf=avg_swolf if is_swimming else None,
        pool_length_m=(
            _number(raw_data.get("pool_length")) if is_swimming else None
        ),
        stroke_style=(
            _string(raw_data.get("avg_stroke_type")) if is_swimming else None
        ),
        avg_stroke_cadence_spm=(
            _number(raw_data.get("avg_stroke_cadence"))
            if is_swimming
            else None
        ),
        invalid_optional_metrics=tuple(invalid_optional_metrics),
        segments=segments,
        runner_type=runner_type,
        running_efficiency=running_efficiency,
        swimming_efficiency=swimming_efficiency,
        cycling_efficiency=cycling_efficiency,
        _processed_projection=processed_projection,
    )


def normalize_activity_window(
    raw_activities: Sequence[Mapping[str, Any]],
) -> ActivityWindow:
    """Normalize one provider-selected window without reordering or mutating it."""

    normalized: list[NormalizedActivity] = []
    by_id: dict[str, NormalizedActivity] = {}
    source_indices: dict[str, int] = {}

    for index, item in enumerate(raw_activities):
        if not isinstance(item, Mapping):
            raise ActivityWindowError(
                f"activity at index {index}: expected an object"
            )
        canonical_id = _canonical_activity_id(item.get("activity_id"), index=index)
        if canonical_id in source_indices:
            raise ActivityWindowError(
                f"activity at index {index}: duplicate activity_id; equivalent to "
                f"index {source_indices[canonical_id]}"
            )
        source_indices[canonical_id] = index

        activity_type = _normalized_activity_type(item.get("type"))
        if should_skip_short_cycling(
            _sport_family(activity_type),
            item.get("distance"),
        ):
            continue

        activity = _normalized_activity(
            item,
            index=index,
            canonical_id=canonical_id,
        )
        normalized.append(activity)
        by_id[canonical_id] = activity

    return ActivityWindow(
        activities=tuple(normalized),
        by_id=MappingProxyType(dict(by_id)),
    )


__all__ = [
    "ActivityWindow",
    "ActivityWindowError",
    "NormalizedActivity",
    "NormalizedSegment",
    "canonical_activity_id",
    "normalize_activity_window",
]
