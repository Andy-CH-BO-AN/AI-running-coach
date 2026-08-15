from __future__ import annotations

import uuid

import pytest

from src.agents import activity_coach
from src.services.ai_report_resolution import AIReportSpec


def _spec(*, input_json: dict | None = None) -> AIReportSpec:
    return AIReportSpec(
        idempotency_key="activity:123:activity-coach:v1:input",
        user_id=uuid.uuid4(),
        report_scope="activity",
        input_json=input_json or {"activity": {"activity_id": 123}},
        prompt_version=activity_coach.ACTIVITY_PROMPT_VERSION,
        activity_id=uuid.uuid4(),
        feature_version="activity-context:v1",
    )


def test_activity_coach_generates_validated_goal_aware_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis = (
        "本次課表的快段配速維持穩定，後段沒有明顯掉速，心率隨強度逐步上升但恢復段仍能回落，顯示主課完成品質良好。"
        "這種在控制下累積的速度耐力，能支持目前 10 公里目標所需的配速經濟性。明天安排輕鬆跑或休息，若雙腿沉重則優先睡眠與補水，再進入下一堂品質課。"
    ) * 3
    calls: list[str] = []
    monkeypatch.setattr(activity_coach.coach_agent, "MODEL_FALLBACKS", ("provider",))
    monkeypatch.setattr(
        activity_coach.coach_agent,
        "_generate_content_with_retries",
        lambda _model, prompt: calls.append(prompt) or {"analysis": analysis},
    )

    report = activity_coach.generate_activity_report(
        _spec(
            input_json={
                "activity": {"activity_id": 123},
                "core_goal": "10 公里 45 分鐘",
                "training_preferences": "週二游泳",
                "athlete_profile": {"vo2max": {"value": 52}},
            }
        )
    )

    assert report.report_text == analysis
    assert report.report_json == {"analysis": analysis}
    assert '"activity_id": 123' in calls[0]
    assert '"core_goal": "10 公里 45 分鐘"' in calls[0]
    assert '"vo2max"' in calls[0]


def test_activity_coach_rejects_analysis_outside_compact_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activity_coach.coach_agent, "MODEL_FALLBACKS", ("provider",))
    monkeypatch.setattr(
        activity_coach.coach_agent,
        "_generate_content_with_retries",
        lambda *_args: {"analysis": "太短"},
    )

    with pytest.raises(activity_coach.ActivityCoachError, match="unavailable"):
        activity_coach.generate_activity_report(_spec())
