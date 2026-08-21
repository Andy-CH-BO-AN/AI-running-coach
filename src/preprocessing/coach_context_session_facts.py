from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Mapping, TypedDict

from src.preprocessing.activity_window import (
    ActivityWindow,
    ActivityWindowError,
    NormalizedActivity,
    NormalizedSegment,
    canonical_activity_id,
)
from src.preprocessing.coach_context_utils import (
    _format_pace_minutes,
    _round_or_none,
    _safe_float,
)


class SessionFactContractError(ValueError):
    """Raised when deterministic Session facts violate their wire contract."""


class CoachEnvironment(TypedDict, total=False):
    estimated_temp_c: float | None
    humidity_pct: int | None
    hr_impact: str | None


class CoachDataQuality(TypedDict, total=False):
    status: str
    missing_fields: list[str]


class CoachSegment(TypedDict, total=False):
    segment_type: str
    split_index: Any
    distance_km: float | None
    duration_min: float | None
    elapsed_duration_min: float | None
    avg_pace: str | None
    speed_kmh: float | None
    avg_hr: int | None
    cadence: float | None
    stride_length_m: float | None
    temperature_c: float | None
    note: str | None


class CoachSession(TypedDict, total=False):
    activity_id: Any
    date: Any
    source_activity_type: str | None
    distance_km: float | None
    duration_min: float
    elapsed_duration_min: float
    swim_duration_min: float
    rest_duration_min: float
    swim_pace_seconds_per_100m: int
    elapsed_pace_seconds_per_100m: int
    training_load: float
    avg_hr: int | None
    avg_pace: str | None
    training_effect_aerobic: float | None
    training_effect_anaerobic: float | None
    strength: dict[str, Any]
    segments: list[CoachSegment]
    environment: CoachEnvironment
    coaching_note: str | None
    data_quality: CoachDataQuality


def _is_running_source_activity(source_activity_type: str | None) -> bool:
    return (source_activity_type or "").lower() == "running"


def _is_swimming_source_activity(source_activity_type: str | None) -> bool:
    return (source_activity_type or "").lower() in {"swimming", "lap_swimming"}


def _is_strength_source_activity(source_activity_type: str | None) -> bool:
    return (source_activity_type or "").lower() == "strength_training"


def _pace_seconds_per_100m(
    duration_min: Any,
    distance_km: Any,
) -> int | None:
    duration = _safe_float(duration_min)
    distance = _safe_float(distance_km)
    if duration is None or distance is None or duration < 0 or distance <= 0:
        return None
    return round(duration * 60 / (distance * 10))


def _required(payload: Mapping[str, Any], key: str, location: str) -> Any:
    if key not in payload:
        raise SessionFactContractError(f"{location}: missing {key}")
    return payload[key]


def _required_mapping(
    payload: Mapping[str, Any],
    key: str,
    location: str,
) -> Mapping[str, Any]:
    value = _required(payload, key, location)
    if not isinstance(value, Mapping):
        raise SessionFactContractError(f"{location}.{key}: expected an object")
    return value


def _required_list(
    payload: Mapping[str, Any],
    key: str,
    location: str,
) -> list[Any]:
    value = _required(payload, key, location)
    if not isinstance(value, list):
        raise SessionFactContractError(f"{location}.{key}: expected a list")
    return value


