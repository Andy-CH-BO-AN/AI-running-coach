import json
from pathlib import Path
import shutil
import subprocess

import pytest


def _js_runtime():
    if shutil.which("node"):
        return ("node",)
    if shutil.which("osascript"):
        return ("osascript", "-l", "JavaScript")
    pytest.skip("dashboard adapter unit tests require Node.js or macOS osascript JavaScript runtime.")


def run_adapter_expression(tmp_path, setup, expression, case_name="adapter_case.js"):
    adapter_source = Path("dashboard/reportAdapter.js").read_text(encoding="utf-8")
    runtime = _js_runtime()
    if runtime[0] == "node":
        trailer = setup + "\nconsole.log(" + expression + ");\n"
    else:
        trailer = setup + "\n" + expression + ";\n"
    script_path = tmp_path / case_name
    script_path.write_text(adapter_source + "\n" + trailer, encoding="utf-8")

    result = subprocess.run(
        [*runtime, str(script_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def run_adapter_case(tmp_path, report):
    setup = (
        "var report = "
        + json.dumps(report, ensure_ascii=False)
        + ";\nvar model = DashboardAdapter.buildDashboardModel(report);"
    )
    expression = (
        "JSON.stringify({"
        + "weekly: model.weekly_analysis.weeks,"
        + "crossTraining: model.cross_training_highlights,"
        + "calendar: model.next_week_plan,"
        + "race: model.race_readiness,"
        + "evidence: model.evidence,"
        + "physio: model.physio_metrics,"
        + "mechanics: model.running_mechanics,"
        + "latest: model.latest_activity,"
        + "summary: model.coaching_summary,"
        + "trend: model.twelve_week_trend,"
        + "periodization: model.periodization"
        + "})"
    )
    return json.loads(run_adapter_expression(tmp_path, setup, expression))


def test_weekly_metrics_are_derived_from_sessions_and_mark_partial_data(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "total_distance_km": 999,
                "training_load": 999,
                "sessions": [
                    {"type": "easy", "distance_km": 5.125, "duration_min": 30.04, "training_load": 44.44},
                    {"type": "bike", "distance_km": 12, "duration_min": 35, "training_load": 24},
                    {"type": "swim", "distance_km": 1.2, "duration_min": 28, "training_load": 18},
                    {"type": "easy", "distance_km": 3, "duration_min": None},
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    metrics = payload["weekly"][0]["metrics"]

    assert metrics["derived_total_distance_km"] == 8.13
    assert metrics["derived_running_distance_km"] == 8.13
    assert metrics["derived_swim_distance_km"] == 1.2
    assert metrics["derived_bike_distance_km"] == 12
    assert metrics["derived_total_duration_min"] == 93.0
    assert metrics["derived_training_load"] == 86.4
    assert metrics["data_quality"] == "部分資料不足"
    assert set(metrics["missing_fields"]) == {"duration_min", "training_load"}


def test_dashboard_renderer_does_not_write_report_text_via_inner_html():
    source = Path("dashboard/app.js").read_text(encoding="utf-8")

    unsafe_fragments = [
        'p.innerHTML = "<strong>" + block.label + "：</strong>" + block.text;',
        'top.innerHTML = "<h4 class=\'week-title\'>" + week.week_label + "</h4>";',
        'summaryLead.innerHTML = "<p><strong>總結：</strong>" + trend.summaryNote + "</p>";',
        'temp.innerHTML = "<p>🌡️ 高溫校正：" + trend.temperature_note + "</p>";',
        'row.innerHTML = "<td>" + (metric.label || metric.metric || "指標") + "</td><td><b>" + value + "</b></td><td>" + (metric.source_label || "資料來源") + "</td>";',
        'card.innerHTML = "<span class=\'coach-note-label\'>" + block.label + "</span><p>" + block.text + "</p>";',
    ]

    for fragment in unsafe_fragments:
        assert fragment not in source


def test_evidence_metrics_table_hides_source_context_column():
    source = Path("dashboard/app.js").read_text(encoding="utf-8")

    assert '資料脈絡' not in source
    assert 'evidence-metric-grid' in source
    assert 'renderEvidenceMetricCard' in source


def test_dashboard_uses_local_font_stack_only():
    index_source = Path("dashboard/index.html").read_text(encoding="utf-8")
    style_source = Path("dashboard/styles.css").read_text(encoding="utf-8")

    assert "fonts.googleapis.com" not in index_source
    assert "fonts.gstatic.com" not in index_source
    assert "font-family: Inter" not in style_source


def test_12_week_trend_uses_db_weeks_and_hides_single_profile_snapshot(tmp_path):
    report = {
        "twelve_week_summary": [
            {"week_label": "舊資料", "derived_total_distance_km": 99, "derived_training_load": 999}
        ],
        "db_fitness_trend": {
            "weeks": [
                {"week_label": "5/4-5/10", "derived_total_distance_km": 8.5, "derived_training_load": 100},
                {"week_label": "5/11-5/17", "derived_total_distance_km": 11.17, "derived_training_load": 172},
            ],
            "profile_series": {
                "vo2max_running": [{"date": "2026-05-17", "value": 53}],
                "lactate_threshold_pace": [{"date": "2026-05-17", "value": "04:24 /km"}],
            },
        },
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    trend = payload["trend"]

    assert [metric["label"] for metric in trend["metrics"]] == ["12 週跑量", "12 週訓練量"]
    assert trend["metrics"][0]["value"] == "11.17 km"
    assert trend["metrics"][1]["value"] == "172 TSS"
    assert trend["metrics"][0]["points"][1]["label"] == "5/11-5/17"


def test_risk_flags_use_human_readable_labels(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "risk_flags": [
                    "heat_stress",
                    "low_running_volume",
                    "overreaching_risk",
                    "high_intensity_long_run",
                    "fatigue_risk",
                ],
                "sessions": [],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)

    assert payload["weekly"][0]["risk_flags"] == [
        {"code": "heat_stress", "label": "熱壓力"},
        {"code": "low_running_volume", "label": "跑量偏低"},
        {"code": "overreaching_risk", "label": "過度負荷風險"},
        {"code": "high_intensity_long_run", "label": "長跑強度偏高"},
        {"code": "fatigue_risk", "label": "疲勞風險"},
    ]


def test_weekly_intensity_focuses_are_adapted_and_limited_to_two(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "intensity_focuses": [
                    {"dimension": "heart_rate", "headline": "心率先上升", "analysis": "熱天心率反應快。"},
                    {"dimension": "power", "headline": "功率仍穩", "analysis": "輸出沒有一起飄高。"},
                    {"dimension": "load", "headline": "不應保留", "analysis": "第三筆應被截斷。"},
                ],
                "sessions": [],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    focuses = payload["weekly"][0]["intensity_focuses"]

    assert len(focuses) == 2
    assert focuses[0]["label"] == "心率"
    assert focuses[1]["label"] == "功率"
    assert focuses[0]["headline"] == "心率先上升"


def test_weekly_intensity_focuses_fall_back_from_sessions_and_risks(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "risk_flags": ["heat_stress"],
                "sessions": [
                    {
                        "date": "2026-05-12",
                        "type": "interval",
                        "training_load": 42,
                        "avg_hr": 182,
                        "training_effect_anaerobic": 3.8,
                        "training_effect_aerobic": 2.4,
                        "environment": {"estimated_temp_c": 29.4},
                    },
                    {
                        "date": "2026-05-14",
                        "type": "tempo",
                        "training_load": 54,
                        "training_effect_anaerobic": 1.2,
                        "training_effect_aerobic": 3.7,
                    }
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    focuses = payload["weekly"][0]["intensity_focuses"]

    assert len(focuses) == 2
    assert focuses[0]["dimension"] == "heat"
    assert focuses[1]["headline"] == "代表課 1：5/12 間歇"
    assert "無氧 TE 3.8" in focuses[1]["analysis"]


def test_cross_training_highlights_pick_highest_load_session_per_week(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_label": "05/11-05/17",
                "week_start": "2026-05-11",
                "sessions": [
                    {
                        "date": "2026-05-12",
                        "type": "swim",
                        "distance_km": 1.2,
                        "duration_min": 42,
                        "training_load": 38,
                        "training_effect_aerobic": 2.1,
                    },
                    {
                        "date": "2026-05-14",
                        "type": "bike",
                        "distance_km": 18,
                        "duration_min": 54,
                        "training_load": 72,
                        "training_effect_aerobic": 3.2,
                    },
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    highlight = payload["crossTraining"][0]

    assert highlight["session_type"] == "bike"
    assert highlight["title"] == "5/14 自行車"
    assert highlight["load_label"] == "72 TSS"


def test_cross_training_highlights_prefer_ai_analysis_when_present(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_label": "05/11-05/17",
                "week_start": "2026-05-11",
                "cross_training_focus": {
                    "activity_id": 22,
                    "headline": "單車是心肺補量，不是恢復日",
                    "analysis": "這堂單車有明確有氧刺激，隔天跑步應避免再堆高強度。",
                },
                "sessions": [
                    {
                        "activity_id": 22,
                        "date": "2026-05-14",
                        "type": "bike",
                        "distance_km": 18,
                        "duration_min": 54,
                        "training_load": 72,
                    },
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    highlight = payload["crossTraining"][0]

    assert highlight["title"] == "單車是心肺補量，不是恢復日"
    assert highlight["session_label"] == "5/14 自行車"
    assert highlight["analysis"] == "這堂單車有明確有氧刺激，隔天跑步應避免再堆高強度。"
    assert highlight["has_ai_analysis"] is True


def test_cross_training_highlights_match_ai_focus_activity_id_before_load(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_label": "05/11-05/17",
                "week_start": "2026-05-11",
                "cross_training_focus": {
                    "activity_id": 11,
                    "headline": "恢復游泳保留跑步主課品質",
                    "analysis": "這堂游泳負荷較低，但更能代表本週交叉訓練的恢復目的。",
                },
                "sessions": [
                    {
                        "activity_id": 11,
                        "date": "2026-05-12",
                        "type": "swim",
                        "distance_km": 1.2,
                        "duration_min": 42,
                        "training_load": 38,
                    },
                    {
                        "activity_id": 22,
                        "date": "2026-05-14",
                        "type": "bike",
                        "distance_km": 18,
                        "duration_min": 54,
                        "training_load": 72,
                    },
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    highlight = payload["crossTraining"][0]

    assert highlight["session_type"] == "swim"
    assert highlight["title"] == "恢復游泳保留跑步主課品質"
    assert highlight["session_label"] == "5/12 游泳"
    assert highlight["load_label"] == "38 TSS"
    assert highlight["analysis"] == "這堂游泳負荷較低，但更能代表本週交叉訓練的恢復目的。"


def test_cross_training_highlights_ignore_ai_text_when_focus_activity_id_misses(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_label": "05/11-05/17",
                "week_start": "2026-05-11",
                "cross_training_focus": {
                    "activity_id": 99,
                    "headline": "不存在的恢復游泳",
                    "analysis": "這段文字不應套到其他交叉訓練卡。",
                },
                "sessions": [
                    {
                        "activity_id": 22,
                        "date": "2026-05-14",
                        "type": "bike",
                        "distance_km": 18,
                        "duration_min": 54,
                        "training_load": 72,
                        "training_effect_aerobic": 3.2,
                    },
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    highlight = payload["crossTraining"][0]

    assert highlight["session_type"] == "bike"
    assert highlight["title"] == "5/14 自行車"
    assert highlight["session_label"] == "5/14 自行車"
    assert highlight["load_label"] == "72 TSS"
    assert highlight["analysis"] != "這段文字不應套到其他交叉訓練卡。"
    assert highlight["has_ai_analysis"] is False


def test_work_reps_include_all_interval_segments(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "sessions": [
                    {
                        "date": "2026-05-12",
                        "type": "interval",
                        "segments": [
                            {
                                "segment_type": "warmup",
                                "distance_km": 1.5,
                                "avg_pace": "06:00",
                            },
                            {
                                "segment_type": "main",
                                "distance_km": 0.4,
                                "avg_pace": "04:00",
                            },
                            {
                                "segment_type": "recovery",
                                "distance_km": 0.2,
                                "avg_pace": "08:00",
                            },
                        ],
                    }
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    setup = (
        "var model = DashboardAdapter.buildDashboardModel("
        + json.dumps(report, ensure_ascii=False)
        + ");"
    )
    reps = json.loads(
        run_adapter_expression(tmp_path, setup, "JSON.stringify(model.latest_activity.work_reps)", "work_reps_case.js")
    )
    assert [rep["segment_type"] for rep in reps] == ["warmup", "main", "recovery"]
    assert [rep["avg_pace"] for rep in reps] == ["06:00", "04:00", "08:00"]


def test_work_reps_ignore_null_interval_segments(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "sessions": [
                    {
                        "date": "2026-05-12",
                        "type": "interval",
                        "segments": [
                            None,
                            {
                                "segment_type": "main",
                                "distance_km": 0.4,
                                "avg_pace": "04:00",
                            },
                            None,
                            {
                                "segment_type": "recovery",
                                "distance_km": 0.2,
                                "avg_pace": "08:00",
                            },
                        ],
                    }
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    setup = (
        "var model = DashboardAdapter.buildDashboardModel("
        + json.dumps(report, ensure_ascii=False)
        + ");"
    )
    reps = json.loads(
        run_adapter_expression(tmp_path, setup, "JSON.stringify(model.latest_activity.work_reps)", "null_work_reps_case.js")
    )

    assert [rep["segment_type"] for rep in reps] == ["main", "recovery"]
    assert [rep["index"] for rep in reps] == [1, 2]
    assert [rep["avg_pace"] for rep in reps] == ["04:00", "08:00"]


def test_calendar_extracts_pace_interval_and_rest_from_description(tmp_path):
    report = {
        "next_week_plan": {
            "week_start": "2026-05-18",
            "theme": "速度週",
            "days": [
                {
                    "date": "2026-05-21",
                    "day_of_week": "Thu",
                    "title": "400m 間歇",
                    "session_type": "interval",
                    "description": "400m×6，84-88s/rep，休息90s，配速 3:40-3:45/km",
                    "distance_km": 6,
                    "duration_min": 50,
                    "intensity": "hard",
                    "key_workout": True,
                }
            ],
        }
    }

    payload = run_adapter_case(tmp_path, report)
    thursday = next(day for day in payload["calendar"]["days"] if day["day_key"] == "Thu")

    assert thursday["interval_label"] == "400m × 6"
    assert thursday["rest_label"] == "90s"
    assert "3:40" in thursday["pace_label"]


def test_calendar_extracts_interval_label_from_multiplier_first_description(tmp_path):
    report = {
        "next_week_plan": {
            "week_start": "2026-05-18",
            "days": [
                {
                    "date": "2026-05-22",
                    "day_of_week": "Fri",
                    "title": "速度課",
                    "session_type": "interval",
                    "description": "6x400m，休息90s，配速 3:45/km",
                    "distance_km": 5,
                    "duration_min": 40,
                    "intensity": "hard",
                    "key_workout": True,
                }
            ],
        }
    }

    payload = run_adapter_case(tmp_path, report)
    friday = next(day for day in payload["calendar"]["days"] if day["day_key"] == "Fri")

    assert friday["interval_label"] == "400m × 6"


def test_calendar_extracts_rep_seconds_and_rest_type(tmp_path):
    report = {
        "next_week_plan": {
            "week_start": "2026-05-18",
            "days": [
                {
                    "date": "2026-05-20",
                    "day_of_week": "Wed",
                    "title": "1500m 專項速度",
                    "session_type": "interval",
                    "description": "400m x 8，配速 84-88s，站休 90秒。",
                    "distance_km": 6,
                    "duration_min": 45,
                    "intensity": "hard",
                    "key_workout": True,
                },
                {
                    "date": "2026-05-23",
                    "day_of_week": "Sat",
                    "title": "長跑",
                    "session_type": "long",
                    "description": "穩定跑 10km，配速 5:30-5:45/km。",
                    "distance_km": 10,
                    "duration_min": 60,
                    "intensity": "moderate",
                    "key_workout": True,
                },
            ],
        }
    }

    payload = run_adapter_case(tmp_path, report)
    wednesday = next(day for day in payload["calendar"]["days"] if day["day_key"] == "Wed")
    saturday = next(day for day in payload["calendar"]["days"] if day["day_key"] == "Sat")

    assert wednesday["pace_label"] == "84–88s/rep"
    assert wednesday["rest_label"] == "站休 90s"
    assert saturday["distance_km"] == 10
    assert saturday["pace_label"] == "5:30–5:45/km"


def test_calendar_prefers_structured_rest_type_and_seconds(tmp_path):
    report = {
        "next_week_plan": {
            "week_start": "2026-05-18",
            "days": [
                {
                    "date": "2026-05-20",
                    "day_of_week": "Wed",
                    "title": "間歇",
                    "session_type": "interval",
                    "description": "400m×6",
                    "distance_km": 6,
                    "duration_min": 45,
                    "target_pace": "3:40/km",
                    "interval_distance": "400m × 6",
                    "rest_seconds": 90,
                    "rest_type": "jog",
                    "intensity": "hard",
                    "key_workout": True,
                }
            ],
        }
    }

    payload = run_adapter_case(tmp_path, report)
    wednesday = next(day for day in payload["calendar"]["days"] if day["day_key"] == "Wed")

    assert wednesday["pace_label"] == "3:40/km"
    assert wednesday["interval_label"] == "400m × 6"
    assert wednesday["rest_label"] == "跑休 90s"


def test_calendar_does_not_treat_rep_seconds_as_rest(tmp_path):
    report = {
        "next_week_plan": {
            "week_start": "2026-05-18",
            "days": [
                {
                    "date": "2026-05-20",
                    "day_of_week": "Wed",
                    "title": "間歇",
                    "session_type": "interval",
                    "description": "400m×8，84-88s/rep",
                    "distance_km": 6,
                    "duration_min": 45,
                    "intensity": "hard",
                    "key_workout": True,
                }
            ],
        }
    }

    payload = run_adapter_case(tmp_path, report)
    wednesday = next(day for day in payload["calendar"]["days"] if day["day_key"] == "Wed")

    assert wednesday["pace_label"] == "84–88s/rep"
    assert wednesday["rest_label"] == ""


def test_power_zones_are_adapted_when_present(tmp_path):
    report = {
        "power_zone_distribution": {
            "period_weeks": 4,
            "zones": [
                {"zone": 1, "name": "Z1", "minutes": 10, "percentage": 10},
                {"zone": 2, "name": "Z2", "minutes": 20, "percentage": 20},
                {"zone": 3, "name": "Z3", "minutes": 30, "percentage": 30},
                {"zone": 4, "name": "Z4", "minutes": 25, "percentage": 25},
                {"zone": 5, "name": "Z5", "minutes": 15, "percentage": 15},
            ],
        },
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    setup = (
        "var model = DashboardAdapter.buildDashboardModel("
        + json.dumps(report, ensure_ascii=False)
        + ");"
    )
    power = json.loads(run_adapter_expression(tmp_path, setup, "JSON.stringify(model.power_zones)", "power_case.js"))
    assert power["has_data"] is True
    assert power["zones"][0]["percentage"] == 10


def test_calendar_fills_missing_days_and_normalizes_day_names(tmp_path):
    report = {
        "next_week_plan": {
            "week_start": "2026-05-18",
            "theme": "恢復週",
            "days": [
                {
                    "date": "2026-05-18",
                    "day_of_week": "MONDAY",
                    "title": "輕鬆跑",
                    "session_type": "easy",
                    "distance_km": 5,
                    "duration_min": 32,
                    "intensity": "easy",
                    "key_workout": False,
                },
                {
                    "date": "2026-05-20",
                    "day_of_week": "WEDNESDAY",
                    "title": "間歇",
                    "session_type": "interval",
                    "distance_km": 6.5,
                    "duration_min": 45,
                    "intensity": "hard",
                    "key_workout": True,
                },
            ],
        }
    }

    payload = run_adapter_case(tmp_path, report)
    calendar = payload["calendar"]

    assert len(calendar["days"]) == 7
    assert calendar["days"][0]["day_key"] == "Mon"
    assert calendar["days"][0]["day_label"] == "週一"
    assert calendar["days"][1]["title"] == "恢復日"
    assert calendar["days"][1]["intensity"] == "rest"
    assert calendar["days"][2]["key_workout"] is True
    assert calendar["total_distance_km"] == 11.5


def test_calendar_derives_weekday_from_date_and_normalizes_week_start(tmp_path):
    report = {
        "next_week_plan": {
            "week_start": "2026-05-19",
            "days": [
                {
                    "date": "2026-05-19",
                    "day_of_week": "MONDAY",
                    "title": "間歇",
                    "session_type": "interval",
                    "distance_km": 4,
                    "duration_min": 40,
                    "intensity": "hard",
                    "key_workout": True,
                }
            ],
        }
    }

    payload = run_adapter_case(tmp_path, report)
    calendar = payload["calendar"]

    assert calendar["week_start"] == "2026-05-18"
    assert calendar["days"][0]["date"] == "2026-05-18"
    assert calendar["days"][0]["day_key"] == "Mon"
    assert calendar["days"][1]["date"] == "2026-05-19"
    assert calendar["days"][1]["day_key"] == "Tue"
    assert calendar["days"][1]["day_label"] == "週二"


def test_periodization_marks_current_phase_from_next_week_plan_start(tmp_path):
    report = {
        "periodization": {
            "weeks_to_race": 16,
            "phases": [
                {
                    "phase_name": "基礎建構期",
                    "start_date": "2026-05-25",
                    "end_date": "2026-07-05",
                    "weeks": 6,
                    "focus": "建立有氧耐力底蘊。",
                    "weekly_structure": [
                        {
                            "day": "Mon",
                            "session_type": "interval",
                            "description": "400m x 8",
                            "duration_min": 45,
                            "intensity": "hard",
                        },
                        {
                            "day": "Tue",
                            "session_type": "swim",
                            "description": "游泳閾值訓練",
                            "duration_min": 60,
                            "intensity": "moderate",
                        },
                    ],
                },
                {
                    "phase_name": "減量期",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-13",
                    "weeks": 2,
                },
            ],
        },
        "next_week_plan": {"week_start": "2026-05-25", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    periodization = payload["periodization"]

    assert periodization["has_data"] is True
    assert periodization["weeks_to_race_label"] == "距離目標賽 16 週"
    assert periodization["reference_date"] == "2026-05-25"
    assert periodization["current_phase"]["phase_name"] == "基礎建構期"
    assert periodization["phases"][0]["is_current"] is True
    assert periodization["phases"][1]["is_current"] is False
    assert periodization["phases"][0]["date_range_label"] == "5/25-7/5"
    assert periodization["phases"][0]["weekly_structure"][0]["day_label"] == "週一"
    assert periodization["phases"][0]["weekly_structure"][0]["session_type_label"] == "間歇"
    assert periodization["phases"][0]["weekly_structure"][0]["intensity_label"] == "高強度"


def test_periodization_handles_missing_data_without_crashing(tmp_path):
    report = {
        "meta": {"today": "2026-05-23"},
        "periodization": {
            "phases": [
                {
                    "phase_name": "日期未定期",
                    "weeks": 3,
                    "focus": "維持規律訓練。",
                }
            ]
        },
        "next_week_plan": {"week_start": "2026-05-25", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    periodization = payload["periodization"]

    assert periodization["has_data"] is True
    assert periodization["weeks_to_race"] is None
    assert periodization["current_phase"] is None
    assert periodization["phases"][0]["date_range_label"] == "日期未設定"
    assert periodization["phases"][0]["weeks_label"] == "3 週"


def test_periodization_empty_state_is_explicit(tmp_path):
    payload = run_adapter_case(tmp_path, {"next_week_plan": {"week_start": "2026-05-25", "days": []}})

    assert payload["periodization"]["has_data"] is False
    assert payload["periodization"]["phases"] == []
    assert payload["periodization"]["current_phase"] is None


def test_evidence_fallback_and_priority_sorting(tmp_path):
    report = {
        "race_readiness": {
            "missing_capabilities": [
                {"capability": "低風險項", "priority": "low"},
                {"capability": "高風險項", "priority": "high"},
                {"capability": "中風險項", "priority": "medium"},
            ]
        },
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)

    assert [item["priority"] for item in payload["race"]["missing_capabilities"]] == [
        "high",
        "medium",
        "low",
    ]
    assert payload["evidence"]["hasEvidence"] is False
    assert payload["evidence"]["fallbackMessage"] == "此報告尚未提供教練判斷理由"


def test_pace_strings_are_preserved(tmp_path):
    report = {
        "physio_metrics": {
            "lactate_threshold": {
                "heart_rate": {"value": 191, "unit": "bpm"},
                "pace": {"value": "03:59/km", "unit": ""},
            },
            "resting_heart_rate": {"value": 50, "unit": "bpm", "source": "garmin"},
            "pace_zones": [
                {"zone": 2, "name": "有氧", "pace_min": "05:30", "pace_max": "04:50"},
                {"zone": 1, "name": "恢復", "pace_min": "07:00", "pace_max": "06:00"},
                {"zone": 5, "name": "衝刺", "pace_min": "03:45", "pace_max": "00:00"},
                {"zone": 6, "name": "開口速度", "pace_min": "03:30", "pace_max": None},
            ],
        },
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)

    assert payload["physio"]["lactate_threshold"]["pace"]["value"] == "03:59/km"
    assert payload["physio"]["lactate_threshold"]["pace"]["assessment"] == ""
    assert [zone["zone"] for zone in payload["physio"]["pace_zones"]] == [1, 2, 5, 6]
    assert payload["physio"]["pace_zones"][2]["pace_range"] == "快於 03:45/km"
    assert payload["physio"]["pace_zones"][3]["pace_range"] == "快於 03:30/km"
    assert payload["physio"]["resting_heart_rate"]["value"] == 50


def test_running_mechanics_only_surface_cadence_assessment_in_metric_cards(tmp_path):
    report = {
        "running_mechanics": {
            "cadence_avg": {"value": 174.2, "unit": "spm", "assessment": "有效跑步段步頻落在合理範圍，休息段已排除。"},
            "ground_contact_ms": {"value": 249, "unit": "ms", "assessment": "觸地時間良好，顯示支撐期控制穩定。"},
            "vertical_oscillation_cm": {"value": 8.4, "unit": "cm", "assessment": "垂直振幅良好，跑動能量沒有明顯向上浪費。"},
            "stride_length_m": {"value": 1.0, "unit": "m", "assessment": "有效跑步段步幅合理，可隨速度課逐步提升推進效率。"},
            "running_economy_score": 95,
            "improvement_tips": ["維持目前有效跑步段步頻與步幅。"],
        },
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    metrics = payload["mechanics"]["metrics"]

    assert [metric["assessment"] for metric in metrics] == [
        "有效跑步段步頻落在合理範圍，休息段已排除。",
        "",
        "",
        "",
    ]


def test_evidence_humanizes_deterministic_context_running_mechanics_paths(tmp_path):
    report = {
        "evidence_links": [
            {
                "insight_id": "stride_context",
                "claim": "步幅解讀需結合速度課情境。",
                "source_sections": ["deterministic_context", "running_mechanics"],
                "supporting_metrics": [
                    {
                        "label": "平均步幅",
                        "value": 1.0,
                        "unit": "m",
                        "source_path": "deterministic_context.running_mechanics.stride_length_m",
                    }
                ],
                "supporting_sessions": [],
                "confidence": 82,
                "visualization_hint": "metric_card",
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    metric = payload["evidence"]["items"][0]["supporting_metrics"][0]

    assert payload["evidence"]["items"][0]["source_section_labels"] == ["訓練資料", "跑姿指標"]
    assert metric["source_label"] == "訓練資料 > 跑姿指標 > 平均步幅"


def test_coaching_summary_links_to_semantically_related_evidence(tmp_path):
    report = {
        "coaching_summary": {
            "headline": "摘要",
            "top_3_insights": ["近期訓練強度偏高，心率常處於高區間，可能導致疲勞累積。"],
            "top_3_actions": ["增加VO2max區間的間歇跑訓練，提升1500m目標配速下的速度耐力。"],
        },
        "evidence_links": [
            {
                "insight_id": "fatigue_warning",
                "claim": "近期訓練強度高，尤其在長距離跑步中，心率常處於高區間，可能導致疲勞累積。",
                "source_sections": ["weekly_analysis", "hr_zone_distribution"],
                "supporting_metrics": [{"label": "Zone 4 心率時間佔比", "value": 11.4}],
                "supporting_sessions": [{"date": "2026-04-26", "type": "long", "source_path": "weekly_analysis[3].sessions[0]"}],
                "confidence": 90,
                "visualization_hint": "metric_card",
            },
            {
                "insight_id": "race_readiness_gap",
                "claim": "需要加強1500m目標配速維持能力，並優化高強度恢復效率。",
                "source_sections": ["race_readiness", "next_week_plan"],
                "supporting_metrics": [{"label": "1500m目標配速", "value": "03:40"}],
                "supporting_sessions": [],
                "confidence": 85,
                "visualization_hint": "chart_annotation",
            },
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)

    assert payload["summary"]["top_3_insights"][0]["evidence_id"] == "fatigue_warning"
    assert payload["summary"]["top_3_actions"][0]["evidence_id"] == "race_readiness_gap"


def test_evidence_uses_human_readable_labels_for_ui_pills_and_sources(tmp_path):
    report = {
        "evidence_links": [
            {
                "insight_id": "fatigue_warning",
                "claim": "近期疲勞偏高。",
                "source_sections": ["athlete_status", "weekly_analysis", "hr_zone_distribution"],
                "supporting_metrics": [
                    {
                        "label": "疲勞分數",
                        "value": 60,
                        "source_path": "athlete_status.fatigue_level.score",
                    },
                    {
                        "label": "Zone 3 心率時間佔比",
                        "value": 22.1,
                        "unit": "%",
                        "source_path": "hr_zone_distribution.zones[2].percentage",
                    },
                ],
                "supporting_sessions": [
                    {
                        "date": "2026-04-26",
                        "type": "long",
                        "source_path": "weekly_analysis[3].sessions[0]",
                    }
                ],
                "confidence": 90,
                "visualization_hint": "metric_card",
            },
            {
                "insight_id": "race_readiness_gap",
                "claim": "需要加強目標配速維持能力。",
                "source_sections": ["race_readiness", "next_week_plan"],
                "supporting_metrics": [
                    {
                        "label": "賽事信心分數",
                        "value": 70,
                        "source_path": "race_readiness.confidence_score",
                    }
                ],
                "supporting_sessions": [],
                "confidence": 85,
                "visualization_hint": "chart_annotation",
            },
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    first, second = payload["evidence"]["items"]

    assert first["source_section_labels"] == ["目前狀態", "近期訓練", "強度分佈"]
    assert first["visualization_label"] == "指標卡"
    assert first["supporting_metrics"][0]["source_label"] == "目前狀態 > 疲勞程度 > 分數"
    assert first["supporting_metrics"][1]["source_label"] == "強度分佈 > 心率區間 3 > 比例"
    assert first["supporting_sessions"][0]["source_label"] == "第 4 週第 1 堂訓練"
    assert second["source_section_labels"] == ["目標能力", "課表建議"]
    assert second["visualization_label"] == "圖表註記"
    assert second["supporting_metrics"][0]["source_label"] == "目標能力 > 信心分數"


def test_evidence_sources_use_runner_language_for_session_fields(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "sessions": [
                    {
                        "date": "2026-05-12",
                        "type": "easy",
                        "distance_km": 2.05,
                        "environment": {"estimated_temp_c": 27.9},
                    }
                ],
            }
        ],
        "evidence_links": [
            {
                "insight_id": "low_volume",
                "claim": "跑步訓練量不足。",
                "supporting_metrics": [
                    {
                        "label": "本週跑量",
                        "value": 2.05,
                        "unit": "km",
                        "source_path": "weekly_analysis[0].sessions[0].distance_km",
                    },
                    {
                        "label": "環境溫度",
                        "value": 27.9,
                        "unit": "°C",
                        "source_path": "weekly_analysis[0].sessions[0].environment.estimated_temp_c",
                    },
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    metrics = payload["evidence"]["items"][0]["supporting_metrics"]

    assert metrics[0]["source_label"] == "5/12 輕鬆跑 > 距離"
    assert metrics[1]["source_label"] == "5/12 輕鬆跑 > 環境 > 氣溫"


def test_evidence_supporting_sessions_include_localized_header_fields(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "sessions": [
                    {
                        "date": "2026-05-12",
                        "type": "easy",
                        "distance_km": 2.05,
                    }
                ],
            }
        ],
        "evidence_links": [
            {
                "insight_id": "low_volume",
                "claim": "跑步訓練量不足。",
                "supporting_sessions": [
                    {
                        "date": "2026-05-12",
                        "type": "easy",
                        "distance_km": 2.05,
                        "source_path": "weekly_analysis[0].sessions[0]",
                    }
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    session = payload["evidence"]["items"][0]["supporting_sessions"][0]

    assert session["date_label"] == "5/12"
    assert session["type_label"] == "輕鬆跑"
    assert session["distance_label"] == "2.05 km"


def test_evidence_metric_display_value_does_not_duplicate_units(tmp_path):
    report = {
        "evidence_links": [
            {
                "insight_id": "heat_impact",
                "claim": "高溫環境導致心率偏高。",
                "source_sections": ["weekly_analysis"],
                "supporting_metrics": [
                    {"label": "高溫環境心率影響", "value": "約 5bpm", "unit": "bpm"},
                    {"label": "Z4 佔比", "value": 11.4, "unit": "%"},
                    {"label": "平均心率", "value": 180, "unit": "bpm"},
                ],
                "supporting_sessions": [],
                "confidence": 90,
                "visualization_hint": "metric_card",
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    metrics = payload["evidence"]["items"][0]["supporting_metrics"]

    assert [metric["display_value"] for metric in metrics] == ["約 5bpm", "11.4%", "180 bpm"]


def test_evidence_sessions_are_enriched_with_source_segments(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "sessions": [
                    {
                        "date": "2026-05-12",
                        "type": "interval",
                        "segments": [
                            {
                                "segment_type": "warmup",
                                "distance_km": 1.2,
                                "avg_pace": "06:10",
                                "avg_hr": 145,
                                "cadence": 170.2,
                                "stride_length_m": 1.08,
                                "note": "輕鬆熱身",
                            },
                            {
                                "segment_type": "main",
                                "distance_km": 0.4,
                                "avg_pace": "03:38",
                                "avg_hr": 181,
                                "cadence": 188.4,
                                "stride_length_m": 1.22,
                                "note": "400m",
                            },
                        ],
                    }
                ],
            }
        ],
        "evidence_links": [
            {
                "insight_id": "race_readiness_gap",
                "claim": "需要更多持續性的高強度訓練。",
                "source_sections": ["weekly_analysis"],
                "supporting_metrics": [],
                "supporting_sessions": [
                    {
                        "date": "2026-05-12",
                        "type": "interval",
                        "source_path": "weekly_analysis[0].sessions[0]",
                    }
                ],
                "confidence": 85,
                "visualization_hint": "session_list",
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    segments = payload["evidence"]["items"][0]["supporting_sessions"][0]["segments"]

    assert len(segments) == 2
    assert segments == [
        {
            "index": 1,
            "segment_type": "warmup",
            "segment_type_label": "熱身",
            "distance_km": 1.2,
            "avg_pace": "06:10",
            "avg_hr": 145,
            "cadence": 170.2,
            "stride_length_m": 1.08,
            "note": "輕鬆熱身",
        },
        {
            "index": 2,
            "segment_type": "main",
            "segment_type_label": "主課表",
            "distance_km": 0.4,
            "avg_pace": "03:38",
            "avg_hr": 181,
            "cadence": 188.4,
            "stride_length_m": 1.22,
            "note": "400m",
        },
    ]


def test_latest_activity_uses_most_recent_session_day(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "sessions": [
                    {
                        "date": "2026-05-15",
                        "type": "interval",
                        "distance_km": 6,
                        "duration_min": 40,
                        "avg_pace": "04:10",
                        "avg_hr": 170,
                    },
                    {
                        "date": "2026-05-16",
                        "type": "easy",
                        "distance_km": 4,
                        "duration_min": 32,
                        "avg_pace": "08:00",
                        "avg_hr": 132,
                    },
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)

    assert payload["latest"]["date_label"] == "5/16"
    assert payload["latest"]["type_label"] == "輕鬆跑"
    assert payload["latest"]["conclusion"] == ""
    assert payload["latest"]["has_ai_conclusion"] is False


def test_latest_activity_prefers_representative_session_within_same_day(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-18",
                "sessions": [
                    {
                        "activity_id": 10,
                        "date": "2026-05-23",
                        "type": "easy",
                        "distance_km": 2.5,
                        "duration_min": 15,
                        "training_load": 42,
                        "avg_pace": "06:00",
                    },
                    {
                        "activity_id": 11,
                        "date": "2026-05-23",
                        "type": "easy",
                        "distance_km": 5.06,
                        "duration_min": 33.4,
                        "training_load": 323.2,
                        "avg_pace": "06:35",
                    },
                    {
                        "activity_id": 12,
                        "date": "2026-05-23",
                        "type": "interval",
                        "distance_km": 0.85,
                        "duration_min": 5.7,
                        "training_load": 15.4,
                        "avg_pace": "06:40",
                    },
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-25", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)

    assert payload["latest"]["date_label"] == "5/23"
    assert payload["latest"]["distance_km"] == 5.06
    assert payload["latest"]["training_load"] == 323.2


def test_latest_activity_uses_real_coaching_note_as_conclusion(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "sessions": [
                    {
                        "date": "2026-05-15",
                        "type": "interval",
                        "coaching_note": "最後一趟仍能加速，速度儲備良好。",
                    }
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)

    assert payload["latest"]["conclusion"] == "最後一趟仍能加速，速度儲備良好。"
    assert payload["latest"]["has_ai_conclusion"] is True


def test_latest_interval_activity_keeps_all_lap_only_splits(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-18",
                "sessions": [
                    {
                        "date": "2026-05-18",
                        "type": "interval",
                        "segments": [
                            {"segment_type": "lap", "distance_km": 0.067, "avg_pace": "3:10", "avg_hr": 156, "cadence": 172.3, "stride_length_m": 1.73},
                            {"segment_type": "lap", "distance_km": 0.099, "avg_pace": "5:10", "avg_hr": 172, "cadence": 183.8, "stride_length_m": 1.13},
                            {"segment_type": "lap", "distance_km": 0.070, "avg_pace": "3:28", "avg_hr": 174, "cadence": 185.1, "stride_length_m": 1.24},
                            {"segment_type": "lap", "distance_km": 0.087, "avg_pace": "6:17", "avg_hr": 184, "cadence": 177.6, "stride_length_m": 0.95},
                        ],
                    }
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-25", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    reps = payload["latest"]["work_reps"]

    assert [rep["avg_pace"] for rep in reps] == ["3:10", "5:10", "3:28", "6:17"]
    assert [rep["segment_type"] for rep in reps] == ["lap", "lap", "lap", "lap"]
    assert [rep["segment_type_label"] for rep in reps] == ["分段", "分段", "分段", "分段"]


def test_evidence_segments_estimate_stride_when_legacy_report_lacks_stride(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "sessions": [
                    {
                        "date": "2026-05-12",
                        "type": "interval",
                        "segments": [
                            {
                                "segment_type": "main",
                                "distance_km": 0.4,
                                "avg_pace": "04:00",
                                "avg_hr": 181,
                                "cadence": 180,
                            }
                        ],
                    }
                ],
            }
        ],
        "evidence_links": [
            {
                "insight_id": "stride_context",
                "claim": "步幅需搭配速度段判斷。",
                "source_sections": ["weekly_analysis"],
                "supporting_sessions": [{"source_path": "weekly_analysis[0].sessions[0]"}],
                "confidence": 85,
                "visualization_hint": "session_list",
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    segment = payload["evidence"]["items"][0]["supporting_sessions"][0]["segments"][0]

    assert segment["stride_length_m"] == 1.39
