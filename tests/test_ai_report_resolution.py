from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import pytest

import src.services.ai_report_resolution as resolution
from src.db.models import AIReport, Activity, LineNotification
from src.services.ai_report_resolution import (
    AIReportDraft,
    AIReportSpec,
    ActivityAINotificationPreparer,
)


@dataclass
class _FakeSession:
    events: list[str]
    name: str
    activity: Activity | None = None

    def commit(self) -> None:
        self.events.append(f"commit:{self.name}")

    def get(self, model: type[Any], key: uuid.UUID):
        if model is Activity and self.activity is not None and self.activity.id == key:
            return self.activity
        return None


def _report(*, report_id: uuid.UUID, text: str, model: str) -> AIReport:
    return AIReport(
        id=report_id,
        idempotency_key="activity:123:feature-v1:coach-v1:input-a",
        user_id=uuid.uuid4(),
        activity_id=uuid.uuid4(),
        weekly_summary_id=None,
        report_scope="activity",
        report_text=text,
        input_json={"activity_id": 123},
        model_name=model,
        prompt_version="coach:v1",
        feature_version="feature:v1",
        report_json={"analysis": text},
        confidence=None,
        output_path=None,
    )


def _spec(report: AIReport) -> AIReportSpec:
    return AIReportSpec(
        idempotency_key=report.idempotency_key,
        user_id=report.user_id,
        report_scope=report.report_scope,
        input_json={"activity_id": 123},
        prompt_version=report.prompt_version,
        activity_id=report.activity_id,
        feature_version=report.feature_version,
    )


def _activity(report: AIReport, *, garmin_activity_id: int = 123) -> Activity:
    return Activity(
        id=report.activity_id,
        user_id=report.user_id,
        garmin_activity_id=garmin_activity_id,
    )


def test_external_generation_is_unlocked_and_conflict_winner_drives_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    lock_state = {"held": False}
    session_index = 0
    canonical = _report(
        report_id=uuid.uuid4(),
        text="canonical persisted analysis",
        model="canonical-model",
    )
    spec = _spec(canonical)

    @contextmanager
    def session_factory():
        nonlocal session_index
        session_index += 1
        name = f"session-{session_index}"
        events.append(f"open:{name}")
        yield _FakeSession(events, name, _activity(canonical))
        events.append(f"close:{name}")

    @contextmanager
    def notification_lock():
        assert lock_state["held"] is False
        lock_state["held"] = True
        events.append("lock:acquire")
        try:
            yield
        finally:
            events.append("lock:release")
            lock_state["held"] = False

    def generate(request: AIReportSpec) -> AIReportDraft:
        assert request == spec
        assert lock_state["held"] is False
        events.append("external-ai")
        return AIReportDraft(
            report_text="losing generated analysis",
            model_name="losing-model",
            report_json={"analysis": "loser"},
        )

    def get_report(_session: Any, _user_id: uuid.UUID, _key: str):
        events.append("lookup")
        return None

    def save_report(_session: Any, **values: Any) -> AIReport:
        assert values["report_text"] == "losing generated analysis"
        events.append("save-conflict-return-canonical")
        return canonical

    def render(report: resolution.PersistedAIReport) -> list[str]:
        assert report.id == canonical.id
        assert report.report_text == "canonical persisted analysis"
        assert report.model_name == "canonical-model"
        events.append("render-canonical")
        return [f"AI:{report.report_text}"]

    def prepare_notification(_session: Any, **values: Any) -> LineNotification:
        assert lock_state["held"] is True
        assert values["ai_report_id"] == canonical.id
        assert values["rendered_messages"] == [
            "AI:canonical persisted analysis"
        ]
        events.append("prepare-canonical")
        return LineNotification(
            id=uuid.uuid4(),
            garmin_activity_id=values["garmin_activity_id"],
            weekly_summary_id=None,
            ai_report_id=canonical.id,
            rendered_messages=list(values["rendered_messages"]),
            is_seed=False,
        )

    monkeypatch.setattr(resolution, "get_ai_report_by_idempotency_key", get_report)
    monkeypatch.setattr(resolution, "save_ai_report", save_report)
    monkeypatch.setattr(
        resolution,
        "prepare_activity_notification",
        prepare_notification,
    )

    delivery = ActivityAINotificationPreparer(
        session_factory=session_factory,
        notification_lock=notification_lock,
        generate=generate,
        render=render,
    ).prepare(spec=spec, garmin_activity_id=123)

    assert delivery.ai_report_id == canonical.id
    assert delivery.rendered_messages == ("AI:canonical persisted analysis",)
    assert delivery.should_send is True
    assert "losing generated analysis" not in "".join(delivery.rendered_messages)
    assert events.index("external-ai") < events.index("lock:acquire")
    assert events.index("save-conflict-return-canonical") < events.index(
        "render-canonical"
    )
    assert events.index("render-canonical") < events.index("prepare-canonical")


