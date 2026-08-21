from __future__ import annotations

import json
import uuid

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
from sqlalchemy import select

from src.agents import activity_coach, weekly_coach
from src.db.models import Activity
from src.db.repositories import get_or_create_default_user
from src.services.ai_report_resolution import AIReportSpec
from src.services.db_importer import import_garmin_raw_file
from tests.db_test_utils import isolated_db_session


@pytest.fixture()
def db_session():
    yield from isolated_db_session()


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _strength_activity(*, sets: list[dict], load: int, include_failure_marker: bool = False) -> dict:
    raw_data = {
        "training_stress_score": load,
        "strength": {
            "total_sets": 2,
            "active_sets": 2 if sets else None,
            "total_reps": 18 if sets else None,
            "total_volume_kg": None,
            "sets": sets,
        },
        "strength_sets_available": bool(sets),
        "strength_raw_exercise_sets": sets,
    }
    if include_failure_marker:
        raw_data["strength_sets_fetch_failed"] = True
    if not sets:
        raw_data["strength_raw_summary"] = {
            "summaryDTO": {
                "activityTrainingLoad": load,
                "totalSets": 2,
                "totalReps": 18,
            }
        }
        raw_data["strength"].update({"total_sets": 2, "active_sets": 2, "total_reps": 18})
    return {
        "activity_id": 988,
        "type": "strength_training",
        "date": "2026-08-20",
        "distance": None,
        "duration": 45,
        "average_heart_rate": 121,
        "splits": [],
        "raw_data": raw_data,
    }


def test_empty_backfill_payload_without_failure_marker_preserves_existing_strength_sets(
    db_session,
    tmp_path,
) -> None:
    complete_sets = [
        {
            "set_index": 1,
            "set_type": "active",
            "exercise_names": ["Squat"],
            "category": None,
            "reps": 9,
            "weight_kg": None,
            "duration_sec": None,
        },
        {
            "set_index": 2,
            "set_type": "active",
            "exercise_names": ["Squat"],
            "category": None,
            "reps": 9,
            "weight_kg": None,
            "duration_sec": None,
        },
    ]
    complete_path = tmp_path / "complete.json"
    empty_backfill_path = tmp_path / "empty_backfill.json"
    _write_json(complete_path, [_strength_activity(sets=complete_sets, load=22)])
    _write_json(empty_backfill_path, [_strength_activity(sets=[], load=23)])
    user = get_or_create_default_user(db_session)

    first = import_garmin_raw_file(db_session, user.id, complete_path)
    second = import_garmin_raw_file(db_session, user.id, empty_backfill_path)

    assert first["activities"] == 1
    assert second["activities"] == 0
    activity = db_session.scalars(select(Activity)).one()
    assert activity.raw_json["raw_data"]["strength"]["sets"] == complete_sets
    assert activity.raw_json["raw_data"]["strength"]["total_reps"] == 18
    assert float(activity.training_stress_score) == 22


def test_first_seen_successful_empty_strength_payload_stays_successful_empty(db_session, tmp_path) -> None:
    empty_path = tmp_path / "first_seen_empty.json"
    _write_json(empty_path, [_strength_activity(sets=[], load=23)])
    user = get_or_create_default_user(db_session)

    counts = import_garmin_raw_file(db_session, user.id, empty_path)

    assert counts["activities"] == 1
    activity = db_session.scalars(select(Activity)).one()
    raw_data = activity.raw_json["raw_data"]
    assert raw_data["strength"]["sets"] == []
    assert raw_data["strength_sets_available"] is False
    assert "strength_sets_fetch_failed" not in raw_data


def _activity_spec(input_json: dict) -> AIReportSpec:
    return AIReportSpec(
        idempotency_key="activity:123:activity-coach:v5:review-regression",
        user_id=uuid.uuid4(),
        report_scope="activity",
        input_json=input_json,
        prompt_version=activity_coach.ACTIVITY_PROMPT_VERSION,
        activity_id=uuid.uuid4(),
        feature_version="activity-context:v1",
    )


def test_activity_unknown_load_guard_allows_explicit_no_increase_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = (
        "本次 Garmin 負荷資料不足，不應增加訓練負荷；"
        "目前只能依已知時長與訓練內容保守安排恢復，等負荷資料完整後再判斷後續強度。"
    ) * 4
    monkeypatch.setattr(activity_coach.coach_agent, "MODEL_FALLBACKS", ("provider",))
    monkeypatch.setattr(
        activity_coach.coach_agent,
        "_generate_content_with_retries",
        lambda *_args: {"analysis": analysis},
    )

    report = activity_coach.generate_activity_report(
        _activity_spec({"activity": {"activity_id": 123, "training_load": None}})
    )

    assert report.report_text == analysis


