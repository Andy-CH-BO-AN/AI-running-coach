from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.db.repositories import save_activity_features


DEFAULT_ACTIVITY_FEATURES: dict[str, Any] = {
    "classification": {
        "workout_type": "unknown",
        "confidence": "low",
    },
    "hr": {
        "z1_seconds": 0,
        "z2_seconds": 0,
        "z3_seconds": 0,
        "z4_seconds": 0,
        "z5_seconds": 0,
        "hr_drift": None,
        "max_hr": None,
    },
    "pace": {
        "fastest_split_pace": None,
        "slowest_split_pace": None,
        "pace_variability": None,
    },
    "intervals": {
        "interval_count": None,
        "work_rest_ratio": None,
    },
    "running_dynamics": {
        "avg_cadence": None,
        "avg_ground_contact_time": None,
        "avg_vertical_ratio": None,
        "efficiency_decay": None,
    },
}


def save_default_activity_features(
    session: Session,
    activity_id,
    feature_version: str = "placeholder:v1",
):
    return save_activity_features(
        session=session,
        activity_id=activity_id,
        feature_version=feature_version,
        algorithm_version="placeholder",
        features=DEFAULT_ACTIVITY_FEATURES,
    )

