from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from src.notifications.formatter import format_activity_message
from src.preprocessing.activity_window import normalize_activity_window
from src.preprocessing.coach_context_session_facts import (
    RunningSegmentFacts,
    RunningSessionFacts,
    SessionFactContractError,
    SessionFacts,
    SwimmingSegmentFacts,
    SwimmingSessionFacts,
    build_session_evidence_index,
    build_session_facts,
    reconcile_session_facts,
)


def _mixed_activity_window():
    return normalize_activity_window(
        [
            {
                "activity_id": 1,
                "type": "running",
                "date": "2026-05-12",
                "distance": 20.965,
                "duration": 100,
                "average_heart_rate": 150,
                "splits": [
                    {
                        "split_index": 1,
                        "distance": 1,
                        "duration": 5,
                        "pace": 5,
                        "average_heart_rate": 148,
                        "avg_cadence": 176,
                        "stride_length": 112,
                        "temperature": 28,
                    }
                ],
                "raw_data": {
                    "training_stress_score": 50,
                    "aerobic_training_effect": 3.1,
                    "anaerobic_training_effect": 0.4,
                    "temperature": 28,
                },
            },
            {
                "activity_id": "2",
                "type": "cycling",
                "date": "2026-05-13",
                "distance": 20,
                "duration": 60,
                "splits": [
                    {
                        "split_index": 1,
                        "distance": 20,
                        "duration": 60,
                        "speed_kmh": 20,
                        "avg_cadence": 88,
                    }
                ],
                "raw_data": {"training_stress_score": 30},
            },
            {
                "activity_id": 3,
                "type": "swimming",
                "date": "2026-05-14",
                "distance": 0.2,
                "duration": 5.25,
                "elapsed_duration": 5.5,
                "moving_duration": 4.75,
                "rest_duration": 0.75,
                "splits": [
                    {
                        "split_index": 1,
                        "distance": 0.1,
                        "duration": 2.25,
                        "elapsed_duration": 2.25,
                        "pace": 2.25,
                    },
                    {
                        "split_index": 2,
                        "interval_type": "rest",
                        "distance": 0,
                        "duration": 0.5,
                        "elapsed_duration": 0.5083333333,
                    },
                ],
                "raw_data": {"training_stress_score": 20},
            },
        ]
    )


def test_build_session_facts_is_immutable_and_owns_sport_presence():
    fact_set = build_session_facts(_mixed_activity_window())

    assert isinstance(fact_set.facts[0], SessionFacts)
    assert isinstance(fact_set.facts[0].running, RunningSessionFacts)
    assert isinstance(fact_set.facts[0].segments[0].running, RunningSegmentFacts)
    assert fact_set.facts[1].running is None
    assert isinstance(fact_set.facts[2].swimming, SwimmingSessionFacts)
    assert isinstance(fact_set.facts[2].segments[0].swimming, SwimmingSegmentFacts)
    assert isinstance(fact_set.facts, tuple)
    assert isinstance(fact_set.facts[0].segments, tuple)

    with pytest.raises(FrozenInstanceError):
        fact_set.facts[0].distance_km = 999

    sessions = fact_set.context_payloads()
    assert [session["activity_id"] for session in sessions] == [1, "2", 3]
    assert sessions[0]["distance_km"] == 20.96
    assert {"cadence", "stride_length_m"} <= set(sessions[0]["segments"][0])
    assert "cadence" not in sessions[1]["segments"][0]
    assert "stride_length_m" not in sessions[1]["segments"][0]
    assert sessions[2]["rest_duration_min"] == 0.75
    assert sessions[2]["segments"][1]["elapsed_duration_min"] == 0.5083

    sessions[0]["segments"][0]["distance_km"] = 999
    assert fact_set.context_payloads()[0]["segments"][0]["distance_km"] == 1.0


def test_session_facts_distinguish_missing_core_values_from_zero():
    fact_set = build_session_facts(
        normalize_activity_window(
            [
                {"activity_id": 10, "type": "running", "date": "2026-05-12"},
                {
                    "activity_id": 11,
                    "type": "running",
                    "date": "2026-05-13",
                    "distance": 0,
                    "duration": 0,
                    "raw_data": {"training_stress_score": 0},
                },
            ]
        )
    )
    missing, zero = fact_set.context_payloads()

    assert (missing["distance_km"], missing["duration_min"], missing["training_load"]) == (0, 0, 0)
    assert missing["data_quality"] == {
        "status": "partial",
        "missing_fields": ["distance_km", "duration_min", "training_load"],
    }
    assert zero["data_quality"] == {"status": "complete", "missing_fields": []}


