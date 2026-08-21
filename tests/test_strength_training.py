from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.ingestion.garmin_client import (
    GarminIngestionError,
    get_all_strength_training_activities,
    get_garmin_activities,
)
from src.ingestion.strength_training import parse_strength_training
from src.notifications.formatter import format_activity_message, format_weekly_report_messages
from src.preprocessing.activity_window import normalize_activity_window
from src.preprocessing.coach_context import (
    build_deterministic_coach_context,
    enforce_deterministic_report_fields,
)
from src.preprocessing.coach_context_session_facts import SessionFacts
from src.services.garmin_import_service import strength_backfill_baseline_ids


def _fixture_payload() -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures" / "garmin_strength_training_deidentified.json").read_text(
            encoding="utf-8"
        )
    )


def test_strength_parser_uses_summary_aliases_preserves_order_and_converts_explicit_units():
    payload = _fixture_payload()
    strength = parse_strength_training(payload["summary"], payload["exercise_sets"])

    assert strength["total_sets"] == 3
    assert strength["active_sets"] == 2
    assert strength["total_reps"] == 18
    assert strength["total_volume_kg"] == 5.4
    assert [item["set_type"] for item in strength["sets"]] == ["active", "rest", "active"]
    assert strength["sets"][0]["weight_kg"] == 20
    assert strength["sets"][2]["weight_kg"] == 25


def test_strength_parser_derives_only_missing_counts_and_rejects_unknown_weight_units():
    strength = parse_strength_training(
        {},
        [
            {"setType": "ACTIVE", "reps": 5, "weight": 100, "weightUnit": "stone"},
            {"setType": "REST", "duration": 30},
            {"setType": "ACTIVE", "reps": float("nan"), "weight": float("inf"), "weightUnit": "kg"},
        ],
    )

    assert strength["total_sets"] == 2
    assert strength["active_sets"] == 2
    assert strength["total_reps"] is None
    assert strength["total_volume_kg"] is None
    assert strength["sets"][0]["weight_kg"] is None
    assert strength["sets"][2]["reps"] == 0
    assert strength["sets"][2]["weight_kg"] is None


def test_strength_parser_derives_reps_only_when_every_active_set_has_a_valid_source_count():
    derived = parse_strength_training(
        {},
        [
            {"setType": "ACTIVE", "reps": 0},
            {"setType": "ACTIVE", "reps": 8},
        ],
    )
    rest_only = parse_strength_training(
        {},
        [{"setType": "REST", "duration": 30}, {"setType": "unknown"}],
    )

    assert derived["total_sets"] == 2
    assert derived["active_sets"] == 2
    assert derived["total_reps"] == 8
    assert rest_only["total_sets"] is None
    assert rest_only["active_sets"] is None
    assert rest_only["total_reps"] is None


def test_strength_parser_accepts_nested_garmin_wrapper_aliases():
    strength = parse_strength_training(
        {"activityInfo": {"totalSets": 1, "totalReps": 6}},
        {"exerciseSets": {"exerciseSetDTOs": [{"setType": "ACTIVE", "repCount": 6, "weightLb": 10}]}},
    )

    assert strength["total_sets"] == 1
    assert strength["total_reps"] == 6
    assert strength["sets"][0]["weight_kg"] == pytest.approx(4.5359)


def test_strength_parser_preserves_zero_based_garmin_set_indices():
    strength = parse_strength_training(
        {},
        {
            "exerciseSets": [
                {"setIndex": 0, "setType": "active", "reps": 8},
                {"setIndex": 1, "setType": "active", "reps": 8},
            ]
        },
    )

    assert [item["set_index"] for item in strength["sets"]] == [0, 1]


def test_strength_context_keeps_distance_unavailable_and_adds_load_effect_and_aggregates():
    strength = parse_strength_training(*(_fixture_payload()[key] for key in ("summary", "exercise_sets")))
    context = build_deterministic_coach_context(
        normalize_activity_window(
            [
                {
                    "activity_id": 1,
                    "type": "running",
                    "date": "2026-08-18",
                    "distance": 5.0,
                    "duration": 30,
                    "raw_data": {"training_stress_score": 30, "hr_zone_1": 50},
                },
                {
                    "activity_id": 2,
                    "type": "strength_training",
                    "date": "2026-08-19",
                    "duration": 45,
                    "average_heart_rate": 125,
                    "raw_data": {
                        "training_stress_score": 22,
                        "aerobic_training_effect": 1.4,
                        "anaerobic_training_effect": 0.8,
                        "strength": strength,
                        "strength_sets_available": True,
                    },
                },
            ]
        ),
        today="2026-08-20",
    )

    week = context["weekly_analysis"][0]
    session = next(item for item in week["sessions"] if item["activity_id"] == 2)
    assert session["distance_km"] is None
    assert session["avg_pace"] is None
    assert session["training_load"] == 22
    assert session["training_effect_aerobic"] == 1.4
    assert session["strength"] == strength
    assert "distance_km" not in session["data_quality"]["missing_fields"]
    assert week["derived_total_distance_km"] == 5
    assert week["derived_training_load"] == 52
    assert context["cross_training"]["strength_training"] == {
        "sessions_count": 1,
        "total_sets": 3.0,
        "total_reps": 18.0,
        "total_volume_kg": 5.4,
    }
    assert context["hr_zone_distribution"]["total_minutes"] == 0.8
    assert {
        fact["fact_id"] for fact in context["evidence_facts"]
    } >= {
        "strength_2_total_sets",
        "strength_2_total_reps",
        "strength_2_total_volume_kg",
    }

    enforced = enforce_deterministic_report_fields(
        {
            "weekly_analysis": [
                {"week_start": item["week_start"], "sessions": []}
                for item in context["weekly_analysis"]
            ],
            "evidence_links": [{
                "supporting_sessions": [{"activity_id": 2}],
            }],
        },
        context,
    )
    assert enforced["evidence_links"][0]["supporting_sessions"][0]["strength"] == strength


