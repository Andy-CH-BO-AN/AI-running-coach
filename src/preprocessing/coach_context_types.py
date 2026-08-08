from __future__ import annotations

from typing import Any, TypedDict

from src.preprocessing.coach_context_session_facts import CoachSession

class CoachDataQuality(TypedDict, total=False):
    status: str
    message: str
    missing_fields: list[str]


class CoachSessionCounts(TypedDict, total=False):
    total: int
    by_source_activity_type: dict[str, int]


class CoachWeek(TypedDict, total=False):
    week_label: str
    week_start: str
    week_end: str
    derived_total_distance_km: float
    derived_total_duration_min: float
    derived_training_load: float
    sessions: list[CoachSession]
    session_counts: CoachSessionCounts
    data_quality: CoachDataQuality
    risk_flags: list[str]
    intensity_focuses: list[dict[str, str]]
    cross_training_focus: dict[str, Any] | None


class HrZone(TypedDict, total=False):
    zone: int
    name: str
    minutes: float
    percentage: float


class HrZoneDistribution(TypedDict, total=False):
    period_weeks: int
    zones: list[HrZone]
    total_minutes: float
    is_polarized: bool


class NextWeekDaySeed(TypedDict, total=False):
    date: str
    day_of_week: str
    available_for_training: bool
    preferred_long_run_day: bool


class NextWeekPlanSeed(TypedDict, total=False):
    week_start: str
    days: list[NextWeekDaySeed]


class EvidenceFact(TypedDict, total=False):
    fact_id: str
    label: str
    value: Any
    unit: str | None
    source_path: str


class DeterministicCoachContext(TypedDict, total=False):
    meta: dict[str, Any]
    deterministic_fields: list[str]
    athlete_profile: dict[str, Any]
    physio_metrics: dict[str, Any]
    pb_validation_seed: list[dict[str, Any]]
    weekly_analysis: list[CoachWeek]
    hr_zone_distribution: HrZoneDistribution
    running_mechanics: dict[str, Any]
    cross_training: dict[str, Any]
    load_assessment: dict[str, Any]
    next_week_plan_seed: NextWeekPlanSeed
    evidence_facts: list[EvidenceFact]
