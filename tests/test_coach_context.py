import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.preprocessing.coach_context import build_deterministic_coach_context


def _sample_user_data():
    return {
        "max_heart_rate": 200,
        "resting_heart_rate": 50,
        "vo2max_running": 53,
        "lactate_threshold_pace": "04:24 /km",
        "lactate_threshold_heart_rate": 188,
        "available_training_days": ["MONDAY", "WEDNESDAY"],
        "preferred_long_training_days": ["SUNDAY"],
        "pr_running": {"5km": "19:57 (3:59 /km)"},
    }


def test_builds_monday_week_buckets_and_derived_weekly_metrics():
    processed_data = [
        {
            "activity_id": 101,
            "type": "running",
            "date": "2026-05-12",
            "distance_km": 5.125,
            "performance_formatted": "05:00 /km",
            "avg_hr": 150,
            "splits": [
                {
                    "split_index": 1,
                    "distance": 1.0,
                    "duration": 5.0,
                    "pace": "05:00 /km",
                    "average_heart_rate": 148,
                    "avg_cadence": 174,
                    "temperature": 28,
                }
            ],
            "advanced_metrics": {
                "training_load": 42.26,
                "training_effect": {"aerobic": 3.1, "anaerobic": 0.4},
                "hr_zones": {
                    "hr_zone_1": 10,
                    "hr_zone_2": 20,
                    "hr_zone_3": 5,
                    "hr_zone_4": 0,
                    "hr_zone_5": 0,
                },
                "avg_cadence": 174,
                "ground_contact_time": 252,
                "vertical_oscillation": 8.1,
                "stride_length": 112,
            },
        },
        {
            "activity_id": 102,
            "type": "running",
            "date": "2026-05-12",
            "distance_km": 1,
            "performance_formatted": "04:05 /km",
            "avg_hr": 170,
            "splits": [],
            "advanced_metrics": {
                "hr_zones": {
                    "hr_zone_1": 0,
                    "hr_zone_2": 3,
                    "hr_zone_3": 2,
                    "hr_zone_4": 1,
                    "hr_zone_5": 0,
                }
            },
        },
    ]
    raw_activities = [
        {"activity_id": 101, "date": "2026-05-12", "type": "running", "duration": 31.26},
        {"activity_id": 102, "date": "2026-05-12", "type": "running", "duration": 5.0},
    ]

    context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=raw_activities,
        today="20260514",
    )

    current_week = context["weekly_analysis"][0]
    assert current_week["week_start"] == "2026-05-11"
    assert current_week["week_end"] == "2026-05-17"
    assert current_week["derived_total_distance_km"] == 6.13
    assert current_week["derived_total_duration_min"] == 36.3
    assert current_week["derived_training_load"] == 42.3
    assert current_week["data_quality"]["status"] == "partial"
    assert current_week["data_quality"]["missing_fields"] == ["training_load"]
    assert "heat_stress" in current_week["risk_flags"]
    assert len(current_week["sessions"][0]["segments"]) == 1


def test_hr_zones_are_sorted_and_percentages_are_deterministic():
    processed_data = [
        {
            "activity_id": 201,
            "type": "running",
            "date": "2026-05-12",
            "distance_km": 10,
            "avg_hr": 145,
            "advanced_metrics": {
                "training_load": 50,
                "hr_zones": {
                    "hr_zone_1": 30,
                    "hr_zone_2": 50,
                    "hr_zone_3": 10,
                    "hr_zone_4": 5,
                    "hr_zone_5": 5,
                },
            },
        }
    ]

    context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=[{"activity_id": 201, "duration": 60}],
        today="2026-05-14",
    )

    zones = context["hr_zone_distribution"]["zones"]
    assert [zone["zone"] for zone in zones] == [1, 2, 3, 4, 5]
    assert [zone["minutes"] for zone in zones] == [0.5, 0.8, 0.2, 0.1, 0.1]
    assert [zone["percentage"] for zone in zones] == [30, 50, 10, 5, 5]
    assert sum(zone["percentage"] for zone in zones) == 100


def test_hr_zone_seconds_are_exposed_as_minutes():
    processed_data = [
        {
            "activity_id": 202,
            "type": "running",
            "date": "2026-05-12",
            "distance_km": 3,
            "advanced_metrics": {
                "training_load": 20,
                "hr_zones": {
                    "hr_zone_1": 870,
                    "hr_zone_2": 0,
                    "hr_zone_3": 0,
                    "hr_zone_4": 0,
                    "hr_zone_5": 0,
                },
            },
        }
    ]

    context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=[{"activity_id": 202, "duration": 14.5}],
        today="2026-05-14",
    )

    zones = context["hr_zone_distribution"]["zones"]
    assert zones[0]["minutes"] == 14.5
    assert zones[0]["percentage"] == 100


def test_physio_seed_preserves_runner_pace_format_and_open_ended_z5():
    context = build_deterministic_coach_context(
        processed_data=[],
        user_data=_sample_user_data(),
        raw_activities=[],
        today="2026-05-14",
    )

    physio = context["physio_metrics"]
    assert physio["lactate_threshold"]["pace"]["value"] == "04:24"
    assert physio["pace_zones"][4]["zone"] == 5
    assert physio["pace_zones"][4]["pace_max"] is None
    assert "快端無上限" in physio["pace_zones"][4]["note"]


def test_next_week_seed_uses_training_preferences_without_ai():
    context = build_deterministic_coach_context(
        processed_data=[],
        user_data=_sample_user_data(),
        raw_activities=[],
        today="2026-05-14",
    )

    next_week = context["next_week_plan_seed"]
    assert next_week["week_start"] == "2026-05-18"
    assert next_week["days"][0] == {
        "date": "2026-05-18",
        "day_of_week": "Mon",
        "available_for_training": True,
        "preferred_long_run_day": False,
    }
    assert next_week["days"][6]["preferred_long_run_day"] is True