def test_strength_context_marks_empty_exercise_sets_partial_and_nulls_weekly_aggregates():
    parsed_strength = parse_strength_training({}, [])
    assert parsed_strength["total_sets"] is None
    assert parsed_strength["active_sets"] is None
    assert parsed_strength["total_reps"] is None
    context = build_deterministic_coach_context(
        normalize_activity_window(
            [{
                "activity_id": 2,
                "type": "strength_training",
                "date": "2026-08-19",
                "duration": 45,
                "raw_data": {
                    "training_stress_score": 22,
                    "strength": parsed_strength,
                    "strength_sets_available": False,
                },
            }]
        ),
        today="2026-08-20",
    )
    session = context["weekly_analysis"][0]["sessions"][0]
    assert session["strength"]["sets"] == []
    assert session["strength"]["total_sets"] is None
    assert session["strength"]["active_sets"] is None
    assert session["strength"]["total_reps"] is None
    assert session["data_quality"] == {"status": "partial", "missing_fields": ["strength.sets"]}
    assert context["cross_training"]["strength_training"]["total_sets"] is None
    validated = SessionFacts.from_context_payload(
        session,
        location="strength session",
    ).strength
    assert validated is not None
    assert (validated.total_sets, validated.active_sets, validated.total_reps) == (None, None, None)
    message = format_activity_message(session, None)
    assert "總組數" not in message
    assert "總次數" not in message


def test_strength_context_keeps_missing_strength_payload_counts_unavailable():
    context = build_deterministic_coach_context(
        normalize_activity_window(
            [{
                "activity_id": 3,
                "type": "strength_training",
                "date": "2026-08-19",
                "duration": 45,
                "raw_data": {"training_stress_score": 22},
            }]
        ),
        today="2026-08-20",
    )

    session = context["weekly_analysis"][0]["sessions"][0]
    assert session["strength"] == {
        "total_sets": None,
        "active_sets": None,
        "total_reps": None,
        "total_volume_kg": None,
        "sets": [],
    }
    assert session["data_quality"] == {"status": "partial", "missing_fields": ["strength.sets"]}


def test_strength_activity_fetch_uses_exercise_sets_and_never_requests_lap_splits():
    class Client:
        split_calls = 0

        def __init__(self, *_args):
            pass

        def login(self):
            pass

        def get_rhr_day(self, _date):
            return {}

        def get_user_profile(self):
            return {}

        def get_personal_record(self):
            return []

        def get_activities(self, start, _limit):
            return [{
                "activityId": 2,
                "activityType": {"typeKey": "strength_training"},
                "startTimeLocal": "2026-08-19 08:00:00",
                "duration": 2700,
            }] if start == 0 else []

        def get_activity(self, _id):
            return {"totalSets": 1, "totalReps": 5}

        def get_activity_exercise_sets(self, _id):
            return [{"setType": "ACTIVE", "reps": 5}]

        def get_activity_splits(self, _id):
            Client.split_calls += 1
            return {"lapDTOs": []}

    with patch.dict("os.environ", {"GARMIN_ACCOUNT": "test", "GARMIN_PASSWORD": "test"}), patch(
        "src.ingestion.garmin_client.Garmin", Client
    ):
        payload = get_garmin_activities(
            n=1,
            activity_types={"strength_training": "strength_training"},
        )
    assert payload["activities"][0]["type"] == "strength_training"
    assert payload["activities"][0]["splits"] == []
    assert Client.split_calls == 0


def test_all_strength_fetch_fails_fast_on_rate_limit_before_artifacts_exist():
    class Client:
        def __init__(self, *_args):
            pass

        def login(self):
            pass

        def get_activities(self, _start, _limit):
            raise RuntimeError("429 rate limited")

    with patch.dict("os.environ", {"GARMIN_ACCOUNT": "test", "GARMIN_PASSWORD": "test"}), patch(
        "src.ingestion.garmin_client.Garmin", Client
    ), pytest.raises(GarminIngestionError):
        get_all_strength_training_activities()