def _nonblank_annotation(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _validate_empty_deterministic_annotation(
    value: Any,
    location: str,
) -> None:
    if value in (None, ""):
        return
    raise SessionFactContractError(
        f"{location}: deterministic annotation slot must be empty"
    )


def _number_or_none(value: Any, location: str) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SessionFactContractError(f"{location}: expected a number or null")
    if not math.isfinite(value):
        raise SessionFactContractError(f"{location}: expected a finite number")
    return value


def _number(value: Any, location: str) -> float | int:
    number = _number_or_none(value, location)
    if number is None:
        raise SessionFactContractError(f"{location}: expected a number")
    return number


def _string_or_none(value: Any, location: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise SessionFactContractError(f"{location}: expected a string or null")


def _json_scalar(value: Any, location: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SessionFactContractError(f"{location}: expected a JSON scalar")


def _safe_canonical_activity_id(value: Any) -> str | None:
    try:
        return canonical_activity_id(value)
    except (ActivityWindowError, TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class RunningSessionFacts:
    training_effect_aerobic: float | None
    training_effect_anaerobic: float | None


@dataclass(frozen=True, slots=True)
class StrengthSessionFacts:
    total_sets: int | None
    active_sets: int | None
    total_reps: int | None
    total_volume_kg: float | None
    sets: tuple[dict[str, Any], ...]

    def projection(self) -> dict[str, Any]:
        return {
            "total_sets": self.total_sets,
            "active_sets": self.active_sets,
            "total_reps": self.total_reps,
            "total_volume_kg": self.total_volume_kg,
            "sets": deepcopy(list(self.sets)),
        }


def _nonnegative_integer(value: Any, location: str) -> int:
    number = _number(value, location)
    if number < 0 or int(number) != number:
        raise SessionFactContractError(f"{location}: expected a non-negative integer")
    return int(number)


def _nonnegative_integer_or_none(value: Any, location: str) -> int | None:
    return None if value is None else _nonnegative_integer(value, location)


def _strength_from_context_payload(
    payload: Mapping[str, Any],
    *,
    location: str,
) -> StrengthSessionFacts:
    for key in ("total_sets", "active_sets", "total_reps", "total_volume_kg", "sets"):
        _required(payload, key, location)
    total_volume = _number_or_none(
        payload["total_volume_kg"], f"{location}.total_volume_kg"
    )
    if total_volume is not None and total_volume < 0:
        raise SessionFactContractError(f"{location}.total_volume_kg: expected non-negative")
    raw_sets = _required(payload, "sets", location)
    if not isinstance(raw_sets, (list, tuple)):
        raise SessionFactContractError(f"{location}.sets: expected a list")
    normalized_sets: list[dict[str, Any]] = []
    for index, raw_set in enumerate(raw_sets):
        if not isinstance(raw_set, Mapping):
            raise SessionFactContractError(f"{location}.sets[{index}]: expected an object")
        set_location = f"{location}.sets[{index}]"
        set_type = _required(raw_set, "set_type", set_location)
        if set_type not in {"active", "rest", "unknown"}:
            raise SessionFactContractError(f"{set_location}.set_type: invalid value")
        names = _required(raw_set, "exercise_names", set_location)
        if not isinstance(names, (list, tuple)) or not all(isinstance(name, str) for name in names):
            raise SessionFactContractError(f"{set_location}.exercise_names: expected strings")
        category = _string_or_none(_required(raw_set, "category", set_location), f"{set_location}.category")
        weight = _number_or_none(_required(raw_set, "weight_kg", set_location), f"{set_location}.weight_kg")
        duration = _number_or_none(_required(raw_set, "duration_sec", set_location), f"{set_location}.duration_sec")
        if (weight is not None and weight < 0) or (duration is not None and duration < 0):
            raise SessionFactContractError(f"{set_location}: expected non-negative values")
        normalized_sets.append({
            "set_index": _nonnegative_integer(_required(raw_set, "set_index", set_location), f"{set_location}.set_index"),
            "set_type": set_type,
            "exercise_names": list(names),
            "category": category,
            "reps": _nonnegative_integer_or_none(_required(raw_set, "reps", set_location), f"{set_location}.reps"),
            "weight_kg": weight,
            "duration_sec": duration,
        })
    return StrengthSessionFacts(
        total_sets=_nonnegative_integer_or_none(payload["total_sets"], f"{location}.total_sets"),
        active_sets=_nonnegative_integer_or_none(payload["active_sets"], f"{location}.active_sets"),
        total_reps=_nonnegative_integer_or_none(payload["total_reps"], f"{location}.total_reps"),
        total_volume_kg=total_volume,
        sets=tuple(normalized_sets),
    )


@dataclass(frozen=True, slots=True)
class SwimmingSessionFacts:
    elapsed_duration_min: float | None
    swim_duration_min: float | None
    rest_duration_min: float | None
    swim_pace_seconds_per_100m: int | None
    elapsed_pace_seconds_per_100m: int | None

    def projection(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.elapsed_duration_min is not None:
            payload["elapsed_duration_min"] = self.elapsed_duration_min
        if self.swim_duration_min is not None:
            payload["swim_duration_min"] = self.swim_duration_min
        if self.rest_duration_min is not None:
            payload["rest_duration_min"] = self.rest_duration_min
        if self.swim_pace_seconds_per_100m is not None:
            payload["swim_pace_seconds_per_100m"] = (
                self.swim_pace_seconds_per_100m
            )
        if self.elapsed_pace_seconds_per_100m is not None:
            payload["elapsed_pace_seconds_per_100m"] = (
                self.elapsed_pace_seconds_per_100m
            )
        return payload


@dataclass(frozen=True, slots=True)
class RunningSegmentFacts:
    cadence: float | None
    stride_length_m: float | None


@dataclass(frozen=True, slots=True)
class SwimmingSegmentFacts:
    elapsed_duration_min: float | None


@dataclass(frozen=True, slots=True)
class SessionEnvironmentFacts:
    estimated_temp_c: float | None
    humidity_pct: int | None
    hr_impact: str | None

    def projection(self) -> CoachEnvironment:
        return {
            "estimated_temp_c": self.estimated_temp_c,
            "humidity_pct": self.humidity_pct,
            "hr_impact": self.hr_impact,
        }

    @classmethod
    def from_context_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        location: str,
    ) -> SessionEnvironmentFacts:
        return cls(
            estimated_temp_c=_number_or_none(
                _required(payload, "estimated_temp_c", location),
                f"{location}.estimated_temp_c",
            ),
            humidity_pct=_number_or_none(
                _required(payload, "humidity_pct", location),
                f"{location}.humidity_pct",
            ),
            hr_impact=_string_or_none(
                _required(payload, "hr_impact", location),
                f"{location}.hr_impact",
            ),
        )


@dataclass(frozen=True, slots=True)
class SessionDataQualityFacts:
    status: str
    missing_fields: tuple[str, ...]

    def projection(self) -> CoachDataQuality:
        return {
            "status": self.status,
            "missing_fields": list(self.missing_fields),
        }

    @classmethod
    def from_context_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        location: str,
    ) -> SessionDataQualityFacts:
        status = _required(payload, "status", location)
        missing_fields = _required(payload, "missing_fields", location)
        if not isinstance(status, str):
            raise SessionFactContractError(f"{location}.status: expected a string")
        if not isinstance(missing_fields, list) or not all(
            isinstance(item, str) for item in missing_fields
        ):
            raise SessionFactContractError(
                f"{location}.missing_fields: expected a list of strings"
            )
        return cls(status=status, missing_fields=tuple(missing_fields))


@dataclass(frozen=True, slots=True)
class SegmentFacts:
    segment_type: str
    split_index: Any
    distance_km: float | None
    duration_min: float | None
    avg_pace: str | None
    speed_kmh: float | None
    avg_hr: int | None
    temperature_c: float | None
    running: RunningSegmentFacts | None = None
    swimming: SwimmingSegmentFacts | None = None

    def context_payload(self) -> CoachSegment:
        payload: CoachSegment = {
            "segment_type": self.segment_type,
            "split_index": deepcopy(self.split_index),
            "distance_km": self.distance_km,
            "duration_min": self.duration_min,
            "avg_pace": self.avg_pace,
            "speed_kmh": self.speed_kmh,
            "avg_hr": self.avg_hr,
            "temperature_c": self.temperature_c,
            "note": None,
        }
        if self.running is not None:
            payload["cadence"] = self.running.cadence
            payload["stride_length_m"] = self.running.stride_length_m
        if self.swimming is not None and self.swimming.elapsed_duration_min is not None:
            payload["elapsed_duration_min"] = self.swimming.elapsed_duration_min
        return payload

    def report_payload(self, note: str | None = None) -> CoachSegment:
        payload: CoachSegment = {
            "segment_type": self.segment_type,
            "split_index": deepcopy(self.split_index),
            "distance_km": self.distance_km,
            "duration_min": self.duration_min,
            "avg_pace": self.avg_pace,
            "speed_kmh": self.speed_kmh,
            "avg_hr": self.avg_hr,
            "note": note,
        }
        if self.running is not None:
            payload["cadence"] = self.running.cadence
            payload["stride_length_m"] = self.running.stride_length_m
        if self.swimming is not None and self.swimming.elapsed_duration_min is not None:
            payload["elapsed_duration_min"] = self.swimming.elapsed_duration_min
        return payload

    @classmethod
    def from_context_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        source_activity_type: str | None,
        location: str,
    ) -> SegmentFacts:
        _validate_empty_deterministic_annotation(
            _required(payload, "note", location),
            f"{location}.note",
        )

        running: RunningSegmentFacts | None = None
        swimming: SwimmingSegmentFacts | None = None
        if _is_running_source_activity(source_activity_type):
            running = RunningSegmentFacts(
                cadence=_number_or_none(
                    _required(payload, "cadence", location),
                    f"{location}.cadence",
                ),
                stride_length_m=_number_or_none(
                    _required(payload, "stride_length_m", location),
                    f"{location}.stride_length_m",
                ),
            )
        elif "cadence" in payload or "stride_length_m" in payload:
            raise SessionFactContractError(
                f"{location}: non-running Segment facts contain running fields"
            )

        if _is_swimming_source_activity(source_activity_type):
            swimming = SwimmingSegmentFacts(
                elapsed_duration_min=(
                    _number(
                        payload["elapsed_duration_min"],
                        f"{location}.elapsed_duration_min",
                    )
                    if "elapsed_duration_min" in payload
                    else None
                )
            )
            if (
                "elapsed_duration_min" in payload
                and payload.get("elapsed_duration_min") is None
            ):
                raise SessionFactContractError(
                    f"{location}.elapsed_duration_min: present optional fact is null"
                )
        elif "elapsed_duration_min" in payload:
            raise SessionFactContractError(
                f"{location}: non-swimming Segment facts contain swimming fields"
            )

        segment_type = _required(payload, "segment_type", location)
        if not isinstance(segment_type, str):
            raise SessionFactContractError(
                f"{location}.segment_type: expected a string"
            )
        return cls(
            segment_type=segment_type,
            split_index=_json_scalar(
                _required(payload, "split_index", location),
                f"{location}.split_index",
            ),
            distance_km=_number_or_none(
                _required(payload, "distance_km", location),
                f"{location}.distance_km",
            ),
            duration_min=_number_or_none(
                _required(payload, "duration_min", location),
                f"{location}.duration_min",
            ),
            avg_pace=_string_or_none(
                _required(payload, "avg_pace", location),
                f"{location}.avg_pace",
            ),
            speed_kmh=_number_or_none(
                _required(payload, "speed_kmh", location),
                f"{location}.speed_kmh",
            ),
            avg_hr=_number_or_none(
                _required(payload, "avg_hr", location),
                f"{location}.avg_hr",
            ),
            temperature_c=_number_or_none(
                _required(payload, "temperature_c", location),
                f"{location}.temperature_c",
            ),
            running=running,
            swimming=swimming,
        )


@dataclass(frozen=True, slots=True)
class SegmentAnnotation:
    note: str | None


@dataclass(frozen=True, slots=True)
class SessionAnnotation:
    coaching_note: str | None
    segments: tuple[SegmentAnnotation, ...]


@dataclass(frozen=True, slots=True)
class SessionFacts:
    canonical_id: str
    activity_id: Any
    date: Any
    source_activity_type: str | None
    distance_km: float | None
    duration_min: float
    training_load: float
    avg_hr: int | None
    avg_pace: str | None
    running: RunningSessionFacts | None
    swimming: SwimmingSessionFacts | None
    strength: StrengthSessionFacts | None
    segments: tuple[SegmentFacts, ...]
    environment: SessionEnvironmentFacts
    data_quality: SessionDataQualityFacts

    def context_payload(self) -> CoachSession:
        training_effect_aerobic = (
            self.running.training_effect_aerobic
            if self.running is not None
            else None
        )
        training_effect_anaerobic = (
            self.running.training_effect_anaerobic
            if self.running is not None
            else None
        )
        payload: CoachSession = {
            "activity_id": deepcopy(self.activity_id),
            "date": deepcopy(self.date),
            "source_activity_type": self.source_activity_type,
            "distance_km": self.distance_km,
            "duration_min": self.duration_min,
            "training_load": self.training_load,
            "avg_hr": self.avg_hr,
            "avg_pace": self.avg_pace,
            "training_effect_aerobic": training_effect_aerobic,
            "training_effect_anaerobic": training_effect_anaerobic,
            "segments": [segment.context_payload() for segment in self.segments],
            "environment": self.environment.projection(),
            "coaching_note": None,
            "data_quality": self.data_quality.projection(),
        }
        if self.swimming is not None:
            payload.update(self.swimming.projection())
        if self.strength is not None:
            payload["strength"] = self.strength.projection()
        return payload

    def report_payload(
        self,
        annotation: SessionAnnotation | None = None,
    ) -> CoachSession:
        training_effect_aerobic = (
            self.running.training_effect_aerobic
            if self.running is not None
            else None
        )
        training_effect_anaerobic = (
            self.running.training_effect_anaerobic
            if self.running is not None
            else None
        )
        segment_annotations = annotation.segments if annotation is not None else ()
        payload: CoachSession = {
            "activity_id": deepcopy(self.activity_id),
            "date": deepcopy(self.date),
            "source_activity_type": self.source_activity_type,
            "distance_km": self.distance_km,
            "duration_min": self.duration_min,
            "training_load": self.training_load,
            "avg_hr": self.avg_hr,
            "avg_pace": self.avg_pace,
            "training_effect_aerobic": training_effect_aerobic,
            "training_effect_anaerobic": training_effect_anaerobic,
            "segments": [
                segment.report_payload(
                    segment_annotations[index].note
                    if index < len(segment_annotations)
                    else None
                )
                for index, segment in enumerate(self.segments)
            ],
            "environment": self.environment.projection(),
            "coaching_note": annotation.coaching_note if annotation else None,
        }
        if self.swimming is not None:
            payload.update(self.swimming.projection())
        if self.strength is not None:
            payload["strength"] = self.strength.projection()
        return payload

    @classmethod
    def from_context_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        location: str,
    ) -> SessionFacts:
        activity_id = _required(payload, "activity_id", location)
        canonical_id = _safe_canonical_activity_id(activity_id)
        if canonical_id is None:
            raise SessionFactContractError(
                f"{location}.activity_id: invalid deterministic identity"
            )

        source_activity_type = _required(payload, "source_activity_type", location)
        if source_activity_type is not None and not isinstance(
            source_activity_type, str
        ):
            raise SessionFactContractError(
                f"{location}.source_activity_type: expected a string or null"
            )
        _validate_empty_deterministic_annotation(
            _required(payload, "coaching_note", location),
            f"{location}.coaching_note",
        )

        segments_payload = _required_list(payload, "segments", location)
        segments: list[SegmentFacts] = []
        for index, segment in enumerate(segments_payload):
            if not isinstance(segment, Mapping):
                raise SessionFactContractError(
                    f"{location}.segments[{index}]: expected an object"
                )
            segments.append(
                SegmentFacts.from_context_payload(
                    segment,
                    source_activity_type=source_activity_type,
                    location=f"{location}.segments[{index}]",
                )
            )

        running = (
            RunningSessionFacts(
                training_effect_aerobic=_number_or_none(
                    _required(payload, "training_effect_aerobic", location),
                    f"{location}.training_effect_aerobic",
                ),
                training_effect_anaerobic=_number_or_none(
                    _required(payload, "training_effect_anaerobic", location),
                    f"{location}.training_effect_anaerobic",
                ),
            )
            if _is_running_source_activity(source_activity_type)
            or _is_strength_source_activity(source_activity_type)
            else None
        )
        if running is None:
            for key in (
                "training_effect_aerobic",
                "training_effect_anaerobic",
            ):
                if _required(payload, key, location) is not None:
                    raise SessionFactContractError(
                        f"{location}.{key}: unsupported activity fact must be null"
                    )

        swimming: SwimmingSessionFacts | None = None
        swim_keys = (
            "elapsed_duration_min",
            "swim_duration_min",
            "rest_duration_min",
            "swim_pace_seconds_per_100m",
            "elapsed_pace_seconds_per_100m",
        )
        if _is_swimming_source_activity(source_activity_type):
            for key in swim_keys:
                if key in payload and payload[key] is None:
                    raise SessionFactContractError(
                        f"{location}.{key}: present optional fact is null"
                    )
            swimming = SwimmingSessionFacts(
                elapsed_duration_min=(
                    _number(
                        payload["elapsed_duration_min"],
                        f"{location}.elapsed_duration_min",
                    )
                    if "elapsed_duration_min" in payload
                    else None
                ),
                swim_duration_min=(
                    _number(
                        payload["swim_duration_min"],
                        f"{location}.swim_duration_min",
                    )
                    if "swim_duration_min" in payload
                    else None
                ),
                rest_duration_min=(
                    _number(
                        payload["rest_duration_min"],
                        f"{location}.rest_duration_min",
                    )
                    if "rest_duration_min" in payload
                    else None
                ),
                swim_pace_seconds_per_100m=(
                    _number(
                        payload["swim_pace_seconds_per_100m"],
                        f"{location}.swim_pace_seconds_per_100m",
                    )
                    if "swim_pace_seconds_per_100m" in payload
                    else None
                ),
                elapsed_pace_seconds_per_100m=(
                    _number(
                        payload["elapsed_pace_seconds_per_100m"],
                        f"{location}.elapsed_pace_seconds_per_100m",
                    )
                    if "elapsed_pace_seconds_per_100m" in payload
                    else None
                ),
            )
        elif any(key in payload for key in swim_keys):
            raise SessionFactContractError(
                f"{location}: non-swimming Session facts contain swimming fields"
            )

        strength = (
            _strength_from_context_payload(
                _required_mapping(payload, "strength", location),
                location=f"{location}.strength",
            )
            if _is_strength_source_activity(source_activity_type)
            else None
        )
        if strength is None and "strength" in payload:
            raise SessionFactContractError(
                f"{location}: non-strength Session facts contain strength fields"
            )

        environment = SessionEnvironmentFacts.from_context_payload(
            _required_mapping(payload, "environment", location),
            location=f"{location}.environment",
        )
        data_quality = SessionDataQualityFacts.from_context_payload(
            _required_mapping(payload, "data_quality", location),
            location=f"{location}.data_quality",
        )
        return cls(
            canonical_id=canonical_id,
            activity_id=deepcopy(activity_id),
            date=_json_scalar(
                _required(payload, "date", location),
                f"{location}.date",
            ),
            source_activity_type=source_activity_type,
            distance_km=_number_or_none(
                _required(payload, "distance_km", location),
                f"{location}.distance_km",
            ),
            duration_min=_number(
                _required(payload, "duration_min", location),
                f"{location}.duration_min",
            ),
            training_load=_number(
                _required(payload, "training_load", location),
                f"{location}.training_load",
            ),
            avg_hr=_number_or_none(
                _required(payload, "avg_hr", location),
                f"{location}.avg_hr",
            ),
            avg_pace=_string_or_none(
                _required(payload, "avg_pace", location),
                f"{location}.avg_pace",
            ),
            running=running,
            swimming=swimming,
            strength=strength,
            segments=tuple(segments),
            environment=environment,
            data_quality=data_quality,
        )


@dataclass(frozen=True, slots=True)
class SessionFactSet:
    facts: tuple[SessionFacts, ...]

    def __post_init__(self) -> None:
        facts = tuple(self.facts)
        seen: set[str] = set()
        for fact in facts:
            if fact.canonical_id in seen:
                raise SessionFactContractError(
                    f"duplicate deterministic activity_id: {fact.activity_id!r}"
                )
            seen.add(fact.canonical_id)
        object.__setattr__(self, "facts", facts)

    def context_payloads(self) -> list[CoachSession]:
        return [fact.context_payload() for fact in self.facts]

    def report_payloads(self, ai_sessions: Any) -> list[CoachSession]:
        annotations = _session_annotation_lookup(ai_sessions)
        return [
            fact.report_payload(annotations.get(fact.canonical_id))
            for fact in self.facts
        ]

    @classmethod
    def from_context_payloads(cls, payloads: Any) -> SessionFactSet:
        if not isinstance(payloads, list):
            raise SessionFactContractError(
                "deterministic sessions: expected a list"
            )
        facts: list[SessionFacts] = []
        for index, payload in enumerate(payloads):
            if not isinstance(payload, Mapping):
                raise SessionFactContractError(
                    f"deterministic sessions[{index}]: expected an object"
                )
            facts.append(
                SessionFacts.from_context_payload(
                    payload,
                    location=f"deterministic sessions[{index}]",
                )
            )
        return cls(tuple(facts))


def _segment_from_normalized(
    split: NormalizedSegment,
    *,
    include_running_metrics: bool,
    include_swimming_timing: bool,
) -> SegmentFacts:
    running = (
        RunningSegmentFacts(
            cadence=_round_or_none(split.processed_avg_cadence_spm, 1),
            stride_length_m=_round_or_none(split.stride_length_m, 2),
        )
        if include_running_metrics
        else None
    )
    elapsed_duration = (
        _round_or_none(split.elapsed_duration_min, 4)
        if include_swimming_timing
        else None
    )
    swimming = (
        SwimmingSegmentFacts(elapsed_duration_min=elapsed_duration)
        if include_swimming_timing
        else None
    )
    return SegmentFacts(
        segment_type=(
            "rest"
            if include_swimming_timing and split.interval_type == "rest"
            else "lap"
        ),
        split_index=deepcopy(split.split_index),
        distance_km=_round_or_none(split.distance_km, 3),
        duration_min=_round_or_none(split.duration_min, 2),
        avg_pace=_format_pace_minutes(split.pace_formatted or split.pace_value),
        speed_kmh=_round_or_none(split.speed_kmh, 1),
        avg_hr=_round_or_none(split.avg_hr_bpm, 0),
        temperature_c=_round_or_none(split.temperature_c, 1),
        running=running,
        swimming=swimming,
    )


def _session_from_normalized(activity: NormalizedActivity) -> SessionFacts:
    distance = (
        round(activity.distance_km, 2)
        if activity.distance_km is not None
        else None
    )
    duration = _round_or_none(activity.duration_min, 1)
    training_load = _round_or_none(activity.training_load, 1)
    source_activity_type = activity.activity_type or None
    is_strength = _is_strength_source_activity(source_activity_type)
    missing_fields = tuple(
        field_name
        for field_name, value in (
            *((() if is_strength else (("distance_km", distance),))),
            ("duration_min", duration),
            ("training_load", training_load),
        )
        if value is None
    )

    include_running_metrics = _is_running_source_activity(source_activity_type)
    include_swimming_timing = _is_swimming_source_activity(source_activity_type)
    include_training_effect = activity.processed_activity_type in {
        "running", "strength_training"
    }
    running = (
        RunningSessionFacts(
            training_effect_aerobic=_round_or_none(
                activity.training_effect_aerobic, 1
            )
            if include_training_effect
            else None,
            training_effect_anaerobic=_round_or_none(
                activity.training_effect_anaerobic, 1
            )
            if include_training_effect
            else None,
        )
        if include_training_effect
        else None
    )

    swimming: SwimmingSessionFacts | None = None
    if include_swimming_timing:
        elapsed_duration = _round_or_none(activity.elapsed_duration_min, 4)
        swim_duration = _round_or_none(activity.moving_duration_min, 4)
        rest_duration = _round_or_none(activity.rest_duration_min, 4)
        swimming = SwimmingSessionFacts(
            elapsed_duration_min=elapsed_duration,
            swim_duration_min=swim_duration,
            rest_duration_min=rest_duration,
            swim_pace_seconds_per_100m=(
                _pace_seconds_per_100m(swim_duration, distance)
                if swim_duration is not None
                else None
            ),
            elapsed_pace_seconds_per_100m=_pace_seconds_per_100m(
                elapsed_duration,
                distance,
            ),
        )

    strength: StrengthSessionFacts | None = None
    if is_strength:
        if activity.strength is None or not activity.strength_sets_available:
            missing_fields = tuple((*missing_fields, "strength.sets"))
        if isinstance(activity.strength, Mapping):
            strength = _strength_from_context_payload(
                activity.strength,
                location="normalized strength",
            )
        else:
            strength = StrengthSessionFacts(
                total_sets=None,
                active_sets=None,
                total_reps=None,
                total_volume_kg=None,
                sets=(),
            )

    temp = _round_or_none(activity.temperature_c, 1)
    humidity = _round_or_none(activity.humidity_pct, 0)
    environment = SessionEnvironmentFacts(
        estimated_temp_c=temp,
        humidity_pct=humidity,
        hr_impact=(
            f"{temp:g}°C 高溫環境，心率可能較涼爽條件偏高。"
            if temp is not None and temp >= 27
            else None
        ),
    )
    return SessionFacts(
        canonical_id=activity.canonical_id,
        activity_id=deepcopy(activity.activity_id),
        date=deepcopy(activity.date),
        source_activity_type=source_activity_type,
        distance_km=None if is_strength else distance if distance is not None else 0,
        duration_min=duration if duration is not None else 0,
        training_load=training_load if training_load is not None else 0,
        avg_hr=_round_or_none(activity.avg_hr_bpm, 0),
        avg_pace=(
            None
            if is_strength
            else _format_pace_minutes(
                activity.processed_performance_formatted
                or activity.processed_performance_value
            )
        ),
        running=running,
        swimming=swimming,
        strength=strength,
        segments=tuple(
            _segment_from_normalized(
                segment,
                include_running_metrics=include_running_metrics,
                include_swimming_timing=include_swimming_timing,
            )
            for segment in activity.segments
        ),
        environment=environment,
        data_quality=SessionDataQualityFacts(
            status="partial" if missing_fields else "complete",
            missing_fields=missing_fields,
        ),
    )


def build_session_facts(activity_window: ActivityWindow) -> SessionFactSet:
    """Derive immutable Session facts from one normalized Activity window."""

    return SessionFactSet(
        tuple(
            _session_from_normalized(activity)
            for activity in activity_window.activities
        )
    )


def _session_annotation(
    ai_session: Mapping[str, Any],
) -> SessionAnnotation | None:
    raw_coaching_note = ai_session.get("coaching_note")
    if raw_coaching_note is not None and not isinstance(raw_coaching_note, str):
        return None

    raw_segments = ai_session.get("segments")
    if "segments" in ai_session and not isinstance(raw_segments, list):
        return None
    segment_annotations: list[SegmentAnnotation] = []
    for segment in raw_segments or []:
        if not isinstance(segment, Mapping):
            return None
        raw_note = segment.get("note")
        if raw_note is not None and not isinstance(raw_note, str):
            return None
        segment_annotations.append(
            SegmentAnnotation(note=_nonblank_annotation(raw_note))
        )

    return SessionAnnotation(
        coaching_note=_nonblank_annotation(raw_coaching_note),
        segments=tuple(segment_annotations),
    )


def _session_annotation_lookup(ai_sessions: Any) -> dict[str, SessionAnnotation]:
    if not isinstance(ai_sessions, list):
        return {}
    annotations: dict[str, SessionAnnotation] = {}
    seen_ids: set[str] = set()
    for ai_session in ai_sessions:
        if not isinstance(ai_session, Mapping):
            continue
        canonical_id = _safe_canonical_activity_id(ai_session.get("activity_id"))
        if canonical_id is None:
            continue
        if canonical_id in seen_ids:
            annotations.pop(canonical_id, None)
            continue
        seen_ids.add(canonical_id)

        annotation = _session_annotation(ai_session)
        if annotation is not None:
            annotations[canonical_id] = annotation
    return annotations


def reconcile_session_facts(
    deterministic_sessions: Any,
    ai_sessions: Any,
) -> list[CoachSession]:
    """Project deterministic facts with only allowed AI annotations."""

    return SessionFactSet.from_context_payloads(
        deterministic_sessions
    ).report_payloads(ai_sessions)


def _session_identity(
    session: Mapping[str, Any],
) -> tuple[Any, Any, Any, Any, Any]:
    return (
        session.get("date"),
        session.get("source_activity_type"),
        _round_or_none(session.get("distance_km"), 2),
        _round_or_none(session.get("duration_min"), 1),
        session.get("avg_pace"),
    )


@dataclass(frozen=True, slots=True)
class SessionEvidenceReference:
    source_path: str
    session: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class SessionEvidenceIndex:
    by_activity_id: Mapping[str, SessionEvidenceReference] = field(repr=False)
    by_identity: Mapping[
        tuple[Any, Any, Any, Any, Any],
        tuple[SessionEvidenceReference, ...],
    ] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "by_activity_id",
            MappingProxyType(dict(self.by_activity_id)),
        )
        object.__setattr__(
            self,
            "by_identity",
            MappingProxyType(dict(self.by_identity)),
        )

    def resolve(
        self,
        candidate: Mapping[str, Any],
    ) -> SessionEvidenceReference | None:
        activity_id = candidate.get("activity_id")
        if activity_id is not None:
            canonical_id = _safe_canonical_activity_id(activity_id)
            if canonical_id is not None:
                reference = self.by_activity_id.get(canonical_id)
                if reference is not None:
                    return reference
        identity_matches = self.by_identity.get(_session_identity(candidate), ())
        return identity_matches[0] if len(identity_matches) == 1 else None

    def project_supporting_session(
        self,
        target: dict[str, Any],
        reference: SessionEvidenceReference,
    ) -> None:
        source = reference.session
        target.pop("type", None)
        target["source_path"] = reference.source_path
        target["date"] = deepcopy(source.get("date"))
        target["source_activity_type"] = deepcopy(
            source.get("source_activity_type")
        )
        target["distance_km"] = deepcopy(source.get("distance_km"))
        target["duration_min"] = deepcopy(source.get("duration_min"))
        target["avg_hr"] = deepcopy(source.get("avg_hr"))
        target["avg_pace"] = deepcopy(source.get("avg_pace"))
        target["training_effect_aerobic"] = deepcopy(
            source.get("training_effect_aerobic")
        )
        target["training_effect_anaerobic"] = deepcopy(
            source.get("training_effect_anaerobic")
        )
        if source.get("source_activity_type") == "strength_training":
            target["strength"] = deepcopy(source.get("strength"))
        target["activity_id"] = deepcopy(source.get("activity_id"))


