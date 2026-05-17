import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.preprocessing.coach_context import (
    build_deterministic_coach_context,
    enforce_deterministic_report_fields,
)
from src.preprocessing.data_processor import preprocess_data


SESSION_OUTPUT_KEYS = {
    "activity_id",
    "date",
    "type",
    "distance_km",
    "duration_min",
    "training_load",
    "avg_hr",
    "avg_pace",
    "training_effect_aerobic",
    "training_effect_anaerobic",
    "segments",
    "environment",
    "coaching_note",
}

WEEKLY_TOTAL_KEYS = {
    "total_distance_km",
    "total_duration_min",
    "training_load",
    "derived_total_distance_km",
    "derived_total_duration_min",
    "derived_training_load",
}


def _sample_raw_activities():
    return [
        {
            "activity_id": 9001,
            "type": "running",
            "date": "2026-05-12",
            "distance": 5.0,
            "duration": 25.0,
            "average_heart_rate": 151,
            "splits": [
                {
                    "split_index": 1,
                    "distance": 1.0,
                    "duration": 5.0,
                    "pace": 5.0,
                    "average_heart_rate": 148,
                    "avg_cadence": 176,
                    "temperature": 28,
                    "stride_length": 112,
                    "ground_contact_time": 242,
                    "vertical_oscillation": 8.0,
                }
            ],
            "raw_data": {
                "training_stress_score": 42.4,
                "aerobic_training_effect": 3.1,
                "anaerobic_training_effect": 0.4,
                "hr_zone_1": 300,
                "hr_zone_2": 900,
                "hr_zone_3": 240,
                "hr_zone_4": 60,
                "hr_zone_5": 0,
                "cadence": 176,
                "stride_length": 112,
                "ground_contact_time": 242,
                "vertical_oscillation": 8.0,
                "temperature": 28,
            },
        },
        {
            "activity_id": 9002,
            "type": "cycling",
            "date": "2026-05-13",
            "distance": 20.0,
            "duration": 60.0,
            "average_heart_rate": 132,
            "splits": [
                {
                    "split_index": 1,
                    "distance": 20.0,
                    "duration": 60.0,
                    "pace": None,
                    "speed_kmh": 20.0,
                }
            ],
            "raw_data": {
                "training_stress_score": 30.0,
                "power_avg": 165,
                "power_max": 250,
                "cadence": 88,
                "hr_zone_1": 600,
                "hr_zone_2": 2400,
                "hr_zone_3": 600,
                "hr_zone_4": 0,
                "hr_zone_5": 0,
                "average_speed_kmh": 20.0,
            },
        },
    ]


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


def _build_processed_and_context():
    raw_activities = _sample_raw_activities()
    processed_data = preprocess_data(raw_activities)
    context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=raw_activities,
        today="2026-05-14",
    )
    return processed_data, context


def test_processed_to_deterministic_context_contract():
    processed_data, context = _build_processed_and_context()

    assert [activity["activity_id"] for activity in processed_data] == [9001, 9002]
    assert processed_data[0]["performance_formatted"] == "5:00 /km"
    assert processed_data[1]["performance_formatted"] == "20.0 km/h"
    assert processed_data[1]["splits"][0]["speed_kmh"] == 20.0
    assert processed_data[1]["splits"][0]["pace"] is None

    assert context["meta"]["today"] == "2026-05-14"
    assert context["meta"]["analysis_period_weeks"] == 4
    assert context["meta"]["source"] == "deterministic_coach_context:v1"
    assert len(context["weekly_analysis"]) == 4

    current_week = context["weekly_analysis"][0]
    assert current_week["week_start"] == "2026-05-11"
    assert current_week["week_end"] == "2026-05-17"
    assert current_week["derived_total_distance_km"] == 25.0
    assert current_week["derived_total_duration_min"] == 85.0
    assert current_week["derived_training_load"] == 72.4
    assert current_week["session_counts"] == {
        "total": 2,
        "by_type": {"bike": 1, "easy": 1},
        "by_source_activity_type": {"cycling": 1, "running": 1},
    }
    assert "heat_stress" in current_week["risk_flags"]
    assert current_week["sessions"][0]["activity_id"] == 9001
    assert current_week["sessions"][0]["segments"][0]["avg_pace"] == "5:00"
    assert current_week["sessions"][0]["segments"][0]["stride_length_m"] == 1.12

    zones = context["hr_zone_distribution"]["zones"]
    assert [zone["zone"] for zone in zones] == [1, 2, 3, 4, 5]
    assert round(sum(zone["percentage"] for zone in zones), 1) == 100.0
    assert [zone["zone"] for zone in context["physio_metrics"]["pace_zones"]] == [1, 2, 3, 4, 5]
    assert context["next_week_plan_seed"]["week_start"] == "2026-05-18"
    assert [day["day_of_week"] for day in context["next_week_plan_seed"]["days"]] == [
        "Mon",
        "Tue",
        "Wed",
        "Thu",
        "Fri",
        "Sat",
        "Sun",
    ]


