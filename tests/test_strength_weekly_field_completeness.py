from copy import deepcopy

from src.preprocessing.weekly_report import _strength_training_summary


def _partial_strength_session():
    return {
        "activity_id": 42,
        "source_activity_type": "strength_training",
        "training_load": None,
        "data_quality": {
            "status": "partial",
            "missing_fields": ["training_load"],
        },
        "strength": {
            "total_sets": 8,
            "active_sets": 8,
            "total_reps": 64,
            "total_volume_kg": 2500.0,
            "sets": [],
        },
    }


def test_strength_weekly_aggregates_ignore_unrelated_partial_fields():
    summary = _strength_training_summary([_partial_strength_session()])

    assert summary == {
        "sessions_count": 1,
        "total_sets": 8,
        "total_reps": 64,
        "total_volume_kg": 2500.0,
    }


def test_strength_weekly_aggregates_are_nullable_per_field():
    missing_reps = _partial_strength_session()
    missing_reps["strength"] = deepcopy(missing_reps["strength"])
    missing_reps["strength"]["total_reps"] = None

    reps_summary = _strength_training_summary([missing_reps])
    assert reps_summary["total_sets"] == 8
    assert reps_summary["total_reps"] is None
    assert reps_summary["total_volume_kg"] == 2500.0

    missing_volume = _partial_strength_session()
    missing_volume["strength"] = deepcopy(missing_volume["strength"])
    missing_volume["strength"]["total_volume_kg"] = None

    volume_summary = _strength_training_summary([missing_volume])
    assert volume_summary["total_sets"] == 8
    assert volume_summary["total_reps"] == 64
    assert volume_summary["total_volume_kg"] is None
