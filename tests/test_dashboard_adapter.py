import json
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(
    shutil.which("osascript") is None,
    reason="dashboard adapter unit tests require macOS JavaScript runtime",
)


def run_adapter_case(tmp_path, report):
    adapter_source = open("dashboard/reportAdapter.js", encoding="utf-8").read()
    script = (
        adapter_source
        + "\nvar report = "
        + json.dumps(report, ensure_ascii=False)
        + ";\n"
        + "var model = DashboardAdapter.buildDashboardModel(report);\n"
        + "JSON.stringify({"
        + "weekly: model.weekly_analysis.weeks,"
        + "calendar: model.next_week_plan,"
        + "race: model.race_readiness,"
        + "evidence: model.evidence,"
        + "physio: model.physio_metrics,"
        + "summary: model.coaching_summary"
        + "});\n"
    )
    script_path = tmp_path / "adapter_case.js"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run(
        ["osascript", "-l", "JavaScript", str(script_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_weekly_metrics_are_derived_from_sessions_and_mark_partial_data(tmp_path):
    report = {
        "weekly_analysis": [
            {
                "week_start": "2026-05-11",
                "total_distance_km": 999,
                "training_load": 999,
                "sessions": [
                    {"distance_km": 5.125, "duration_min": 30.04, "training_load": 44.44},
                    {"distance_km": 3, "duration_min": None},
                ],
            }
        ],
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)
    metrics = payload["weekly"][0]["metrics"]

    assert metrics["derived_total_distance_km"] == 8.13
    assert metrics["derived_total_duration_min"] == 30.0
    assert metrics["derived_training_load"] == 44.4
    assert metrics["data_quality"] == "部分資料不足"
    assert set(metrics["missing_fields"]) == {"duration_min", "training_load"}


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
    assert payload["evidence"]["fallbackMessage"] == "此報告尚未提供可追溯依據"


def test_pace_strings_are_preserved(tmp_path):
    report = {
        "physio_metrics": {
            "lactate_threshold": {
                "heart_rate": {"value": 191, "unit": "bpm"},
                "pace": {"value": "03:59/km", "unit": ""},
            },
            "pace_zones": [
                {"zone": 2, "name": "有氧", "pace_min": "05:30", "pace_max": "04:50"},
                {"zone": 1, "name": "恢復", "pace_min": "07:00", "pace_max": "06:00"},
                {"zone": 5, "name": "衝刺", "pace_min": "03:45", "pace_max": "00:00"},
            ],
        },
        "next_week_plan": {"week_start": "2026-05-18", "days": []},
    }

    payload = run_adapter_case(tmp_path, report)

    assert payload["physio"]["lactate_threshold"]["pace"]["value"] == "03:59/km"
    assert [zone["zone"] for zone in payload["physio"]["pace_zones"]] == [1, 2, 5]
    assert payload["physio"]["pace_zones"][2]["pace_range"] == "快於 03:45/km"


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
    assert first["supporting_sessions"][0]["source_label"] == "近期訓練 4 > 活動 1"
    assert second["source_section_labels"] == ["目標能力", "課表建議"]
    assert second["visualization_label"] == "圖表註記"
    assert second["supporting_metrics"][0]["source_label"] == "目標能力 > 信心分數"


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
                                "note": "輕鬆熱身",
                            },
                            {
                                "segment_type": "main",
                                "distance_km": 0.4,
                                "avg_pace": "03:38",
                                "avg_hr": 181,
                                "cadence": 188.4,
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

    assert segments == [
        {
            "index": 1,
            "segment_type": "warmup",
            "segment_type_label": "熱身",
            "distance_km": 1.2,
            "avg_pace": "06:10",
            "avg_hr": 145,
            "cadence": 170.2,
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
            "note": "400m",
        },
    ]
