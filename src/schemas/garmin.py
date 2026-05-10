from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GarminSwimmingLength(BaseModel):
    model_config = ConfigDict(extra="allow")

    length_index: int | None = None
    distance: float | None = None
    duration: float | None = None
    swim_stroke: str | None = None
    strokes: int | None = None
    swolf: float | None = None
    avg_hr: float | None = None


class GarminActivitySplit(BaseModel):
    model_config = ConfigDict(extra="allow")

    split_index: int
    distance: float | None = None
    duration: float | None = None
    pace: float | None = None
    average_heart_rate: float | None = None
    max_heart_rate: float | None = None
    avg_cadence: float | None = None
    max_cadence: float | None = None
    lengths: list[GarminSwimmingLength] = Field(default_factory=list)


class GarminActivity(BaseModel):
    model_config = ConfigDict(extra="allow")

    activity_id: int
    type: str
    date: str | None = None
    distance: float | None = None
    duration: float | None = None
    average_pace: float | None = None
    average_heart_rate: float | None = None
    splits: list[GarminActivitySplit] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class GarminUserProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    max_heart_rate: float | None = None
    resting_heart_rate: float | None = None
    vo2max_running: float | None = None
    lactate_threshold_speed_mps: float | None = None
    lactate_threshold_pace: str | None = None
    lactate_threshold_heart_rate: float | None = None
    weight_kg: float | None = None
    height_cm: float | None = None
    available_training_days: list[str] = Field(default_factory=list)
    preferred_long_training_days: list[str] = Field(default_factory=list)
    pr_running: dict[str, Any] = Field(default_factory=dict)
    pr_swimming: dict[str, Any] = Field(default_factory=dict)
    pr_cycling: dict[str, Any] = Field(default_factory=dict)