def test_enforced_report_preserves_dashboard_json_contract():
    _processed_data, context = _build_processed_and_context()
    ai_report = {
        "meta": {"today": "2026-05-01", "analysis_period_weeks": 1},
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "week_label": "AI label",
                "total_distance_km": 999,
                "derived_training_load": 999,
                "key_observation": "Keep AI observation",
                "weekly_assessment": "Keep AI assessment",
                "weekly_recommendation": "Keep AI recommendation",
                "sessions": [
                    {
                        "activity_id": 9002,
                        "date": "2026-05-13",
                        "coaching_note": "Keep bike note",
                    }
                ],
            }
        ],
        "hr_zone_distribution": {
            "zones": [{"zone": 1, "minutes": 999, "percentage": 100}],
            "assessment": "Keep HR assessment",
        },
        "physio_metrics": {
            "vo2max": {"value": 1, "unit": "bad", "assessment": "Keep VO2max assessment"},
        },
        "running_mechanics": {
            "cadence_avg": {"value": 90, "unit": "spm", "assessment": "stale"},
        },
        "load_assessment": {
            "current_tss_weekly": 999,
            "status": "overtraining",
            "label": "Keep load label",
        },
        "next_week_plan": {
            "week_start": "2026-05-19",
            "days": [
                {
                    "date": "2026-05-18",
                    "day_of_week": "Tue",
                    "session_type": "easy",
                    "title": "Keep workout",
                    "description": "AI workout",
                    "distance_km": 4.5,
                    "duration_min": 30,
                    "intensity": "easy",
                    "key_workout": False,
                }
            ],
        },
    }

    report = enforce_deterministic_report_fields(ai_report, context)

    assert report["meta"]["today"] == "2026-05-14"
    assert report["meta"]["analysis_period_weeks"] == 4
    assert len(report["weekly_analysis"]) == 4

    current_week = report["weekly_analysis"][0]
    assert WEEKLY_TOTAL_KEYS.isdisjoint(current_week)
    assert current_week["week_label"] == "05/11-05/17"
    assert current_week["key_observation"] == "Keep AI observation"
    assert [session["activity_id"] for session in current_week["sessions"]] == [9001, 9002]
    assert set(current_week["sessions"][0]) == SESSION_OUTPUT_KEYS
    assert current_week["sessions"][1]["coaching_note"] == "Keep bike note"

    assert report["hr_zone_distribution"]["assessment"] == "Keep HR assessment"
    assert report["hr_zone_distribution"]["zones"] == context["hr_zone_distribution"]["zones"]
    assert report["physio_metrics"]["vo2max"]["value"] == 53
    assert report["physio_metrics"]["vo2max"]["assessment"] == "Keep VO2max assessment"
    assert [zone["zone"] for zone in report["physio_metrics"]["pace_zones"]] == [1, 2, 3, 4, 5]
    assert report["running_mechanics"]["cadence_avg"]["value"] == 176
    assert report["load_assessment"]["current_tss_weekly"] == context["load_assessment"]["current_tss_weekly"]
    assert report["load_assessment"]["label"] == "Keep load label"

    next_week = report["next_week_plan"]
    assert next_week["week_start"] == "2026-05-18"
    assert len(next_week["days"]) == 7
    assert [day["day_of_week"] for day in next_week["days"]] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert next_week["days"][0]["title"] == "Keep workout"
    assert next_week["days"][1]["title"] == "恢復日"
    assert next_week["total_distance_km"] == 4.5
