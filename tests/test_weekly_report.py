from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import AIReport, LineNotification, WeeklySummary
from src.db.repositories import get_or_create_default_user
from src.notifications.line_client import LineSendResult
from src.preprocessing.weekly_report import build_completed_week_summary
from src.services.ai_report_resolution import AIReportDraft, AIReportSpec
from src.services.weekly_training_report import (
    LINE_RETRY_KEY_SAFE_WINDOW,
    WeeklyTrainingReportRunner,
    _weekly_ai_idempotency_key,
)
from tests.db_test_utils import isolated_db_session


@pytest.fixture()
def db_session() -> Iterator[Session]:
    yield from isolated_db_session()


def _session(
    activity_id: int,
    day: str,
    source_type: str,
    distance: float,
    duration: float,
    load: float,
    *,
    aerobic: float | None = None,
    anaerobic: float | None = None,
) -> dict[str, Any]:
    return {
        "activity_id": activity_id,
        "date": day,
        "source_activity_type": source_type,
        "distance_km": distance,
        "duration_min": duration,
        "training_load": load,
        "training_effect_aerobic": aerobic,
        "training_effect_anaerobic": anaerobic,
        "data_quality": {"status": "complete", "missing_fields": []},
    }


def _week(start: str, end: str, sessions: list[dict[str, Any]], load: float) -> dict[str, Any]:
    return {
        "week_start": start,
        "week_end": end,
        "week_label": f"{start[5:]}-{end[5:]}",
        "derived_total_distance_km": round(sum(item["distance_km"] for item in sessions), 2),
        "derived_total_duration_min": round(sum(item["duration_min"] for item in sessions), 1),
        "derived_training_load": load,
        "sessions": sessions,
        "session_counts": {
            "total": len(sessions),
            "by_source_activity_type": {
                source: sum(1 for item in sessions if item["source_activity_type"] == source)
                for source in sorted({item["source_activity_type"] for item in sessions})
            },
        },
        "data_quality": {"status": "complete", "missing_fields": []},
        "risk_flags": [],
    }


def _context(*, target_load: float = 120.0) -> dict[str, Any]:
    target_sessions = [
        _session(101, "2026-08-03", "running", 10.0, 55.0, 50.0, aerobic=4.2),
        _session(102, "2026-08-05", "swimming", 2.0, 45.0, 30.0),
        _session(103, "2026-08-08", "cycling", 30.0, 90.0, 40.0),
    ]
    return {
        "athlete_profile": {
            "available_training_days": ["Mon", "Wed", "Sat"],
            "preferred_long_training_days": ["Sat"],
        },
        "weekly_analysis": [
            _week("2026-08-10", "2026-08-16", [], 0.0),
            _week("2026-08-03", "2026-08-09", target_sessions, target_load),
            _week("2026-07-27", "2026-08-02", [], 90.0),
            _week("2026-07-20", "2026-07-26", [], 70.0),
        ],
    }


def _draft(_spec: AIReportSpec) -> AIReportDraft:
    return AIReportDraft(
        report_text="本週負荷維持穩定，跑步與交叉訓練安排均衡。\n\n建議：保持恢復品質。",
        model_name="test-model",
        report_json={
            "analysis": "本週負荷維持穩定，跑步與交叉訓練安排均衡。",
            "recommendation": "保持恢復品質。",
            "next_week_plan": [
                {"session": "恢復", "description": f"第 {index} 天依體感調整。"}
                for index in range(1, 8)
            ],
        },
    )


class _Transport:
    def __init__(self, results: list[bool] | None = None) -> None:
        self.results = list(results or [True])
        self.messages: list[tuple[str, ...]] = []

    def send(self, _token: str, _group_id: str, messages: Sequence[str]) -> LineSendResult:
        self.messages.append(tuple(messages))
        success = self.results.pop(0) if self.results else True
        return LineSendResult(success, 200 if success else 500, 1, None if success else "server_error")


