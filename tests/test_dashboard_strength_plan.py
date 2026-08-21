from tests.test_dashboard_adapter import run_adapter_case


def test_planned_strength_keeps_null_distance_and_uses_chinese_labels(tmp_path):
    report = {
        "next_week_plan": {
            "week_start": "2026-05-18",
            "days": [
                {
                    "date": "2026-05-19",
                    "day_of_week": "Tue",
                    "title": "肌力訓練",
                    "session_type": "strength_training",
                    "description": "依既定安排完成肌力訓練。",
                    "distance_km": None,
                    "duration_min": 45,
                    "intensity": "moderate",
                    "key_workout": False,
                },
                {
                    "date": "2026-05-20",
                    "day_of_week": "Wed",
                    "title": "輕鬆跑",
                    "session_type": "easy",
                    "description": "5.25 km 輕鬆跑。",
                    "distance_km": 5.25,
                    "duration_min": 35,
                    "intensity": "easy",
                    "key_workout": False,
                },
            ],
        },
        "periodization": {
            "phases": [
                {
                    "phase_name": "基礎期",
                    "start_date": "2026-05-18",
                    "end_date": "2026-05-24",
                    "weekly_structure": [
                        {
                            "day": "Tue",
                            "session_type": "strength_training",
                            "description": "肌力訓練",
                            "duration_min": 45,
                            "intensity": "moderate",
                        }
                    ],
                }
            ]
        },
    }

    payload = run_adapter_case(tmp_path, report)
    tuesday = next(day for day in payload["calendar"]["days"] if day["day_key"] == "Tue")
    periodization_strength = payload["periodization"]["phases"][0]["weekly_structure"][0]

    assert tuesday["session_type"] == "strength_training"
    assert tuesday["session_type_label"] == "肌力訓練"
    assert tuesday["distance_km"] is None
    assert payload["calendar"]["total_distance_km"] == 5.25
    assert periodization_strength["session_type_label"] == "肌力訓練"