@pytest.mark.parametrize("mismatch", ["garmin_id", "owner"])
def test_wrong_activity_subject_stops_before_external_or_delivery_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    report = _report(
        report_id=uuid.uuid4(),
        text="report",
        model="model",
    )
    events: list[str] = []

    persisted_activity = _activity(
        report,
        garmin_activity_id=999 if mismatch == "garmin_id" else 123,
    )
    if mismatch == "owner":
        persisted_activity.user_id = uuid.uuid4()

    @contextmanager
    def session_factory():
        events.append("session")
        yield _FakeSession(
            events,
            "session",
            persisted_activity,
        )

    @contextmanager
    def notification_lock():
        events.append("lock")
        yield

    monkeypatch.setattr(
        resolution,
        "get_ai_report_by_idempotency_key",
        lambda *_args: events.append("lookup"),
    )
    monkeypatch.setattr(
        resolution,
        "prepare_activity_notification",
        lambda *_args, **_kwargs: events.append("prepare"),
    )

    with pytest.raises(ValueError, match="does not match"):
        ActivityAINotificationPreparer(
            session_factory=session_factory,
            notification_lock=notification_lock,
            generate=lambda _spec: (
                events.append("external-ai")
                or AIReportDraft(report_text="draft", model_name="model")
            ),
            render=lambda _report: events.append("render") or ["payload"],
        ).prepare(spec=_spec(report), garmin_activity_id=123)

    assert events == ["session"]


def test_notification_conflict_returns_persisted_payload_not_local_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(
        report_id=uuid.uuid4(),
        text="canonical report",
        model="canonical-model",
    )
    existing_notification = LineNotification(
        id=uuid.uuid4(),
        garmin_activity_id=123,
        weekly_summary_id=None,
        ai_report_id=uuid.uuid4(),
        rendered_messages=["persisted winner payload"],
        is_seed=False,
    )

    @contextmanager
    def session_factory():
        yield _FakeSession([], "session", _activity(report))

    @contextmanager
    def notification_lock():
        yield

    monkeypatch.setattr(
        resolution,
        "get_ai_report_by_idempotency_key",
        lambda _session, _user_id, _key: report,
    )
    monkeypatch.setattr(
        resolution,
        "prepare_activity_notification",
        lambda _session, **_values: existing_notification,
    )

    delivery = ActivityAINotificationPreparer(
        session_factory=session_factory,
        notification_lock=notification_lock,
        generate=lambda _spec: pytest.fail("existing report must skip external AI"),
        render=lambda _report: ["locally rendered loser payload"],
    ).prepare(spec=_spec(report), garmin_activity_id=123)

    assert delivery.notification_id == existing_notification.id
    assert delivery.ai_report_id == existing_notification.ai_report_id
    assert delivery.rendered_messages == ("persisted winner payload",)
    assert delivery.should_send is True


def test_single_string_render_is_rejected_by_notification_repository_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(
        report_id=uuid.uuid4(),
        text="canonical report",
        model="canonical-model",
    )
    events: list[str] = []

    @contextmanager
    def session_factory():
        yield _FakeSession(events, "session", _activity(report))

    @contextmanager
    def notification_lock():
        events.append("lock")
        yield

    monkeypatch.setattr(
        resolution,
        "get_ai_report_by_idempotency_key",
        lambda _session, _user_id, _key: report,
    )

    with pytest.raises(ValueError, match="collection of messages"):
        ActivityAINotificationPreparer(
            session_factory=session_factory,
            notification_lock=notification_lock,
            generate=lambda _spec: pytest.fail("existing report must skip external AI"),
            render=lambda _report: "one message",
        ).prepare(spec=_spec(report), garmin_activity_id=123)

    assert events == ["lock"]


def test_sent_notification_conflict_is_not_sendable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(
        report_id=uuid.uuid4(),
        text="canonical report",
        model="canonical-model",
    )
    existing_notification = LineNotification(
        id=uuid.uuid4(),
        garmin_activity_id=123,
        weekly_summary_id=None,
        ai_report_id=report.id,
        rendered_messages=["already delivered payload"],
        sent_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
        is_seed=False,
    )

    @contextmanager
    def session_factory():
        yield _FakeSession([], "session", _activity(report))

    @contextmanager
    def notification_lock():
        yield

    monkeypatch.setattr(
        resolution,
        "get_ai_report_by_idempotency_key",
        lambda _session, _user_id, _key: report,
    )
    monkeypatch.setattr(
        resolution,
        "prepare_activity_notification",
        lambda _session, **_values: existing_notification,
    )

    delivery = ActivityAINotificationPreparer(
        session_factory=session_factory,
        notification_lock=notification_lock,
        generate=lambda _spec: pytest.fail("existing report must skip external AI"),
        render=lambda _report: ["local loser"],
    ).prepare(spec=_spec(report), garmin_activity_id=123)

    assert delivery.should_send is False
    assert delivery.rendered_messages == ("already delivered payload",)