class _FailingCommitSession:
    """Fail only the post-LINE acknowledgement commit of one runner."""

    def __init__(self, session: Session, *, fail_on_commit: int) -> None:
        self._session = session
        self._fail_on_commit = fail_on_commit
        self._commits = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    def commit(self) -> None:
        self._commits += 1
        if self._commits == self._fail_on_commit:
            raise RuntimeError("simulated acknowledgement database failure")
        self._session.commit()


def _runner(
    db_session: Session,
    *,
    generate=_draft,
    render=None,
    transport: _Transport | None = None,
) -> WeeklyTrainingReportRunner:
    @contextmanager
    def session_factory() -> Iterator[Session]:
        yield db_session

    kwargs: dict[str, Any] = {
        "session_factory": session_factory,
        "generate": generate,
        "token": "token",
        "group_id": "group",
        "transport": transport or _Transport(),
    }
    if render is not None:
        kwargs["render"] = render
    return WeeklyTrainingReportRunner(**kwargs)


def test_completed_week_summary_uses_previous_complete_week_and_keeps_sport_totals():
    summary = build_completed_week_summary(_context(), today=date(2026, 8, 10))

    assert summary.week_start == date(2026, 8, 3)
    assert summary.week_end == date(2026, 8, 9)
    assert summary.summary_json["totals"] == {
        "workout_count": 3,
        "distance_km": 42.0,
        "duration_min": 190.0,
    }
    assert [sport["display_name"] for sport in summary.summary_json["sports"]] == [
        "自行車",
        "跑步",
        "游泳",
    ]
    assert summary.summary_json["training_load"]["garmin_weekly_load"] == 120.0
    assert summary.summary_json["training_load"]["chronic_load"] == 80.0
    assert summary.summary_json["training_load"]["acute_chronic_ratio"] == 1.5
    assert summary.summary_json["next_week_plan_seed"]["week_start"] == "2026-08-10"
    assert summary.summary_json["next_week_plan_seed"]["days"][0]["date"] == "2026-08-10"


def test_completed_week_summary_combines_swimming_aliases_and_rest_days_for_load_metrics():
    sessions = [
        _session(101, "2026-08-03", "swimming", 2.0, 45.0, 30.0),
        _session(102, "2026-08-05", "lap_swimming", 3.0, 60.0, 40.0),
    ]
    context = _context()
    context["weekly_analysis"][1] = _week(
        "2026-08-03",
        "2026-08-09",
        sessions,
        70.0,
    )

    summary = build_completed_week_summary(context, today=date(2026, 8, 10))

    assert summary.metrics["swimming_distance_km"] == 5.0
    assert summary.metrics["swimming_count"] == 2
    assert summary.metrics["monotony"] == pytest.approx(0.62)
    assert summary.metrics["strain"] == pytest.approx(43.4)


def test_weekly_runner_persists_then_sends_once_and_recomputes_sent_summary(db_session: Session):
    user = get_or_create_default_user(db_session)
    transport = _Transport()
    generated = 0

    def generate(spec: AIReportSpec) -> AIReportDraft:
        nonlocal generated
        generated += 1
        return _draft(spec)

    runner = _runner(db_session, generate=generate, transport=transport)
    first = runner.run(
        user_id=user.id,
        deterministic_context=_context(),
        today=date(2026, 8, 10),
    )
    second = runner.run(
        user_id=user.id,
        deterministic_context=_context(target_load=150.0),
        today=date(2026, 8, 10),
    )

    summary = db_session.scalar(select(WeeklySummary))
    notification = db_session.scalar(select(LineNotification))
    assert first.status == "sent"
    assert first.sent == 1
    assert second.status == "already_sent"
    assert generated == 1
    assert len(transport.messages) == 1
    assert summary is not None
    assert float(summary.training_load) == 150.0
    assert notification is not None
    assert notification.sent_at is not None
    assert notification.rendered_messages == list(transport.messages[0])
    assert db_session.scalar(select(func.count()).select_from(AIReport)) == 1
    assert db_session.scalar(select(func.count()).select_from(LineNotification)) == 1