def test_activity_unknown_load_guard_allows_explicit_modifier_no_increase_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = (
        "本次 Garmin 負荷資料不足，避免額外提高 TSS；"
        "目前只能依已知時長與訓練內容保守安排恢復，不做未知負荷高低判斷。"
    ) * 4
    monkeypatch.setattr(activity_coach.coach_agent, "MODEL_FALLBACKS", ("provider",))
    monkeypatch.setattr(
        activity_coach.coach_agent,
        "_generate_content_with_retries",
        lambda *_args: {"analysis": analysis},
    )

    report = activity_coach.generate_activity_report(
        _activity_spec({"activity": {"activity_id": 123, "training_load": None}})
    )

    assert report.report_text == analysis


@pytest.mark.parametrize(
    "advice",
    [
        "不應減少，應增加訓練負荷",
        "不應休息，建議增加訓練負荷",
    ],
)
def test_activity_unknown_load_guard_rejects_unrelated_negation_before_increase(
    monkeypatch: pytest.MonkeyPatch,
    advice: str,
) -> None:
    analysis = (
        f"本次 Garmin 負荷資料不足，{advice}；"
        "其他已知內容只能支持保守恢復與持續觀察，不能用未知負荷推導高低。"
    ) * 4
    monkeypatch.setattr(activity_coach.coach_agent, "MODEL_FALLBACKS", ("provider",))
    monkeypatch.setattr(
        activity_coach.coach_agent,
        "_generate_content_with_retries",
        lambda *_args: {"analysis": analysis},
    )

    with pytest.raises(activity_coach.ActivityCoachError, match="unknown training load"):
        activity_coach.generate_activity_report(
            _activity_spec({"activity": {"activity_id": 123, "training_load": None}})
        )


def _weekly_spec(input_json: dict) -> AIReportSpec:
    return AIReportSpec(
        idempotency_key="weekly:2026-08-17:weekly-coach:v5:review-regression",
        user_id=uuid.uuid4(),
        report_scope="weekly",
        input_json=input_json,
        prompt_version=weekly_coach.WEEKLY_PROMPT_VERSION,
        weekly_summary_id=uuid.uuid4(),
        feature_version="weekly:v5",
    )


def _weekly_payload(recommendation: str) -> dict:
    return {
        "analysis": "這是一段依據固定週訓練事實撰寫的分析，並明確保留 Garmin 未知負荷的資料限制。" * 6,
        "recommendation": recommendation,
        "next_week_plan": [
            {"session": "恢復", "description": "依體感安排，不因未知負荷額外加量。"}
            for _ in range(7)
        ],
    }


def test_weekly_unknown_load_guard_allows_explicit_no_increase_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _weekly_payload("本週負荷資料不足，不應增加訓練負荷；先依體感保守恢復。")
    monkeypatch.setattr(weekly_coach.coach_agent, "MODEL_FALLBACKS", ("provider",))
    monkeypatch.setattr(
        weekly_coach.coach_agent,
        "_generate_content_with_retries",
        lambda *_args: payload,
    )

    report = weekly_coach.generate_weekly_report(
        _weekly_spec({"sessions": [{"training_load": 50}, {"training_load": None}]})
    )

    assert report.report_json == payload


def test_weekly_unknown_load_guard_allows_explicit_modifier_no_increase_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _weekly_payload("本週負荷資料不足，避免額外提高 TSS；先依體感保守恢復。")
    monkeypatch.setattr(weekly_coach.coach_agent, "MODEL_FALLBACKS", ("provider",))
    monkeypatch.setattr(
        weekly_coach.coach_agent,
        "_generate_content_with_retries",
        lambda *_args: payload,
    )

    report = weekly_coach.generate_weekly_report(
        _weekly_spec({"sessions": [{"training_load": 50}, {"training_load": None}]})
    )

    assert report.report_json == payload


@pytest.mark.parametrize(
    "recommendation",
    [
        "本週負荷資料不足，不應減少，應增加訓練負荷。",
        "本週負荷資料不足，不應休息，建議增加訓練負荷。",
    ],
)
def test_weekly_unknown_load_guard_rejects_unrelated_negation_before_increase(
    monkeypatch: pytest.MonkeyPatch,
    recommendation: str,
) -> None:
    payload = _weekly_payload(recommendation)
    monkeypatch.setattr(weekly_coach.coach_agent, "MODEL_FALLBACKS", ("provider",))
    monkeypatch.setattr(
        weekly_coach.coach_agent,
        "_generate_content_with_retries",
        lambda *_args: payload,
    )

    with pytest.raises(weekly_coach.WeeklyCoachError, match="unknown training load"):
        weekly_coach.generate_weekly_report(
            _weekly_spec({"sessions": [{"training_load": 50}, {"training_load": None}]})
        )