def test_all_strength_fetch_tolerates_only_missing_exercise_sets_and_scans_to_empty_page():
    class Client:
        starts: list[int] = []

        def __init__(self, *_args):
            Client.starts = []

        def login(self):
            pass

        def get_activities(self, start, _limit):
            Client.starts.append(start)
            return [{
                "activityId": 9,
                "activityType": {"typeKey": "strength_training"},
                "startTimeLocal": "2026-08-19 08:00:00",
                "duration": 60,
            }] if start == 0 else []

        def get_activity(self, _id):
            return {"totalSets": 1, "totalReps": 5}

        def get_activity_exercise_sets(self, _id):
            raise RuntimeError("HTTP 404 Not Found")

    with patch.dict("os.environ", {"GARMIN_ACCOUNT": "test", "GARMIN_PASSWORD": "test"}), patch(
        "src.ingestion.garmin_client.Garmin", Client
    ):
        payload = get_all_strength_training_activities()
    assert Client.starts == [0, 50]
    assert payload["activities"][0]["raw_data"]["strength"]["sets"] == []
    assert payload["activities"][0]["raw_data"]["strength_sets_available"] is False


def test_all_strength_fetch_does_not_treat_a_rate_limit_message_with_404_as_missing_sets():
    class Client:
        def __init__(self, *_args):
            pass

        def login(self):
            pass

        def get_activities(self, start, _limit):
            return [{
                "activityId": "9",
                "activityType": {"typeKey": "strength_training"},
                "startTimeLocal": "2026-08-19 08:00:00",
                "duration": 60,
            }] if start == 0 else []

        def get_activity(self, _id):
            return {"totalSets": 1, "totalReps": 5}

        def get_activity_exercise_sets(self, _id):
            raise RuntimeError("429 rate limit while fetching activity 404")

    with patch.dict("os.environ", {"GARMIN_ACCOUNT": "test", "GARMIN_PASSWORD": "test"}), patch(
        "src.ingestion.garmin_client.Garmin", Client
    ), pytest.raises(GarminIngestionError):
        get_all_strength_training_activities()


def test_strength_line_and_weekly_line_never_render_zero_kilometres():
    activity = {
        "activity_id": 2,
        "date": "2026-08-19",
        "source_activity_type": "strength_training",
        "distance_km": None,
        "duration_min": 45,
        "training_load": 22,
        "avg_hr": 125,
        "strength": {"total_sets": 3, "total_reps": 18, "total_volume_kg": 5.4, "sets": []},
    }
    message = format_activity_message(activity, None)
    assert "肌力訓練" in message
    assert "總組數：3" in message and "總容量：5.4 kg" in message
    assert "0 km" not in message
    weekly_messages = format_weekly_report_messages(
        {
            "week_start": "2026-08-17",
            "week_end": "2026-08-23",
            "totals": {"workout_count": 1, "distance_km": None, "duration_min": 45},
            "sports": [{"display_name": "肌力訓練", "count": 1, "distance_km": None, "duration_min": 45}],
            "training_load": {"garmin_weekly_load": 22},
            "next_week_plan_seed": {"days": [{"date": f"2026-08-{24 + day}", "day_of_week": weekday} for day, weekday in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])]},
        },
        report_text="本週肌力課已納入跑步恢復判讀。",
        report_json={
            "analysis": "本週肌力課已納入跑步恢復判讀。",
            "recommendation": "保留跑課間距。",
            "next_week_plan": [{"session": "休息", "description": "恢復"} for _ in range(7)],
        },
    )
    assert "肌力訓練：1 次｜45 分" in "\n".join(weekly_messages)
    assert "肌力訓練：1 次｜0 km" not in "\n".join(weekly_messages)
    assert "總計：1 次｜45 分" in "\n".join(weekly_messages)
    assert "總計：1 次｜0 km" not in "\n".join(weekly_messages)


def test_strength_backfill_baseline_leaves_only_three_newest_in_current_window_unseeded():
    activities = [
        {"activity_id": activity_id, "type": "strength_training", "date": day}
        for activity_id, day in [(1, "2026-07-01"), (2, "2026-08-04"), (3, "2026-08-10"), (4, "2026-08-18"), (5, "2026-08-19")]
    ]
    assert strength_backfill_baseline_ids(activities, today=date(2026, 8, 20)) == [1, 2]


def test_strength_backfill_baseline_normalizes_string_garmin_ids():
    activities = [{"activity_id": str(activity_id), "type": "strength_training", "date": "2026-07-01"} for activity_id in (1, 2)]

    assert strength_backfill_baseline_ids(activities, today=date(2026, 8, 20)) == [1, 2]


def test_strength_backfill_baseline_rejects_non_integral_activity_ids():
    with pytest.raises(ValueError, match="positive integer"):
        strength_backfill_baseline_ids(
            [{"activity_id": 1.5, "type": "strength_training", "date": "2026-07-01"}],
            today=date(2026, 8, 20),
        )


def test_all_three_coaching_prompts_define_strength_guardrails():
    for prompt_name in ("activity_coach.md", "weekly_coach.md", "coach.md"):
        prompt = Path("prompts") / prompt_name
        contents = prompt.read_text(encoding="utf-8")
        assert "strength_training" in contents
        assert "不得" in contents
        assert "不是 0" in contents