def test_weekly_runner_retries_immutable_pending_payload_without_ai_or_render(db_session: Session):
    user = get_or_create_default_user(db_session)
    first_transport = _Transport([False])
    first_runner = _runner(db_session, transport=first_transport)

    failed = first_runner.run(
        user_id=user.id,
        deterministic_context=_context(),
        today=date(2026, 8, 10),
    )
    persisted_payload = first_transport.messages[0]

    def should_not_generate(_spec: AIReportSpec) -> AIReportDraft:
        pytest.fail("pending payload retry must not generate another AI report")

    def should_not_render(*_args: Any) -> Sequence[str]:
        pytest.fail("pending payload retry must not rerender")

    retry_transport = _Transport([True])
    retry_runner = _runner(
        db_session,
        generate=should_not_generate,
        render=should_not_render,
        transport=retry_transport,
    )
    retried = retry_runner.run(
        user_id=user.id,
        deterministic_context=_context(target_load=150.0),
        today=date(2026, 8, 10),
    )

    notification = db_session.scalar(select(LineNotification))
    assert failed.status == "line_failed"
    assert retried.status == "retried_pending"
    assert retried.sent == 1
    assert retry_transport.messages == [persisted_payload]
    assert notification is not None
    assert notification.rendered_messages == list(persisted_payload)
    assert notification.sent_at is not None


def test_weekly_runner_fails_closed_after_line_retry_key_window(db_session: Session):
    user = get_or_create_default_user(db_session)
    first_runner = _runner(db_session, transport=_Transport([False]))
    first_runner.run(
        user_id=user.id,
        deterministic_context=_context(),
        today=date(2026, 8, 10),
    )
    notification = db_session.scalar(select(LineNotification))
    assert notification is not None
    notification.recorded_at -= LINE_RETRY_KEY_SAFE_WINDOW + timedelta(seconds=1)
    db_session.commit()

    retry_transport = _Transport()
    result = _runner(db_session, transport=retry_transport).retry_pending(user_id=user.id)

    assert result.status == "retry_window_expired"
    assert result.failed == 1
    assert retry_transport.messages == []
    db_session.refresh(notification)
    assert notification.sent_at is None


def test_weekly_runner_sends_new_week_after_expired_earlier_delivery(db_session: Session):
    user = get_or_create_default_user(db_session)
    first_runner = _runner(db_session, transport=_Transport([False]))
    first_runner.run(
        user_id=user.id,
        deterministic_context=_context(),
        today=date(2026, 8, 10),
    )
    expired = db_session.scalar(select(LineNotification))
    assert expired is not None
    expired.recorded_at -= LINE_RETRY_KEY_SAFE_WINDOW + timedelta(seconds=1)
    db_session.commit()

    next_week_transport = _Transport()
    result = _runner(
        db_session,
        transport=next_week_transport,
    ).run(
        user_id=user.id,
        deterministic_context=_context(),
        today=date(2026, 8, 17),
    )

    db_session.refresh(expired)
    assert result.status == "sent"
    assert result.sent == 1
    assert next_week_transport.messages
    assert expired.sent_at is None
    assert db_session.scalar(select(func.count()).select_from(LineNotification)) == 2


def test_weekly_runner_does_not_send_expired_delivery_for_the_same_week(db_session: Session):
    user = get_or_create_default_user(db_session)
    first_runner = _runner(db_session, transport=_Transport([False]))
    first_runner.run(
        user_id=user.id,
        deterministic_context=_context(),
        today=date(2026, 8, 10),
    )
    expired = db_session.scalar(select(LineNotification))
    assert expired is not None
    expired.recorded_at -= LINE_RETRY_KEY_SAFE_WINDOW + timedelta(seconds=1)
    db_session.commit()

    retry_transport = _Transport()
    result = _runner(
        db_session,
        generate=lambda _spec: pytest.fail("expired payload must not generate AI"),
        render=lambda *_args: pytest.fail("expired payload must not rerender"),
        transport=retry_transport,
    ).run(
        user_id=user.id,
        deterministic_context=_context(),
        today=date(2026, 8, 10),
    )

    assert result.status == "retry_window_expired"
    assert result.failed == 1
    assert retry_transport.messages == []