def test_existing_report_with_mismatched_identity_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(
        report_id=uuid.uuid4(),
        text="wrong subject",
        model="model",
    )
    spec = _spec(report)
    authorized_activity = _activity(report)
    report.activity_id = uuid.uuid4()

    @contextmanager
    def session_factory():
        yield _FakeSession([], "session", authorized_activity)

    @contextmanager
    def notification_lock():
        pytest.fail("mismatched report must fail before notification preparation")
        yield

    monkeypatch.setattr(
        resolution,
        "get_ai_report_by_idempotency_key",
        lambda _session, _user_id, _key: report,
    )

    with pytest.raises(RuntimeError, match="does not match"):
        ActivityAINotificationPreparer(
            session_factory=session_factory,
            notification_lock=notification_lock,
            generate=lambda _spec: pytest.fail("existing report skips generation"),
            render=lambda _report: pytest.fail("mismatch must not render"),
        ).prepare(spec=spec, garmin_activity_id=123)


def test_generator_and_identity_use_json_normalized_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(
        report_id=uuid.uuid4(),
        text="canonical report",
        model="canonical-model",
    )
    raw_spec = _spec(report)
    raw_spec = AIReportSpec(
        idempotency_key=raw_spec.idempotency_key,
        user_id=raw_spec.user_id,
        report_scope=raw_spec.report_scope,
        input_json={"activity_id": 123, "day": date(2026, 8, 12)},
        prompt_version=raw_spec.prompt_version,
        activity_id=raw_spec.activity_id,
        feature_version=raw_spec.feature_version,
    )
    persisted = report
    persisted.report_text = "normalized report"
    persisted.model_name = "model"
    persisted.input_json = {"activity_id": 123, "day": "2026-08-12"}

    @contextmanager
    def session_factory():
        yield _FakeSession([], "session", _activity(report))

    @contextmanager
    def notification_lock():
        yield

    monkeypatch.setattr(
        resolution,
        "get_ai_report_by_idempotency_key",
        lambda _session, _user_id, _key: None,
    )
    monkeypatch.setattr(
        resolution,
        "save_ai_report",
        lambda _session, **_values: persisted,
    )
    monkeypatch.setattr(
        resolution,
        "prepare_activity_notification",
        lambda _session, **values: LineNotification(
            id=uuid.uuid4(),
            garmin_activity_id=values["garmin_activity_id"],
            ai_report_id=persisted.id,
            rendered_messages=list(values["rendered_messages"]),
            is_seed=False,
        ),
    )

    generated_inputs: list[dict[str, Any]] = []
    delivery = ActivityAINotificationPreparer(
        session_factory=session_factory,
        notification_lock=notification_lock,
        generate=lambda spec: (
            generated_inputs.append(spec.input_json)
            or AIReportDraft(report_text="draft", model_name="model")
        ),
        render=lambda canonical: [canonical.report_text],
    ).prepare(spec=raw_spec, garmin_activity_id=123)

    assert generated_inputs == [{"activity_id": 123, "day": "2026-08-12"}]
    assert delivery.rendered_messages == ("normalized report",)
    assert delivery.should_send is True


def test_generator_cannot_mutate_persisted_report_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(
        report_id=uuid.uuid4(),
        text="canonical report",
        model="canonical-model",
    )
    spec = _spec(report)

    @contextmanager
    def session_factory():
        yield _FakeSession([], "session", _activity(report))

    @contextmanager
    def notification_lock():
        yield

    monkeypatch.setattr(
        resolution,
        "get_ai_report_by_idempotency_key",
        lambda _session, _user_id, _key: None,
    )

    def generate(request: AIReportSpec) -> AIReportDraft:
        request.input_json["activity_id"] = "mutated"
        return AIReportDraft(report_text="draft", model_name="model")

    def save_report(_session: Any, **values: Any) -> AIReport:
        assert values["input_json"] == {"activity_id": 123}
        return report

    monkeypatch.setattr(resolution, "save_ai_report", save_report)
    monkeypatch.setattr(
        resolution,
        "prepare_activity_notification",
        lambda _session, **values: LineNotification(
            id=uuid.uuid4(),
            garmin_activity_id=values["garmin_activity_id"],
            ai_report_id=report.id,
            rendered_messages=list(values["rendered_messages"]),
            is_seed=False,
        ),
    )

    ActivityAINotificationPreparer(
        session_factory=session_factory,
        notification_lock=notification_lock,
        generate=generate,
        render=lambda canonical: [canonical.report_text],
    ).prepare(spec=spec, garmin_activity_id=123)

    assert spec.input_json == {"activity_id": 123}
