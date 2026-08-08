import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.preprocessing.activity_window import normalize_activity_window
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


def _pace_fixture_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    pace = value.strip().split(" ", 1)[0]
    pieces = pace.split(":")
    if len(pieces) != 2:
        return value
    try:
        return int(pieces[0]) + float(pieces[1]) / 60
    except ValueError:
        return value


def _activity_window_fixture(
    processed_data: list[dict[str, Any]],
    raw_activities: list[dict[str, Any]] | None,
):
    """Translate focused legacy context fixtures into provider-shaped inputs."""

    raw_by_id = {
        str(activity.get("activity_id")): activity
        for activity in raw_activities or []
    }
    activities: list[dict[str, Any]] = []
    advanced_to_raw = {
        "avg_cadence": "cadence",
        "max_cadence": "max_cadence",
        "vertical_oscillation": "vertical_oscillation",
        "ground_contact_time": "ground_contact_time",
        "stride_length": "stride_length",
        "elevation_gain": "elevation_gain",
        "elevation_loss": "elevation_loss",
        "power_avg": "power_avg",
        "power_max": "power_max",
        "training_load": "training_stress_score",
        "training_stress_score": "training_stress_score",
        "stroke_count": "total_strokes",
        "avg_swolf": "avg_swolf",
        "pool_length": "pool_length",
        "stroke_style": "avg_stroke_type",
        "avg_stroke_cadence": "avg_stroke_cadence",
        "intensity_factor": "intensity_factor",
    }

    for processed in processed_data:
        activity_id = processed.get("activity_id")
        activity = dict(raw_by_id.get(str(activity_id), {}))
        activity["activity_id"] = activity_id
        for processed_key, raw_key in (
            ("type", "type"),
            ("date", "date"),
            ("distance_km", "distance"),
            ("duration_min", "duration"),
            ("avg_hr", "average_heart_rate"),
            ("max_hr", "max_heart_rate"),
        ):
            if processed_key in processed:
                activity[raw_key] = processed[processed_key]

        if "splits" in processed:
            activity["splits"] = [
                {
                    **split,
                    "pace": _pace_fixture_value(split.get("pace")),
                }
                for split in processed["splits"]
                if isinstance(split, dict)
            ]

        raw_data = dict(activity.get("raw_data") or {})
        advanced = processed.get("advanced_metrics") or {}
        for advanced_key, raw_key in advanced_to_raw.items():
            if advanced_key in advanced:
                raw_data[raw_key] = advanced[advanced_key]
        training_effect = advanced.get("training_effect") or {}
        if "aerobic" in training_effect:
            raw_data["aerobic_training_effect"] = training_effect["aerobic"]
        if "anaerobic" in training_effect:
            raw_data["anaerobic_training_effect"] = training_effect["anaerobic"]
        for zone_base in ("hr", "power"):
            zones = advanced.get(f"{zone_base}_zones") or {}
            for zone in range(1, 6):
                key = f"{zone_base}_zone_{zone}"
                if key in zones:
                    raw_data[key] = zones[key]
        activity["raw_data"] = raw_data
        activities.append(activity)

    return normalize_activity_window(activities)