def test_weekly_retry_skips_expired_delivery_and_sends_newer_safe_pending(db_session: Session):
    user = get_or_create_default_user(db_session)
    old_runner = _runner(db_session, transport=_Transport([False]))
    old_runner.run(
        user_id=user.id,
        deterministic_context=_context(),
        today=date(2026, 8, 10),
    )
    expired = db_session.scalar(select(LineNotification))
    assert expired is not None
    expired.recorded_at -= LINE_RETRY_KEY_SAFE_WINDOW + timedelta(seconds=1)
    db_session.commit()

    newer_runner = _runner(db_session, transport=_Transport([False]))
    newer_runner.run(
        user_id=user.id,
        deterministic_context=_context(),
        today=date(2026, 8, 17),
    )

    retry_transport = _Transport()
    result = _runner(db_session, transport=retry_transport).retry_pending(user_id=user.id)

    assert result.status == "retry_window_expired"
    assert result.sent == 1
    assert result.failed == 1
    assert len(retry_transport.messages) == 1
    db_session.refresh(expired)
    assert expired.sent_at is None


def test_weekly_runner_reuses_persisted_report_with_unavailable_days_safely(db_session: Session):
    user = get_or_create_default_user(db_session)
    transport = _Transport()
    runner = _runner(db_session, transport=transport)
    projection = build_completed_week_summary(_context(), today=date(2026, 8, 10))
    summary = runner._save_summary(user.id, projection)
    report = runner._resolve_report(
        AIReportSpec(
            idempotency_key=_weekly_ai_idempotency_key(projection),
            user_id=user.id,
            report_scope="weekly",
            input_json=dict(summary.summary_json),
            prompt_version="weekly-coach:v1",
            weekly_summary_id=summary.id,
            feature_version="weekly:v1",
        )
    )
    persisted = db_session.get(AIReport, report.id)
    assert persisted is not None
    plan = [dict(entry) for entry in persisted.report_json["next_week_plan"]]
    plan[1] = {"session": "高強度間歇", "description": "進行高強度跑步課表。"}
    persisted.report_json = {**persisted.report_json, "next_week_plan": plan}
    db_session.commit()

    result = _runner(
        db_session,
        generate=lambda _spec: pytest.fail("persisted report must be reused"),
        transport=transport,
    ).run(
        user_id=user.id,
        deterministic_context=_context(),
        today=date(2026, 8, 10),
    )

    rendered = "\n".join(transport.messages[0])
    assert result.status == "sent"
    assert "Tue 2026-08-11｜休息／恢復：此日不可訓練；安排休息或低強度恢復。" in rendered
    assert "高強度間歇" not in rendered


def test_weekly_runner_retries_post_line_acknowledgement_failure_with_saved_payload(db_session: Session):
    user = get_or_create_default_user(db_session)
    first_transport = _Transport([True])
    failing_session = _FailingCommitSession(db_session, fail_on_commit=4)

    @contextmanager
    def failing_factory() -> Iterator[Session]:
        yield failing_session  # type: ignore[misc]

    first_runner = WeeklyTrainingReportRunner(
        session_factory=failing_factory,
        generate=_draft,
        token="token",
        group_id="group",
        transport=first_transport,
    )

    with pytest.raises(RuntimeError, match="acknowledgement"):
        first_runner.run(
            user_id=user.id,
            deterministic_context=_context(),
            today=date(2026, 8, 10),
        )
    db_session.rollback()
    notification = db_session.scalar(select(LineNotification))
    assert notification is not None
    assert notification.sent_at is None
    saved_payload = tuple(notification.rendered_messages or [])

    def should_not_generate(_spec: AIReportSpec) -> AIReportDraft:
        pytest.fail("acknowledgement retry must reuse the persisted AI report")

    retry_transport = _Transport([True])
    retried = _runner(
        db_session,
        generate=should_not_generate,
        render=lambda *_args: pytest.fail("acknowledgement retry must not rerender"),
        transport=retry_transport,
    ).retry_pending(user_id=user.id)

    db_session.refresh(notification)
    assert retried.status == "retried_pending"
    assert retried.sent == 1
    assert retry_transport.messages == [saved_payload]
    assert notification.sent_at is not None
