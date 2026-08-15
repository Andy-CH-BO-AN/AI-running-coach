from __future__ import annotations

import pytest

from src.agents import weekly_coach
from src.services.ai_report_resolution import AIReportSpec


def _spec() -> AIReportSpec:
    import uuid

    return AIReportSpec(
        idempotency_key="weekly:2026-08-03:test",
        user_id=uuid.uuid4(),
        report_scope="weekly",
        input_json={"week_start": "2026-08-03"},
        prompt_version="weekly-coach:v1",
        weekly_summary_id=uuid.uuid4(),
        feature_version="weekly:v1",
    )


def _payload() -> dict:
    return {
        "analysis": "這是一段依據固定週訓練事實撰寫的分析。" * 9,
        "recommendation": "本週優先安排恢復。",
        "next_week_plan": [
            {"session": "恢復", "description": "依體感安排。"}
            for _ in range(7)
        ],
    }


def test_weekly_coach_returns_validated_structured_draft(monkeypatch, tmp_path):
    prompt = tmp_path / "weekly.md"
    prompt.write_text("system prompt", encoding="utf-8")
    monkeypatch.setattr(weekly_coach, "WEEKLY_PROMPT_PATH", prompt)
    monkeypatch.setattr(
        weekly_coach.coach_agent,
        "_generate_content_with_retries",
        lambda _model, _prompt: _payload(),
    )
    monkeypatch.setattr(weekly_coach.coach_agent, "MODEL_FALLBACKS", ("test-model",))

    draft = weekly_coach.generate_weekly_report(_spec())

    assert draft.model_name == "test-model"
    assert draft.report_json == _payload()
    assert "建議：本週優先安排恢復。" in draft.report_text


def test_weekly_coach_rejects_incomplete_plan(monkeypatch, tmp_path):
    prompt = tmp_path / "weekly.md"
    prompt.write_text("system prompt", encoding="utf-8")
    monkeypatch.setattr(weekly_coach, "WEEKLY_PROMPT_PATH", prompt)
    monkeypatch.setattr(
        weekly_coach.coach_agent,
        "_generate_content_with_retries",
        lambda _model, _prompt: {**_payload(), "next_week_plan": []},
    )
    monkeypatch.setattr(weekly_coach.coach_agent, "MODEL_FALLBACKS", ("test-model",))

    with pytest.raises(weekly_coach.WeeklyCoachError, match="unavailable"):
        weekly_coach.generate_weekly_report(_spec())


def test_weekly_coach_rejects_oversized_analysis_before_persistence(monkeypatch, tmp_path):
    prompt = tmp_path / "weekly.md"
    prompt.write_text("system prompt", encoding="utf-8")
    monkeypatch.setattr(weekly_coach, "WEEKLY_PROMPT_PATH", prompt)
    monkeypatch.setattr(
        weekly_coach.coach_agent,
        "_generate_content_with_retries",
        lambda _model, _prompt: {**_payload(), "analysis": "過長" * 400},
    )
    monkeypatch.setattr(weekly_coach.coach_agent, "MODEL_FALLBACKS", ("test-model",))

    with pytest.raises(weekly_coach.WeeklyCoachError, match="unavailable"):
        weekly_coach.generate_weekly_report(_spec())
