from __future__ import annotations

import uuid

import pytest

from src.agents import activity_coach
from src.services.ai_report_resolution import AIReportSpec


def _spec() -> AIReportSpec:
    return AIReportSpec(
        idempotency_key="activity:123:activity-coach:v1:input",
        user_id=uuid.uuid4(),
        report_scope="activity",
        input_json={"activity": {"activity_id": 123}},
        prompt_version=activity_coach.ACTIVITY_PROMPT_VERSION,
        activity_id=uuid.uuid4(),
        feature_version="activity-context:v1",
    )


def test_activity_coach_generates_validated_compact_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis = "本次訓練完成度穩定，配速與心率可作為本週負荷判讀的參考。後續先安排恢復、補充水分與睡眠，確認雙腿感受良好後再進行下一次品質課表。" * 2
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(activity_coach.coach_agent, "MODEL_FALLBACKS", ("test-model",))
    monkeypatch.setattr(
        activity_coach.coach_agent,
        "_generate_content_with_retries",
        lambda model, prompt: calls.append((model, prompt)) or {"analysis": analysis},
    )

    report = activity_coach.generate_activity_report(_spec())

    assert report.model_name == "test-model"
    assert report.report_text == analysis
    assert report.report_json == {"analysis": analysis}
    assert calls[0][0] == "test-model"
    assert '"activity_id": 123' in calls[0][1]


def test_activity_coach_rejects_analysis_outside_compact_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activity_coach.coach_agent, "MODEL_FALLBACKS", ("test-model",))
    monkeypatch.setattr(
        activity_coach.coach_agent,
        "_generate_content_with_retries",
        lambda *_args: {"analysis": "太短"},
    )

    with pytest.raises(activity_coach.ActivityCoachError, match="unavailable"):
        activity_coach.generate_activity_report(_spec())
