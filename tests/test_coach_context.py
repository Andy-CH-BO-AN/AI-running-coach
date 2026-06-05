import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.preprocessing.coach_context import (
    build_deterministic_coach_context,
    enforce_deterministic_report_fields,
)


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
                    "stride_length": 112,
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
    assert current_week["session_counts"] == {
        "total": 2,
        "by_type": {"easy": 2},
        "by_source_activity_type": {"running": 2},
    }
    assert current_week["data_quality"]["status"] == "partial"
    assert current_week["data_quality"]["missing_fields"] == ["training_load"]
    assert "heat_stress" in current_week["risk_flags"]
    assert len(current_week["sessions"][0]["segments"]) == 1
    assert current_week["sessions"][0]["segments"][0]["stride_length_m"] == 1.12


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


def test_running_mechanics_use_active_segments_for_cadence_and_stride():
    processed_data = [
        {
            "activity_id": 203,
            "type": "running",
            "date": "2026-05-12",
            "distance_km": 3,
            "advanced_metrics": {
                "avg_cadence": 120,
                "stride_length": 75,
                "ground_contact_time": 300,
                "vertical_oscillation": 10,
                "training_load": 30,
                "hr_zones": {
                    "hr_zone_1": 600,
                    "hr_zone_2": 0,
                    "hr_zone_3": 0,
                    "hr_zone_4": 0,
                    "hr_zone_5": 0,
                },
            },
            "splits": [
                {
                    "split_index": 1,
                    "duration": 5,
                    "avg_cadence": 176,
                    "stride_length": 110,
                    "ground_contact_time": 240,
                    "vertical_oscillation": 8,
                },
                {
                    "split_index": 2,
                    "duration": 2,
                    "avg_cadence": 35,
                    "stride_length": 55,
                    "ground_contact_time": 390,
                    "vertical_oscillation": 13,
                },
                {
                    "split_index": 3,
                    "duration": 5,
                    "avg_cadence": 180,
                    "stride_length": 120,
                    "ground_contact_time": 230,
                    "vertical_oscillation": 7,
                },
            ],
        }
    ]

    context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=[{"activity_id": 203, "duration": 12}],
        today="2026-05-14",
    )

    mechanics = context["running_mechanics"]
    assert mechanics["cadence_avg"]["value"] == 178
    assert mechanics["stride_length_m"]["value"] == 1.15
    assert mechanics["ground_contact_ms"]["value"] == 235
    assert mechanics["vertical_oscillation_cm"]["value"] == 7.5


def test_enforce_updates_stale_mechanics_assessments_when_values_change():
    processed_data = [
        {
            "activity_id": 204,
            "type": "running",
            "date": "2026-05-12",
            "distance_km": 3,
            "advanced_metrics": {"training_load": 30},
            "splits": [
                {
                    "duration": 5,
                    "avg_cadence": 176,
                    "stride_length": 110,
                    "ground_contact_time": 240,
                    "vertical_oscillation": 8,
                }
            ],
        }
    ]
    context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=[{"activity_id": 204, "duration": 5}],
        today="2026-05-14",
    )
    ai_report = {
        "meta": {"today": "2026-05-14"},
        "weekly_analysis": [],
        "running_mechanics": {
            "cadence_avg": {"value": 90, "unit": "spm", "assessment": "極低"},
            "stride_length_m": {"value": 0.4, "unit": "m", "assessment": "偏短"},
            "running_economy_score": 10,
            "improvement_tips": ["把步頻提升到 170+ spm"],
        },
    }

    report = enforce_deterministic_report_fields(ai_report, context)
    mechanics = report["running_mechanics"]

    assert mechanics["cadence_avg"]["value"] == 176
    assert mechanics["cadence_avg"]["assessment"] == "有效跑步段步頻落在合理範圍，休息段已排除。"
    assert mechanics["stride_length_m"]["value"] == 1.1
    assert mechanics["stride_length_m"]["assessment"] == "有效跑步段步幅合理，可隨速度課逐步提升推進效率。"
    assert mechanics["improvement_tips"] == [
        "維持目前有效跑步段步頻與步幅，優先把品質穩定複製到節奏跑與間歇主課表。"
    ]