def _build_context_fixture(
    *,
    processed_data: list[dict[str, Any]],
    user_data: dict[str, Any] | None = None,
    raw_activities: list[dict[str, Any]] | None = None,
    today: Any = None,
):
    return build_deterministic_coach_context(
        activity_window=_activity_window_fixture(processed_data, raw_activities),
        user_data=user_data,
        today=today,
    )


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

    context = _build_context_fixture(
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
        "by_source_activity_type": {"running": 2},
    }
    assert all("type" not in session for session in current_week["sessions"])
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

    context = _build_context_fixture(
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

    context = _build_context_fixture(
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

    context = _build_context_fixture(
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
    context = _build_context_fixture(
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
    context = _build_context_fixture(
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
    assert supporting_session["avg_pace"] == "6:00"
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

    context = _build_context_fixture(
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
        "by_source_activity_type": {"cycling": 1, "running": 1, "swimming": 1},
    }


def test_context_and_enforced_report_exclude_inferred_session_type():
    context = _build_context_fixture(
        processed_data=[
            {
                "activity_id": 210,
                "type": "running",
                "date": "2026-05-12",
                "distance_km": 0.62,
                "performance_value": 6.14,
                "performance_formatted": "06:08 /km",
                "avg_hr": 166,
            }
        ],
        user_data=_sample_user_data(),
        raw_activities=[{"activity_id": 210, "type": "running", "duration": 3.8}],
        today="2026-05-14",
    )

    context_session = context["weekly_analysis"][0]["sessions"][0]
    assert context_session["source_activity_type"] == "running"
    assert "type" not in context_session
    assert "by_type" not in context["weekly_analysis"][0]["session_counts"]

    report = enforce_deterministic_report_fields(
        {
            "weekly_analysis": [
                {
                    "week_start": "2026-05-11",
                    "sessions": [{"activity_id": 210, "type": "interval"}],
                }
            ],
            "evidence_links": [
                {
                    "supporting_sessions": [
                        {"activity_id": 210, "type": "interval"},
                        {
                            "date": "2026-05-12",
                            "source_activity_type": "running",
                            "distance_km": 0.62,
                            "duration_min": 3.8,
                            "avg_pace": "6:08",
                            "type": "interval",
                        },
                        {"date": "2026-05-09", "type": "interval"},
                    ]
                }
            ],
        },
        context,
    )

    assert "type" not in report["weekly_analysis"][0]["sessions"][0]
    assert "type" not in report["evidence_links"][0]["supporting_sessions"][0]
    fallback_session = report["evidence_links"][0]["supporting_sessions"][1]
    assert fallback_session["source_path"] == "weekly_analysis[0].sessions[0]"
    assert "type" not in fallback_session
    assert "type" not in report["evidence_links"][0]["supporting_sessions"][2]


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

    context = _build_context_fixture(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=[
            {"activity_id": 208, "duration": 25},
            {"activity_id": 209, "duration": 20},
        ],
        today="2026-05-14",
    )

    sessions = {
        session["source_activity_type"]: session
        for session in context["weekly_analysis"][0]["sessions"]
    }
    for source_activity_type in ("cycling", "swimming"):
        segment = sessions[source_activity_type]["segments"][0]
        assert "cadence" not in segment
        assert "stride_length_m" not in segment


def test_swimming_context_preserves_reliable_timings_and_rest_segment_order():
    processed_data = [
        {
            "activity_id": 211,
            "type": "swimming",
            "date": "2026-05-13",
            "distance_km": 0.3,
            "splits": [
                {
                    "split_index": 1,
                    "distance": 0.1,
                    "duration": 2.0,
                    "elapsed_duration": 2.0166666667,
                    "moving_duration": 1.9833333333,
                    "pace": "2:00 /100m",
                },
                {
                    "split_index": 2,
                    "interval_type": "rest",
                    "distance": 0,
                    "duration": 0.5,
                    "elapsed_duration": 0.5083333333,
                    "moving_duration": 0,
                },
                {
                    "split_index": 3,
                    "distance": 0,
                    "duration": 0.25,
                    "elapsed_duration": 0.25,
                    "moving_duration": 0,
                },
                {
                    "split_index": 4,
                    "distance": 0.2,
                    "duration": 4.4,
                    "elapsed_duration": 4.4,
                    "moving_duration": 4.4,
                    "pace": "2:12 /100m",
                },
            ],
        }
    ]
    raw_activities = [
        {
            "activity_id": 211,
            "type": "swimming",
            "duration": 7.15,
            "elapsed_duration": 7.4,
            "moving_duration": 6.3833333333,
            "rest_duration": 0.75,
        }
    ]

    context = _build_context_fixture(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=raw_activities,
        today="2026-05-14",
    )
    session = context["weekly_analysis"][0]["sessions"][0]

    assert session["elapsed_duration_min"] == 7.4
    assert session["swim_duration_min"] == 6.3833
    assert session["rest_duration_min"] == 0.75
    assert session["swim_pace_seconds_per_100m"] == 128
    assert session["elapsed_pace_seconds_per_100m"] == 148
    assert [segment["split_index"] for segment in session["segments"]] == [1, 2, 3, 4]
    assert [segment["segment_type"] for segment in session["segments"]] == ["lap", "rest", "lap", "lap"]
    assert session["segments"][1]["elapsed_duration_min"] == 0.5083

    report = enforce_deterministic_report_fields(
        {
            "weekly_analysis": [
                {
                    "week_start": "2026-05-11",
                    "sessions": [
                        {
                            "activity_id": 211,
                            "swim_pace_seconds_per_100m": 1,
                            "elapsed_pace_seconds_per_100m": 1,
                        }
                    ],
                }
            ]
        },
        context,
    )
    enforced = report["weekly_analysis"][0]["sessions"][0]
    assert enforced["elapsed_duration_min"] == 7.4
    assert enforced["swim_duration_min"] == 6.3833
    assert enforced["rest_duration_min"] == 0.75
    assert enforced["swim_pace_seconds_per_100m"] == 128
    assert enforced["elapsed_pace_seconds_per_100m"] == 148
    assert enforced["segments"][1]["elapsed_duration_min"] == 0.5083


def test_swimming_context_sums_only_explicit_rest_segments_before_rounding():
    processed_data = [
        {
            "activity_id": 212,
            "type": "swimming",
            "date": "2026-05-13",
            "distance_km": 0.1,
            "splits": [
                {
                    "split_index": 1,
                    "interval_type": "rest",
                    "distance": 0,
                    "duration": 0.5,
                    "elapsed_duration": 0.5083333333,
                },
                {
                    "split_index": 2,
                    "interval_type": "rest",
                    "distance": 0,
                    "duration": 0.2525,
                    "elapsed_duration": None,
                },
                {
                    "split_index": 3,
                    "distance": 0,
                    "duration": 5.0,
                    "elapsed_duration": 5.0,
                },
            ],
        }
    ]

    context = _build_context_fixture(
        processed_data=processed_data,
        user_data=_sample_user_data(),
        raw_activities=[{"activity_id": 212, "type": "swimming", "duration": 5.7525}],
        today="2026-05-14",
    )
    session = context["weekly_analysis"][0]["sessions"][0]

    assert session["rest_duration_min"] == 0.7608
    assert "elapsed_duration_min" not in session
    assert "swim_duration_min" not in session
    assert "swim_pace_seconds_per_100m" not in session
    assert "elapsed_pace_seconds_per_100m" not in session


def test_swimming_context_keeps_reliable_swim_pace_without_rest_breakdown():
    context = _build_context_fixture(
        processed_data=[
            {
                "activity_id": 215,
                "type": "swimming",
                "date": "2026-05-13",
                "distance_km": 0.2,
                "splits": [],
            }
        ],
        user_data=_sample_user_data(),
        raw_activities=[
            {
                "activity_id": 215,
                "type": "swimming",
                "duration": 5.25,
                "elapsed_duration": 5.5,
                "moving_duration": 4.75,
            }
        ],
        today="2026-05-14",
    )
    session = context["weekly_analysis"][0]["sessions"][0]

    assert session["swim_pace_seconds_per_100m"] == 142
    assert session["elapsed_pace_seconds_per_100m"] == 165
    assert "rest_duration_min" not in session


def test_context_uses_split_duration_without_inventing_legacy_session_pace():
    activity_window = normalize_activity_window(
        [
            {
                "activity_id": 216,
                "type": "running",
                "date": "2026-05-13",
                "distance": 2,
                "splits": [
                    {"split_index": 1, "distance": 1, "duration": 5, "pace": 5},
                    {"split_index": 2, "distance": 1, "duration": 5, "pace": 5},
                ],
                "raw_data": {"training_stress_score": 20},
            }
        ]
    )

    context = build_deterministic_coach_context(
        activity_window=activity_window,
        user_data=_sample_user_data(),
        today="2026-05-14",
    )
    session = context["weekly_analysis"][0]["sessions"][0]

    assert session["duration_min"] == 10
    assert session["avg_pace"] is None


def test_swimming_session_does_not_expose_raw_training_effect():
    activity_window = normalize_activity_window(
        [
            {
                "activity_id": 217,
                "type": "swimming",
                "date": "2026-05-13",
                "distance": 1,
                "duration": 20,
                "raw_data": {
                    "training_stress_score": 30,
                    "aerobic_training_effect": 3.2,
                    "anaerobic_training_effect": 1.4,
                    "avg_swolf": 42,
                    "avg_stroke_cadence": 24,
                },
            }
        ]
    )

    context = build_deterministic_coach_context(
        activity_window=activity_window,
        user_data=_sample_user_data(),
        today="2026-05-14",
    )
    session = context["weekly_analysis"][0]["sessions"][0]

    assert session["training_effect_aerobic"] is None
    assert session["training_effect_anaerobic"] is None
    assert context["cross_training"]["swimming"]["avg_swolf"] == 42
    assert context["cross_training"]["swimming"]["avg_stroke_rate"] is None


def test_lap_swimming_session_preserves_legacy_pace_and_zone_behavior():
    activity_window = normalize_activity_window(
        [
            {
                "activity_id": 218,
                "type": "lap_swimming",
                "date": "2026-05-13",
                "distance": 0.2,
                "duration": 4,
                "raw_data": {
                    "training_stress_score": 15,
                    "hr_zone_1": 240,
                    "power_zone_2": 120,
                    "avg_swolf": 44,
                    "avg_stroke_cadence": 22,
                },
            }
        ]
    )

    context = build_deterministic_coach_context(
        activity_window=activity_window,
        user_data=_sample_user_data(),
        today="2026-05-14",
    )
    session = context["weekly_analysis"][0]["sessions"][0]

    normalized = activity_window.activities[0]
    assert normalized.performance_formatted == "2:00 /100m"
    assert normalized.processed_performance_value is None
    assert normalized.processed_performance_formatted == "N/A"
    assert normalized.processed_activity_type == "lap_swimming"
    assert normalized.processed_has_advanced_metrics is False
    assert normalized.hr_zone_seconds[1] == 240
    assert normalized.power_zone_seconds[2] == 120
    assert normalized.avg_swolf == 44
    assert activity_window.processed_data()[0]["performance_formatted"] == "N/A"
    assert session["source_activity_type"] == "lap_swimming"
    assert session["avg_pace"] is None
    assert context["hr_zone_distribution"]["total_minutes"] == 0
    assert context["power_zone_distribution"]["total_minutes"] == 0
    assert context["cross_training"]["swimming"] == {
        "sessions_count": 1,
        "avg_swolf": None,
        "avg_stroke_rate": None,
    }


def test_invalid_sport_metrics_do_not_leak_into_context_aggregates():
    activity_window = normalize_activity_window(
        [
            {
                "activity_id": 219,
                "type": "running",
                "date": "2026-05-13",
                "distance": 5,
                "duration": 25,
                "splits": [
                    {
                        "split_index": 1,
                        "duration": 25,
                        "avg_cadence": 175,
                        "vertical_oscillation": 99,
                        "ground_contact_time": 99,
                    }
                ],
                "raw_data": {
                    "training_stress_score": 30,
                    "cadence": 175,
                    "vertical_oscillation": 99,
                    "ground_contact_time": 99,
                },
            },
            {
                "activity_id": 220,
                "type": "cycling",
                "date": "2026-05-13",
                "distance": 20,
                "duration": 60,
                "raw_data": {
                    "training_stress_score": 40,
                    "power_avg": 2501,
                    "power_max": 4000,
                },
            },
            {
                "activity_id": 221,
                "type": "swimming",
                "date": "2026-05-13",
                "distance": 1,
                "duration": 20,
                "raw_data": {
                    "training_stress_score": 20,
                    "avg_swolf": 999,
                },
            },
        ]
    )

    running, cycling, swimming = activity_window.activities
    assert running.vertical_oscillation_cm is None
    assert running.ground_contact_time_ms is None
    assert cycling.power_avg_w is None
    assert cycling.power_max_w is None
    assert swimming.avg_swolf is None

    context = build_deterministic_coach_context(
        activity_window=activity_window,
        user_data=_sample_user_data(),
        today="2026-05-14",
    )

    assert context["running_mechanics"]["vertical_oscillation_cm"]["value"] is None
    assert context["running_mechanics"]["ground_contact_ms"]["value"] is None
    assert context["cross_training"]["cycling"]["avg_power_w"] is None
    assert context["cross_training"]["swimming"]["avg_swolf"] is None


def test_alias_only_cadence_and_power_remain_canonical_only():
    activity_window = normalize_activity_window(
        [
            {
                "activity_id": 222,
                "type": "running",
                "date": "2026-05-13",
                "distance": 5,
                "duration": 25,
                "splits": [
                    {
                        "split_index": 1,
                        "distance": 1,
                        "duration": 5,
                        "average_cadence": 182,
                    }
                ],
                "raw_data": {
                    "training_stress_score": 30,
                    "avg_cadence": 180,
                },
            },
            {
                "activity_id": 223,
                "type": "cycling",
                "date": "2026-05-13",
                "distance": 20,
                "duration": 60,
                "raw_data": {
                    "training_stress_score": 40,
                    "avg_cadence": 90,
                    "average_power": 220,
                    "max_power": 400,
                },
            },
        ]
    )

    running, cycling = activity_window.activities
    assert running.avg_cadence_spm == 180
    assert running.segments[0].avg_cadence_spm == 182
    assert cycling.avg_cadence_spm == 90
    assert cycling.power_avg_w == 220
    assert cycling.power_max_w == 400
    assert running.processed_avg_cadence_spm is None
    assert running.segments[0].processed_avg_cadence_spm is None
    assert cycling.processed_avg_cadence_spm is None
    assert cycling.processed_power_avg_w is None
    assert cycling.processed_power_max_w is None

    processed_running, processed_cycling = activity_window.processed_data()
    assert "runner_type" not in processed_running
    assert processed_running["advanced_metrics"]["avg_cadence"] is None
    assert processed_cycling["advanced_metrics"]["avg_cadence"] is None
    assert processed_cycling["advanced_metrics"]["power_avg"] is None
    assert processed_cycling["advanced_metrics"]["power_max"] is None

    context = build_deterministic_coach_context(
        activity_window=activity_window,
        user_data=_sample_user_data(),
        today="2026-05-14",
    )
    sessions = {
        session["source_activity_type"]: session
        for session in context["weekly_analysis"][0]["sessions"]
    }

    assert sessions["running"]["segments"][0]["cadence"] is None
    assert context["running_mechanics"]["cadence_avg"]["value"] is None
    assert context["cross_training"]["cycling"]["avg_power_w"] is None
    assert context["cross_training"]["cycling"]["avg_cadence"] is None


def test_legacy_swimming_context_does_not_infer_missing_times_from_index_gaps():
    context = _build_context_fixture(
        processed_data=[
            {
                "activity_id": 213,
                "type": "swimming",
                "date": "2026-05-13",
                "distance_km": 0.2,
                "splits": [
                    {"split_index": 1, "distance": 0.1, "duration": 2.0},
                    {"split_index": 4, "distance": 0.1, "duration": 2.1},
                ],
            }
        ],
        user_data=_sample_user_data(),
        raw_activities=[{"activity_id": 213, "type": "swimming", "duration": 10.0}],
        today="2026-05-14",
    )
    session = context["weekly_analysis"][0]["sessions"][0]

    assert "elapsed_duration_min" not in session
    assert "swim_duration_min" not in session
    assert "rest_duration_min" not in session
    assert "swim_pace_seconds_per_100m" not in session
    assert "elapsed_pace_seconds_per_100m" not in session
    assert [segment["segment_type"] for segment in session["segments"]] == ["lap", "lap"]


def test_non_swimming_context_does_not_gain_optional_swim_timing_keys():
    context = _build_context_fixture(
        processed_data=[
            {
                "activity_id": 214,
                "type": "running",
                "date": "2026-05-13",
                "distance_km": 5,
                "splits": [{"split_index": 1, "distance": 1, "duration": 5}],
            }
        ],
        user_data=_sample_user_data(),
        raw_activities=[
            {
                "activity_id": 214,
                "type": "running",
                "duration": 25,
                "elapsed_duration": 26,
                "moving_duration": 24,
                "rest_duration": 2,
            }
        ],
        today="2026-05-14",
    )
    session = context["weekly_analysis"][0]["sessions"][0]

    assert "elapsed_duration_min" not in session
    assert "swim_duration_min" not in session
    assert "rest_duration_min" not in session
    assert "swim_pace_seconds_per_100m" not in session
    assert "elapsed_pace_seconds_per_100m" not in session
    assert "elapsed_duration_min" not in session["segments"][0]


def test_physio_seed_preserves_runner_pace_format_and_open_ended_z5():
    context = _build_context_fixture(
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


def test_physio_seed_does_not_estimate_resting_hr_from_activity_data():
    user_data = _sample_user_data()
    user_data["resting_heart_rate"] = None
    context = _build_context_fixture(
        processed_data=[
            {
                "activity_id": 401,
                "type": "running",
                "date": "2026-05-12",
                "distance_km": 0.62,
                "duration_min": 4,
                "avg_hr": 166,
            },
        ],
        user_data=user_data,
        raw_activities=[],
        today="2026-05-14",
    )

    physio = context["physio_metrics"]
    assert physio["resting_heart_rate"]["value"] is None
    assert physio["resting_heart_rate"]["source"] is None
    assert all(zone["hr_min"] is None and zone["hr_max"] is None for zone in physio["pace_zones"])


def test_next_week_seed_uses_training_preferences_without_ai():
    context = _build_context_fixture(
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
    context = _build_context_fixture(
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
    assert all("type" not in session for session in restored_week["sessions"])
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