def build_session_evidence_index(weekly_analysis: Any) -> SessionEvidenceIndex:
    """Index final deterministic Session facts for evidence path reconciliation."""

    by_activity_id: dict[str, SessionEvidenceReference] = {}
    by_identity: dict[
        tuple[Any, Any, Any, Any, Any],
        list[SessionEvidenceReference],
    ] = {}
    if not isinstance(weekly_analysis, list):
        weekly_analysis = []
    for week_index, week in enumerate(weekly_analysis):
        if not isinstance(week, Mapping):
            continue
        sessions = week.get("sessions")
        if not isinstance(sessions, list):
            continue
        for session_index, session in enumerate(sessions):
            if not isinstance(session, Mapping):
                continue
            source_path = (
                f"weekly_analysis[{week_index}].sessions[{session_index}]"
            )
            reference = SessionEvidenceReference(
                source_path=source_path,
                session=deepcopy(dict(session)),
            )
            activity_id = session.get("activity_id")
            if activity_id is not None:
                canonical_id = _safe_canonical_activity_id(activity_id)
                if canonical_id is not None:
                    if canonical_id in by_activity_id:
                        raise SessionFactContractError(
                            "duplicate deterministic Session facts in evidence index"
                        )
                    by_activity_id[canonical_id] = reference
            by_identity.setdefault(_session_identity(session), []).append(reference)
    return SessionEvidenceIndex(
        by_activity_id=by_activity_id,
        by_identity={
            identity: tuple(references)
            for identity, references in by_identity.items()
        },
    )


__all__ = [
    "CoachSession",
    "RunningSegmentFacts",
    "RunningSessionFacts",
    "SegmentFacts",
    "SessionEvidenceIndex",
    "SessionEvidenceReference",
    "SessionFactContractError",
    "SessionFactSet",
    "SessionFacts",
    "SwimmingSegmentFacts",
    "SwimmingSessionFacts",
    "build_session_evidence_index",
    "build_session_facts",
    "reconcile_session_facts",
]