def test_enforce_repoints_evidence_source_paths_by_activity_id():
    processed_data = [
        {
            "activity_id": 205,
            "type": "running",
            "date": "2026-05-12",
            "distance_km": 5,
            "performance_formatted": "06:00 /km",
            "avg_hr": 150,
            "advanced_metrics": {"training_load": 30},
            "splits": [{"duration": 6, "distance": 1, "avg_cadence": 172}],
        },
        {
            "activity_id": 206,
            "type": "running",
            "date": "2026-05-12",
            "distance_km": 0.4,
            "performance_formatted": "03:20 /km",
            "avg_hr": 145,
            "advanced_metrics": {"training_load": 10},
            "splits": [{"duration": 0.5, "distance": 0.1, "avg_cadence": 150}],
        },
    ]
    context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=[
            {"activity_id": 205, "duration": 30},
            {"activity_id": 206, "duration": 3},
        ],
        today="2026-05-14",
    )
    ai_report = {
        "meta": {"today": "2026-05-14"},
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "sessions": [
                    {"activity_id": 206, "date": "2026-05-12", "type": "interval"},
                    {"activity_id": 205, "date": "2026-05-12", "type": "easy"},
                ],
            }
        ],
        "evidence_links": [
            {
                "supporting_sessions": [
                    {
                        "activity_id": 205,
                        "date": "2026-05-12",
                        "type": "easy",
                        "distance_km": 5,
                        "duration_min": 30,
                        "avg_hr": 150,
                        "avg_pace": "06:00",
                        "source_path": "weekly_analysis[0].sessions[1]",
                        "reason": "保留原因",
                    }
                ]
            }
        ],
    }

    report = enforce_deterministic_report_fields(ai_report, context)
    supporting_session = report["evidence_links"][0]["supporting_sessions"][0]

    assert [session["activity_id"] for session in report["weekly_analysis"][0]["sessions"]] == [205, 206]
    assert supporting_session["activity_id"] == 205
    assert supporting_session["source_path"] == "weekly_analysis[0].sessions[0]"
    assert supporting_session["distance_km"] == 5
    assert supporting_session["avg_pace"] == "06:00"
    assert supporting_session["reason"] == "保留原因"