def test_reconcile_session_facts_allows_only_nonblank_positional_annotations():
    deterministic = build_session_facts(_mixed_activity_window()).context_payloads()
    deterministic_before = deepcopy(deterministic)
    ai_sessions = [
        {
            "activity_id": "3.0",
            "distance_km": 999,
            "coaching_note": "游泳註解",
            "segments": [
                {"duration_min": 999, "note": "游泳段一"},
                {"segment_type": "lap", "note": "游泳休息段"},
                {"note": "額外分段"},
            ],
        },
        {
            "activity_id": 1,
            "date": "1900-01-01",
            "coaching_note": "跑步註解",
            "segments": [{"distance_km": 999, "note": "跑步分段註解"}],
        },
        {
            "activity_id": "2",
            "coaching_note": "   ",
            "segments": [{"note": 123}],
        },
        {"activity_id": 999, "coaching_note": "不得新增"},
    ]

    report_sessions = reconcile_session_facts(deterministic, ai_sessions)

    assert deterministic == deterministic_before
    assert [session["activity_id"] for session in report_sessions] == [1, "2", 3]
    assert report_sessions[0]["distance_km"] == 20.96
    assert report_sessions[0]["date"] == "2026-05-12"
    assert report_sessions[0]["coaching_note"] == "跑步註解"
    assert report_sessions[0]["segments"][0]["note"] == "跑步分段註解"
    assert report_sessions[1]["coaching_note"] is None
    assert report_sessions[1]["segments"][0]["note"] is None
    assert report_sessions[2]["coaching_note"] == "游泳註解"
    assert report_sessions[2]["segments"][1]["segment_type"] == "rest"
    assert report_sessions[2]["segments"][1]["note"] == "游泳休息段"
    assert len(report_sessions[2]["segments"]) == 2
    assert "data_quality" not in report_sessions[0]
    assert "temperature_c" not in report_sessions[0]["segments"][0]


def test_reconcile_session_facts_treats_malformed_ai_as_no_annotations():
    deterministic = build_session_facts(_mixed_activity_window()).context_payloads()

    report_sessions = reconcile_session_facts(deterministic, "not-a-session-list")

    assert all(session["coaching_note"] is None for session in report_sessions)
    assert all(
        segment["note"] is None
        for session in report_sessions
        for segment in session["segments"]
    )

    malformed_session = reconcile_session_facts(
        deterministic,
        [
            {
                "activity_id": 1,
                "coaching_note": "不得保留",
                "segments": "not-a-list",
            }
        ],
    )
    assert malformed_session[0]["coaching_note"] is None

    duplicate_identity = reconcile_session_facts(
        deterministic,
        [
            {"activity_id": 1, "coaching_note": "第一筆"},
            {"activity_id": "1.0", "coaching_note": "第二筆"},
        ],
    )
    assert duplicate_identity[0]["coaching_note"] is None


def test_reconcile_session_facts_rejects_broken_deterministic_contract():
    deterministic = build_session_facts(_mixed_activity_window()).context_payloads()
    duplicate = deepcopy(deterministic)
    duplicate[1]["activity_id"] = "1.0"

    with pytest.raises(SessionFactContractError, match="duplicate"):
        reconcile_session_facts(duplicate, [])

    malformed = deepcopy(deterministic)
    malformed[0]["segments"] = "not-a-list"
    with pytest.raises(SessionFactContractError, match="segments"):
        reconcile_session_facts(malformed, [])

    malformed_value = deepcopy(deterministic)
    malformed_value[0]["distance_km"] = "20.96"
    with pytest.raises(SessionFactContractError, match="distance_km"):
        reconcile_session_facts(malformed_value, [])

    malformed_annotation = deepcopy(deterministic)
    malformed_annotation[0]["coaching_note"] = 123
    with pytest.raises(SessionFactContractError, match="coaching_note"):
        reconcile_session_facts(malformed_annotation, [])

    malformed_segment_annotation = deepcopy(deterministic)
    malformed_segment_annotation[0]["segments"][0]["note"] = 123
    with pytest.raises(SessionFactContractError, match="note"):
        reconcile_session_facts(malformed_segment_annotation, [])


def test_session_facts_owner_resolves_and_projects_evidence_identity():
    deterministic = build_session_facts(_mixed_activity_window()).context_payloads()
    report_sessions = reconcile_session_facts(deterministic, [])
    index = build_session_evidence_index([{"sessions": report_sessions}])

    reference = index.resolve({"activity_id": "1.0"})
    assert reference is not None
    supporting_session = {
        "activity_id": "1.0",
        "type": "interval",
        "distance_km": 999,
        "reason": "保留 AI 說明",
    }
    index.project_supporting_session(supporting_session, reference)

    assert supporting_session["source_path"] == "weekly_analysis[0].sessions[0]"
    assert supporting_session["activity_id"] == 1
    assert supporting_session["distance_km"] == 20.96
    assert supporting_session["reason"] == "保留 AI 說明"
    assert "type" not in supporting_session

    by_identity = index.resolve(
        {
            "date": "2026-05-12",
            "source_activity_type": "running",
            "distance_km": 20.96,
            "duration_min": 100,
            "avg_pace": report_sessions[0]["avg_pace"],
        }
    )
    assert by_identity == reference


def test_session_evidence_identity_does_not_guess_when_fallback_is_ambiguous():
    deterministic = build_session_facts(_mixed_activity_window()).context_payloads()
    report_session = reconcile_session_facts(deterministic, [])[0]
    duplicate_identity = deepcopy(report_session)
    duplicate_identity["activity_id"] = 99
    index = build_session_evidence_index(
        [{"sessions": [report_session, duplicate_identity]}]
    )

    assert index.resolve(
        {
            "date": report_session["date"],
            "source_activity_type": report_session["source_activity_type"],
            "distance_km": report_session["distance_km"],
            "duration_min": report_session["duration_min"],
            "avg_pace": report_session["avg_pace"],
        }
    ) is None


def test_session_facts_context_remains_formatter_compatible():
    sessions = build_session_facts(_mixed_activity_window()).context_payloads()
    week = {"derived_training_load": sum(session["training_load"] for session in sessions)}

    running_message = format_activity_message(sessions[0], week)
    swimming_message = format_activity_message(sessions[2], week)

    assert "跑步" in running_message
    assert "/km" in running_message
    assert "游泳" in swimming_message
    assert "/100m" in swimming_message
    assert "休息時間" in swimming_message