def test_enforce_repoints_evidence_metric_source_paths_by_activity_id():
    context = {
        "meta": {"today": "2026-05-23"},
        "weekly_analysis": [
            {
                "week_start": "2026-05-18",
                "sessions": [
                    {
                        "activity_id": 301,
                        "date": "2026-05-18",
                        "type": "bike",
                        "distance_km": 2.19,
                        "duration_min": 11.4,
                        "avg_hr": 116,
                        "avg_pace": "11.5 km/h",
                    },
                    {
                        "activity_id": 302,
                        "date": "2026-05-22",
                        "type": "easy",
                        "distance_km": 5.35,
                        "duration_min": 34.7,
                        "avg_hr": 150,
                        "avg_pace": "6:29",
                    },
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-25", "days": []},
    }
    ai_report = {
        "meta": {"today": "2026-05-23"},
        "weekly_analysis": [
            {
                "week_start": "2026-05-18",
                "sessions": [
                    {
                        "activity_id": 302,
                        "date": "2026-05-22",
                        "type": "easy",
                        "distance_km": 5.35,
                        "duration_min": 34.7,
                        "avg_hr": 150,
                        "avg_pace": "6:29",
                    },
                    {
                        "activity_id": 301,
                        "date": "2026-05-18",
                        "type": "bike",
                        "distance_km": 2.19,
                        "duration_min": 11.4,
                        "avg_hr": 116,
                        "avg_pace": "11.5 km/h",
                    },
                ],
            }
        ],
        "evidence_links": [
            {
                "supporting_metrics": [
                    {
                        "label": "5/22 輕鬆跑平均心率",
                        "value": 150,
                        "unit": "bpm",
                        "source_path": "weekly_analysis[0].sessions[0].avg_hr",
                        "activity_id": 302,
                    }
                ]
            }
        ],
        "next_week_plan": {"week_start": "2026-05-25", "days": []},
    }

    report = enforce_deterministic_report_fields(ai_report, context)
    supporting_metric = report["evidence_links"][0]["supporting_metrics"][0]

    assert [session["activity_id"] for session in report["weekly_analysis"][0]["sessions"]] == [301, 302]
    assert supporting_metric["source_path"] == "weekly_analysis[0].sessions[1].avg_hr"


def test_enforce_repoints_evidence_metric_source_paths_by_session_identity_without_activity_id():
    context = {
        "meta": {"today": "2026-05-23"},
        "weekly_analysis": [
            {
                "week_start": "2026-05-18",
                "sessions": [
                    {
                        "activity_id": 401,
                        "date": "2026-05-18",
                        "type": "bike",
                        "distance_km": 2.19,
                        "duration_min": 11.4,
                        "avg_hr": 116,
                        "avg_pace": "11.5 km/h",
                    },
                    {
                        "activity_id": 402,
                        "date": "2026-05-22",
                        "type": "easy",
                        "distance_km": 5.35,
                        "duration_min": 34.7,
                        "avg_hr": 150,
                        "avg_pace": "6:29",
                    },
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-25", "days": []},
    }
    ai_report = {
        "meta": {"today": "2026-05-23"},
        "weekly_analysis": [
            {
                "week_start": "2026-05-18",
                "sessions": [
                    {
                        "activity_id": 402,
                        "date": "2026-05-22",
                        "type": "easy",
                        "distance_km": 5.35,
                        "duration_min": 34.7,
                        "avg_hr": 150,
                        "avg_pace": "6:29",
                    },
                    {
                        "activity_id": 401,
                        "date": "2026-05-18",
                        "type": "bike",
                        "distance_km": 2.19,
                        "duration_min": 11.4,
                        "avg_hr": 116,
                        "avg_pace": "11.5 km/h",
                    },
                ],
            }
        ],
        "evidence_links": [
            {
                "supporting_metrics": [
                    {
                        "label": "5/22 輕鬆跑平均心率",
                        "value": 150,
                        "unit": "bpm",
                        "source_path": "weekly_analysis[0].sessions[0].avg_hr",
                    }
                ]
            }
        ],
        "next_week_plan": {"week_start": "2026-05-25", "days": []},
    }

    report = enforce_deterministic_report_fields(ai_report, context)
    supporting_metric = report["evidence_links"][0]["supporting_metrics"][0]

    assert [session["activity_id"] for session in report["weekly_analysis"][0]["sessions"]] == [401, 402]
    assert supporting_metric["source_path"] == "weekly_analysis[0].sessions[1].avg_hr"


def test_weekly_session_counts_include_cross_training_distribution():
    processed_data = [
        {
            "activity_id": 207,
            "type": "running",
            "date": "2026-05-12",
            "distance_km": 5,
            "performance_formatted": "06:00 /km",
            "advanced_metrics": {"training_load": 20},
        },
        {
            "activity_id": 208,
            "type": "cycling",
            "date": "2026-05-12",
            "distance_km": 10,
        },
        {
            "activity_id": 209,
            "type": "swimming",
            "date": "2026-05-13",
            "distance_km": 1,
        },
    ]

    context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=[
            {"activity_id": 207, "duration": 30},
            {"activity_id": 208, "duration": 25},
            {"activity_id": 209, "duration": 20},
        ],
        today="2026-05-14",
    )

    counts = context["weekly_analysis"][0]["session_counts"]
    assert counts == {
        "total": 3,
        "by_type": {"bike": 1, "easy": 1, "swim": 1},
        "by_source_activity_type": {"cycling": 1, "running": 1, "swimming": 1},
    }


def test_cross_training_segments_do_not_emit_running_mechanics():
    processed_data = [
        {
            "activity_id": 208,
            "type": "cycling",
            "date": "2026-05-12",
            "distance_km": 10,
            "splits": [
                {
                    "split_index": 1,
                    "distance": 10,
                    "duration": 25,
                    "average_heart_rate": 132,
                    "avg_cadence": 88,
                    "stride_length": 350,
                }
            ],
        },
        {
            "activity_id": 209,
            "type": "swimming",
            "date": "2026-05-13",
            "distance_km": 1,
            "splits": [
                {
                    "split_index": 1,
                    "distance": 0.1,
                    "duration": 2,
                    "average_heart_rate": 128,
                    "avg_cadence": 22,
                    "stride_length": 3000,
                }
            ],
        },
    ]

    context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=[
            {"activity_id": 208, "duration": 25},
            {"activity_id": 209, "duration": 20},
        ],
        today="2026-05-14",
    )

    sessions = {session["type"]: session for session in context["weekly_analysis"][0]["sessions"]}
    for session_type in ("bike", "swim"):
        segment = sessions[session_type]["segments"][0]
        assert "cadence" not in segment
        assert "stride_length_m" not in segment


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
    assert physio["resting_heart_rate"]["value"] == 50
    assert physio["pace_zones"][0]["hr_min"] == 140
    assert physio["pace_zones"][0]["hr_max"] == 155


def test_physio_seed_estimates_resting_hr_when_garmin_value_missing():
    user_data = _sample_user_data()
    user_data["resting_heart_rate"] = None
    context = build_deterministic_coach_context(
        processed_data=[
            {
                "activity_id": 401,
                "type": "cycling",
                "date": "2026-05-12",
                "distance_km": 6,
                "duration_min": 24,
                "avg_hr": 96,
            },
            {
                "activity_id": 402,
                "type": "running",
                "date": "2026-05-13",
                "distance_km": 5,
                "duration_min": 32,
                "avg_hr": 132,
            },
        ],
        user_data=user_data,
        raw_activities=[],
        today="2026-05-14",
    )

    physio = context["physio_metrics"]
    assert physio["resting_heart_rate"]["value"] == 56
    assert physio["resting_heart_rate"]["source"] == "estimated_from_lowest_activity_avg_hr"
    assert physio["pace_zones"][0]["hr_min"] is not None


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


def test_enforce_deterministic_report_fields_restores_pruned_sessions_and_metrics():
    processed_data = [
        {
            "activity_id": 301,
            "type": "running",
            "date": "2026-05-05",
            "distance_km": 5,
            "performance_formatted": "05:00 /km",
            "advanced_metrics": {
                "training_load": 30,
                "hr_zones": {
                    "hr_zone_1": 600,
                    "hr_zone_2": 0,
                    "hr_zone_3": 0,
                    "hr_zone_4": 0,
                    "hr_zone_5": 0,
                },
            },
        },
        {
            "activity_id": 302,
            "type": "running",
            "date": "2026-05-06",
            "distance_km": 7,
            "performance_formatted": "05:20 /km",
            "advanced_metrics": {
                "training_load": 40,
                "hr_zones": {
                    "hr_zone_1": 0,
                    "hr_zone_2": 1200,
                    "hr_zone_3": 0,
                    "hr_zone_4": 0,
                    "hr_zone_5": 0,
                },
            },
        },
    ]
    context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=[
            {"activity_id": 301, "duration": 25},
            {"activity_id": 302, "duration": 35},
        ],
        today="2026-05-14",
    )
    ai_report = {
        "meta": {"today": "2026-05-12", "analysis_period_weeks": 4},
        "weekly_analysis": [
            {
                "week_start": "2026-05-04",
                "week_label": "AI label",
                "key_observation": "保留 AI 觀察",
                "weekly_assessment": "保留 AI 解讀",
                "weekly_recommendation": "保留 AI 建議",
                "total_distance_km": 5,
                "sessions": [
                    {
                        "activity_id": 302,
                        "date": "2026-05-06",
                        "coaching_note": "保留單次活動教練備註",
                    }
                ],
            }
        ],
        "hr_zone_distribution": {
            "zones": [{"zone": 1, "minutes": 999, "percentage": 100}],
            "assessment": "保留 HR 解讀",
        },
        "physio_metrics": {
            "vo2max": {"value": 1, "unit": "bad", "assessment": "保留 VO2max 解讀"},
            "pace_zones": [{"zone": 5, "pace_min": "00:00", "pace_max": "00:00"}],
        },
        "load_assessment": {
            "current_tss_weekly": 999,
            "status": "overtraining",
            "label": "保留負荷標籤",
        },
        "next_week_plan": {
            "week_start": "2026-05-19",
            "days": [
                {
                    "date": "2026-05-18",
                    "day_of_week": "Tue",
                    "session_type": "easy",
                    "title": "保留課表",
                    "distance_km": 3,
                    "duration_min": 20,
                    "intensity": "easy",
                    "key_workout": False,
                }
            ],
        },
    }

    report = enforce_deterministic_report_fields(ai_report, context)
    restored_week = report["weekly_analysis"][1]

    assert report["meta"]["today"] == "2026-05-14"
    assert restored_week["week_start"] == "2026-05-04"
    assert restored_week["key_observation"] == "保留 AI 觀察"
    assert "total_distance_km" not in restored_week
    assert [session["activity_id"] for session in restored_week["sessions"]] == [301, 302]
    assert restored_week["sessions"][1]["coaching_note"] == "保留單次活動教練備註"
    assert report["hr_zone_distribution"]["assessment"] == "保留 HR 解讀"
    assert report["hr_zone_distribution"]["zones"] == context["hr_zone_distribution"]["zones"]
    assert report["physio_metrics"]["vo2max"]["value"] == 53
    assert report["physio_metrics"]["vo2max"]["assessment"] == "保留 VO2max 解讀"
    assert report["physio_metrics"]["pace_zones"][4]["pace_max"] is None
    assert report["load_assessment"]["current_tss_weekly"] == context["load_assessment"]["current_tss_weekly"]
    assert report["load_assessment"]["label"] == "保留負荷標籤"
    assert report["next_week_plan"]["week_start"] == "2026-05-18"
    assert report["next_week_plan"]["days"][0]["day_of_week"] == "Mon"
    assert report["next_week_plan"]["total_distance_km"] == 3
