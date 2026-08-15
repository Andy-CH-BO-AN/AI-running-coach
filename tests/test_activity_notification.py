"""Behavior contracts for persistent Activity AI LINE notifications."""
from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

import src.notifications.notifier as notifier
import src.services.ai_report_resolution as resolution
from src.agents.activity_coach import ActivityCoachError
from src.db.models import Activity, LineNotification
from src.notifications.line_client import LineSendResult
from src.notifications.notifier import (
    NotificationDatabaseAccess,
    run_daily_line_notification,
    run_line_notification,
)
from src.services.ai_report_resolution import PreparedLineDelivery


SUCCESS = LineSendResult(True, 200, 1, None)
LINE_FAILURE = LineSendResult(False, 500, 3, "server_error")


def _context(*activity_ids: int) -> dict[str, Any]:
    return {
        "weekly_analysis": [
            {
                "week_start": "2026-08-10",
                "week_end": "2026-08-16",
                "derived_total_distance_km": 18.0,
                "derived_total_duration_min": 120.0,
                "derived_training_load": 180.0,
                "session_counts": {"total": len(activity_ids)},
                "sessions": [
                    {
                        "activity_id": activity_id,
                        "date": "2026-08-12",
                        "source_activity_type": "running",
                        "distance_km": 6.0,
                        "duration_min": 36.0,
                        "training_load": 60.0,
                        "avg_hr": 142,
                        "avg_pace": "6:00",
                        "segments": [],
                    }
                    for activity_id in activity_ids
                ],
            }
        ]
    }


def _write_context(tmp_path: Path, context: dict[str, Any]) -> Path:
    path = tmp_path / "coach_context.json"
    path.write_text(json.dumps(context), encoding="utf-8")
    return path


@dataclass
class _FakeSession:
    commits: int = 0

    def commit(self) -> None:
        self.commits += 1


@dataclass
class _FakeTransport:
    results: list[LineSendResult] = field(default_factory=lambda: [SUCCESS])
    messages: list[tuple[str, ...]] = field(default_factory=list)

    def send(self, _token: str, _group_id: str, messages: Sequence[str]) -> LineSendResult:
        self.messages.append(tuple(messages))
        return self.results.pop(0)


def _prepared_notification(
    activity_id: int,
    *,
    sent_at: datetime | None = None,
) -> LineNotification:
    return LineNotification(
        id=uuid.uuid4(),
        garmin_activity_id=activity_id,
        weekly_summary_id=None,
        ai_report_id=uuid.uuid4(),
        rendered_messages=[f"persisted activity {activity_id}", "🤖 AI 教練\n\n分析"],
        recorded_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
        sent_at=sent_at,
        is_seed=False,
    )


def _install_manual_persistence(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    session = _FakeSession()

    @contextmanager
    def session_factory() -> Iterator[_FakeSession]:
        yield session

    @contextmanager
    def lock_factory() -> Iterator[object]:
        yield object()

    monkeypatch.setattr(notifier, "_get_db_session", session_factory)
    monkeypatch.setattr(notifier, "_get_lock_connection", lock_factory)
    monkeypatch.setattr(notifier, "_acquire_advisory_lock", lambda _connection: True)
    monkeypatch.setattr(notifier, "_release_advisory_lock", lambda _connection: None)
    return session


def _run_manual(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, context: dict[str, Any]):
    path = _write_context(tmp_path, context)
    return patch.dict(
        os.environ,
        {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_GROUP_ID": "test-group",
        },
        clear=True,
    ), path


def test_first_run_seeds_history_without_ai_or_line_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_manual_persistence(monkeypatch)
    seeded: list[list[int]] = []
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: set())
    monkeypatch.setattr(
        notifier,
        "seed_baseline_notifications",
        lambda _session, activity_ids: seeded.append(activity_ids) or len(activity_ids),
    )
    monkeypatch.setattr(
        notifier,
        "ActivityAINotificationPreparer",
        lambda **_kwargs: pytest.fail("baseline must not invoke AI"),
    )
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda *_args: pytest.fail("baseline must not send LINE"),
    )

    env, path = _run_manual(tmp_path, monkeypatch, _context(101, 102))
    with env:
        result = run_line_notification(str(path))

    assert (result.status, result.sent, result.failed) == ("seeded", 0, 0)
    assert seeded == [[102, 101]]


def test_new_activity_prepares_ai_payload_outside_selection_lock_then_sends_canonical_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_manual_persistence(monkeypatch)
    events: list[str] = []
    prepared = PreparedLineDelivery(
        notification_id=uuid.uuid4(),
        ai_report_id=uuid.uuid4(),
        rendered_messages=("deterministic facts", "🤖 AI 教練\n\ncanonical analysis"),
        recorded_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
        already_sent=False,
    )
    persisted = _prepared_notification(123)
    persisted.id = prepared.notification_id
    persisted.ai_report_id = prepared.ai_report_id
    persisted.rendered_messages = list(prepared.rendered_messages)

    def acquire(_connection: object) -> bool:
        events.append("lock:acquire")
        return True

    def release(_connection: object) -> None:
        events.append("lock:release")

    class _Preparer:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def prepare(self, *, spec, garmin_activity_id: int) -> PreparedLineDelivery:
            events.append("prepare")
            assert garmin_activity_id == 123
            assert spec.report_scope == "activity"
            assert spec.input_json["activity"]["activity_id"] == 123
            assert spec.input_json["recent_training_weeks"][0]["derived_training_load"] == 180.0
            return prepared

    sent_messages: list[tuple[str, ...]] = []
    monkeypatch.setattr(notifier, "_acquire_advisory_lock", acquire)
    monkeypatch.setattr(notifier, "_release_advisory_lock", release)
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {-1})
    monkeypatch.setattr(notifier, "list_pending_activity_notifications", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        notifier,
        "get_activity_by_garmin_id",
        lambda _session, activity_id: Activity(
            id=uuid.uuid4(), user_id=uuid.uuid4(), garmin_activity_id=activity_id
        ),
    )
    monkeypatch.setattr(notifier, "ActivityAINotificationPreparer", _Preparer)
    monkeypatch.setattr(
        notifier,
        "get_prepared_activity_notification",
        lambda _session, _activity_id: persisted,
    )
    monkeypatch.setattr(notifier, "mark_notification_sent", lambda *_args: None)
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda _token, _group, messages: sent_messages.append(tuple(messages)) or SUCCESS,
    )

    env, path = _run_manual(tmp_path, monkeypatch, _context(123))
    with env:
        result = run_line_notification(str(path))

    assert (result.status, result.sent, result.failed) == ("done", 1, 0)
    assert sent_messages == [prepared.rendered_messages]
    assert events == [
        "lock:acquire",
        "lock:release",
        "prepare",
        "lock:acquire",
        "lock:release",
    ]


def test_pending_payload_retries_without_ai_or_renderer_even_after_context_ages_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_manual_persistence(monkeypatch)
    notification = _prepared_notification(456)
    first_transport = _FakeTransport(results=[LINE_FAILURE])
    second_transport = _FakeTransport(results=[SUCCESS])
    transports = [first_transport, second_transport]

    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {456})
    monkeypatch.setattr(
        notifier,
        "list_pending_activity_notifications",
        lambda *_args, **_kwargs: [notification],
    )
    monkeypatch.setattr(
        notifier,
        "get_prepared_activity_notification",
        lambda _session, _activity_id: notification,
    )
    monkeypatch.setattr(notifier, "mark_notification_sent", lambda *_args: None)
    monkeypatch.setattr(
        notifier,
        "ActivityAINotificationPreparer",
        lambda **_kwargs: pytest.fail("pending payload must not invoke AI"),
    )
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda *_args: transports.pop(0).send(*_args),
    )

    env, path = _run_manual(tmp_path, monkeypatch, _context())
    with env:
        first = run_line_notification(str(path))
    with env:
        second = run_line_notification(str(path))

    expected = tuple(notification.rendered_messages or [])
    assert (first.sent, first.failed) == (0, 1)
    assert (second.status, second.sent, second.failed) == ("done", 1, 0)
    assert first_transport.messages == [expected]
    assert second_transport.messages == [expected]


def test_ai_failure_defers_line_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_manual_persistence(monkeypatch)

    class _UnavailablePreparer:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def prepare(self, **_kwargs: Any) -> PreparedLineDelivery:
            raise ActivityCoachError("provider unavailable")

    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {-1})
    monkeypatch.setattr(notifier, "list_pending_activity_notifications", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        notifier,
        "get_activity_by_garmin_id",
        lambda _session, activity_id: Activity(
            id=uuid.uuid4(), user_id=uuid.uuid4(), garmin_activity_id=activity_id
        ),
    )
    monkeypatch.setattr(notifier, "ActivityAINotificationPreparer", _UnavailablePreparer)
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda *_args: pytest.fail("AI failure must defer LINE"),
    )

    env, path = _run_manual(tmp_path, monkeypatch, _context(789))
    with env:
        result = run_line_notification(str(path))

    assert (result.status, result.sent, result.failed) == ("ai_failed", 0, 1)


def test_unpersisted_activity_subject_defers_without_ai_or_line_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_manual_persistence(monkeypatch)
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {-1})
    monkeypatch.setattr(notifier, "list_pending_activity_notifications", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(notifier, "get_activity_by_garmin_id", lambda *_args: None)
    monkeypatch.setattr(
        notifier,
        "ActivityAINotificationPreparer",
        lambda **_kwargs: pytest.fail("unpersisted Activity must not invoke AI"),
    )
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda *_args: pytest.fail("unpersisted Activity must not send LINE"),
    )

    env, path = _run_manual(tmp_path, monkeypatch, _context(790))
    with env:
        result = run_line_notification(str(path))

    assert (result.status, result.sent, result.failed) == ("persistence_unavailable", 0, 1)


def test_daily_lookup_teardown_revocation_skips_ai_and_line_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activity = Activity(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        garmin_activity_id=791,
    )
    available = True
    session_count = 0

    @dataclass
    class _SubjectSession(_FakeSession):
        def get(self, model: type[Any], key: uuid.UUID) -> Activity | None:
            if model is Activity and key == activity.id:
                return activity
            return None

    @contextmanager
    def session_factory() -> Iterator[_SubjectSession]:
        nonlocal session_count
        session_count += 1
        yield _SubjectSession()
        if session_count == 4:
            revoke(OperationalError("SELECT", {}, ConnectionError("connection refused")))

    @contextmanager
    def lock_factory() -> Iterator[object]:
        yield object()

    def revoke(_error: BaseException) -> None:
        nonlocal available
        available = False

    database = NotificationDatabaseAccess(
        is_available=lambda: available,
        session=session_factory,
        lock_connection=lock_factory,
        revoke=revoke,
    )
    monkeypatch.setattr(notifier, "_acquire_advisory_lock", lambda _connection: True)
    monkeypatch.setattr(notifier, "_release_advisory_lock", lambda _connection: None)
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {-1})
    monkeypatch.setattr(notifier, "list_pending_activity_notifications", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(notifier, "get_activity_by_garmin_id", lambda *_args: activity)
    monkeypatch.setattr(
        resolution,
        "get_prepared_activity_notification",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        resolution,
        "get_ai_report_by_idempotency_key",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        notifier,
        "generate_activity_report",
        lambda *_args: pytest.fail("revoked persistence must skip Gemini"),
    )
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda *_args: pytest.fail("revoked persistence must skip LINE"),
    )

    path = _write_context(tmp_path, _context(791))
    with patch.dict(
        os.environ,
        {"LINE_CHANNEL_ACCESS_TOKEN": "test-token", "LINE_GROUP_ID": "test-group"},
        clear=True,
    ):
        result = run_daily_line_notification(str(path), database=database)

    assert (result.status, result.sent, result.failed) == ("persistence_unavailable", 0, 1)
    assert session_count == 4


def test_daily_database_unavailable_defers_without_stateless_line_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_context(tmp_path, _context(123))
    database = NotificationDatabaseAccess(
        is_available=lambda: False,
        session=lambda: pytest.fail("unavailable DB must not open session"),
        lock_connection=lambda: pytest.fail("unavailable DB must not acquire lock"),
        revoke=lambda _error: None,
    )
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda *_args: pytest.fail("unavailable DB must not send LINE statelessly"),
    )

    with patch.dict(
        os.environ,
        {"LINE_CHANNEL_ACCESS_TOKEN": "test-token", "LINE_GROUP_ID": "test-group"},
        clear=True,
    ):
        result = run_daily_line_notification(str(path), database=database)

    assert (result.status, result.sent, result.failed) == ("persistence_unavailable", 0, 1)


def test_manual_database_connection_loss_defers_without_line_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def lock_factory() -> Iterator[object]:
        yield object()

    @contextmanager
    def unavailable_session() -> Iterator[object]:
        raise OperationalError("SELECT 1", {}, ConnectionError("connection refused"))
        yield object()

    monkeypatch.setattr(notifier, "_get_lock_connection", lock_factory)
    monkeypatch.setattr(notifier, "_get_db_session", unavailable_session)
    monkeypatch.setattr(notifier, "_acquire_advisory_lock", lambda _connection: True)
    monkeypatch.setattr(notifier, "_release_advisory_lock", lambda _connection: None)
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda *_args: pytest.fail("connection loss must not send LINE statelessly"),
    )

    env, path = _run_manual(tmp_path, monkeypatch, _context(123))
    with env:
        result = run_line_notification(str(path))

    assert (result.status, result.sent, result.failed) == ("persistence_unavailable", 0, 1)


def test_line_acknowledgement_persistence_failure_never_falls_back_to_stateless_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _install_manual_persistence(monkeypatch)
    notification = _prepared_notification(901)

    def failed_commit() -> None:
        raise OperationalError("COMMIT", {}, ConnectionError("connection refused"))

    monkeypatch.setattr(session, "commit", failed_commit)
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {901})
    monkeypatch.setattr(
        notifier,
        "list_pending_activity_notifications",
        lambda *_args, **_kwargs: [notification],
    )
    monkeypatch.setattr(
        notifier,
        "get_prepared_activity_notification",
        lambda _session, _activity_id: notification,
    )
    monkeypatch.setattr(notifier, "mark_notification_sent", lambda *_args: None)
    sent_messages: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda _token, _group, messages: sent_messages.append(tuple(messages)) or SUCCESS,
    )

    env, path = _run_manual(tmp_path, monkeypatch, _context())
    with env:
        result = run_line_notification(str(path))

    assert (result.status, result.sent, result.failed) == ("persistence_unavailable", 1, 1)
    assert sent_messages == [tuple(notification.rendered_messages or [])]


def test_daily_unlock_connection_loss_stops_later_delivery_and_preserves_completed_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    notification = _prepared_notification(903)
    deferred_notification = _prepared_notification(904)
    available = True
    release_calls = 0
    revoked: list[BaseException] = []

    @contextmanager
    def session_factory() -> Iterator[_FakeSession]:
        yield session

    @contextmanager
    def lock_factory() -> Iterator[object]:
        yield object()

    def release(_connection: object) -> None:
        nonlocal release_calls
        release_calls += 1
        if release_calls == 2:
            raise OperationalError("UNLOCK", {}, ConnectionError("connection refused"))

    def revoke(error: BaseException) -> None:
        nonlocal available
        available = False
        revoked.append(error)

    database = NotificationDatabaseAccess(
        is_available=lambda: available,
        session=session_factory,
        lock_connection=lock_factory,
        revoke=revoke,
    )
    monkeypatch.setattr(notifier, "_acquire_advisory_lock", lambda _connection: True)
    monkeypatch.setattr(notifier, "_release_advisory_lock", release)
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {903})
    monkeypatch.setattr(
        notifier,
        "list_pending_activity_notifications",
        lambda *_args, **_kwargs: [notification, deferred_notification],
    )
    monkeypatch.setattr(
        notifier,
        "get_prepared_activity_notification",
        lambda _session, activity_id: {
            903: notification,
            904: deferred_notification,
        }[activity_id],
    )
    monkeypatch.setattr(notifier, "mark_notification_sent", lambda *_args: None)
    sent_messages: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda _token, _group, messages: sent_messages.append(tuple(messages)) or SUCCESS,
    )

    path = _write_context(tmp_path, _context())
    with patch.dict(
        os.environ,
        {"LINE_CHANNEL_ACCESS_TOKEN": "test-token", "LINE_GROUP_ID": "test-group"},
        clear=True,
    ):
        result = run_daily_line_notification(str(path), database=database)

    assert (result.status, result.sent, result.failed) == ("persistence_unavailable", 1, 0)
    assert release_calls == 2
    assert len(revoked) == 1
    assert sent_messages == [tuple(notification.rendered_messages or [])]


def test_daily_selection_unlock_loss_defers_without_ai_or_line_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    available = True
    release_calls = 0

    @contextmanager
    def session_factory() -> Iterator[_FakeSession]:
        yield session

    @contextmanager
    def lock_factory() -> Iterator[object]:
        yield object()

    def release(_connection: object) -> None:
        nonlocal release_calls
        release_calls += 1
        raise OperationalError("UNLOCK", {}, ConnectionError("connection refused"))

    def revoke(_error: BaseException) -> None:
        nonlocal available
        available = False

    database = NotificationDatabaseAccess(
        is_available=lambda: available,
        session=session_factory,
        lock_connection=lock_factory,
        revoke=revoke,
    )
    monkeypatch.setattr(notifier, "_acquire_advisory_lock", lambda _connection: True)
    monkeypatch.setattr(notifier, "_release_advisory_lock", release)
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {-1})
    monkeypatch.setattr(notifier, "list_pending_activity_notifications", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        notifier,
        "ActivityAINotificationPreparer",
        lambda **_kwargs: pytest.fail("unlock loss must not invoke AI"),
    )
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda *_args: pytest.fail("unlock loss must not send LINE"),
    )

    path = _write_context(tmp_path, _context(905))
    with patch.dict(
        os.environ,
        {"LINE_CHANNEL_ACCESS_TOKEN": "test-token", "LINE_GROUP_ID": "test-group"},
        clear=True,
    ):
        result = run_daily_line_notification(str(path), database=database)

    assert (result.status, result.sent, result.failed) == ("persistence_unavailable", 0, 1)
    assert release_calls == 1


def test_daily_acknowledgement_connection_loss_skips_unlock_after_neon_revoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notification = _prepared_notification(904)
    available = True
    release_calls = 0

    @dataclass
    class _FailingSession(_FakeSession):
        def commit(self) -> None:
            raise OperationalError("COMMIT", {}, ConnectionError("connection refused"))

    session = _FailingSession()

    @contextmanager
    def session_factory() -> Iterator[_FailingSession]:
        yield session

    @contextmanager
    def lock_factory() -> Iterator[object]:
        yield object()

    def release(_connection: object) -> None:
        nonlocal release_calls
        release_calls += 1

    def revoke(_error: BaseException) -> None:
        nonlocal available
        available = False

    database = NotificationDatabaseAccess(
        is_available=lambda: available,
        session=session_factory,
        lock_connection=lock_factory,
        revoke=revoke,
    )
    monkeypatch.setattr(notifier, "_acquire_advisory_lock", lambda _connection: True)
    monkeypatch.setattr(notifier, "_release_advisory_lock", release)
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {904})
    monkeypatch.setattr(
        notifier,
        "list_pending_activity_notifications",
        lambda *_args, **_kwargs: [notification],
    )
    monkeypatch.setattr(
        notifier,
        "get_prepared_activity_notification",
        lambda _session, _activity_id: notification,
    )
    monkeypatch.setattr(notifier, "mark_notification_sent", lambda *_args: None)
    monkeypatch.setattr(notifier, "send_push_messages", lambda *_args: SUCCESS)

    path = _write_context(tmp_path, _context())
    with patch.dict(
        os.environ,
        {"LINE_CHANNEL_ACCESS_TOKEN": "test-token", "LINE_GROUP_ID": "test-group"},
        clear=True,
    ):
        result = run_daily_line_notification(str(path), database=database)

    assert (result.status, result.sent, result.failed) == ("persistence_unavailable", 1, 1)
    assert release_calls == 1


def test_manual_unlock_connection_loss_preserves_completed_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_manual_persistence(monkeypatch)
    notification = _prepared_notification(905)
    release_calls = 0

    def release(_connection: object) -> None:
        nonlocal release_calls
        release_calls += 1
        if release_calls == 2:
            raise OperationalError("UNLOCK", {}, ConnectionError("connection refused"))

    monkeypatch.setattr(notifier, "_release_advisory_lock", release)
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {905})
    monkeypatch.setattr(
        notifier,
        "list_pending_activity_notifications",
        lambda *_args, **_kwargs: [notification] if notification.sent_at is None else [],
    )
    monkeypatch.setattr(
        notifier,
        "get_prepared_activity_notification",
        lambda _session, _activity_id: notification,
    )

    def mark_sent(_session: _FakeSession, _notification_id: uuid.UUID) -> None:
        notification.sent_at = datetime.now(timezone.utc)

    sent_messages: list[tuple[str, ...]] = []
    monkeypatch.setattr(notifier, "mark_notification_sent", mark_sent)
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda _token, _group, messages: sent_messages.append(tuple(messages)) or SUCCESS,
    )

    env, path = _run_manual(tmp_path, monkeypatch, _context())
    with env:
        first = run_line_notification(str(path))
    with env:
        second = run_line_notification(str(path))

    assert (first.status, first.sent, first.failed) == ("done", 1, 0)
    assert (second.status, second.sent, second.failed) == ("no_new", 0, 0)
    assert release_calls == 3
    assert sent_messages == [tuple(notification.rendered_messages or [])]


def test_manual_nonconnection_unlock_error_propagates_after_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_manual_persistence(monkeypatch)
    notification = _prepared_notification(906)
    release_calls = 0

    def release(_connection: object) -> None:
        nonlocal release_calls
        release_calls += 1
        if release_calls == 2:
            raise IntegrityError("UNLOCK", {}, Exception("constraint failed"))

    monkeypatch.setattr(notifier, "_release_advisory_lock", release)
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {906})
    monkeypatch.setattr(
        notifier,
        "list_pending_activity_notifications",
        lambda *_args, **_kwargs: [notification],
    )
    monkeypatch.setattr(
        notifier,
        "get_prepared_activity_notification",
        lambda _session, _activity_id: notification,
    )
    monkeypatch.setattr(notifier, "mark_notification_sent", lambda *_args: None)
    monkeypatch.setattr(notifier, "send_push_messages", lambda *_args: SUCCESS)

    env, path = _run_manual(tmp_path, monkeypatch, _context())
    with env, pytest.raises(IntegrityError):
        run_line_notification(str(path))


def test_nonconnection_acknowledgement_error_propagates_after_line_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _install_manual_persistence(monkeypatch)
    notification = _prepared_notification(902)

    def failed_commit() -> None:
        raise IntegrityError("COMMIT", {}, Exception("constraint failed"))

    monkeypatch.setattr(session, "commit", failed_commit)
    monkeypatch.setattr(notifier, "get_notified_activity_ids", lambda _session: {902})
    monkeypatch.setattr(
        notifier,
        "list_pending_activity_notifications",
        lambda *_args, **_kwargs: [notification],
    )
    monkeypatch.setattr(
        notifier,
        "get_prepared_activity_notification",
        lambda _session, _activity_id: notification,
    )
    monkeypatch.setattr(notifier, "mark_notification_sent", lambda *_args: None)
    monkeypatch.setattr(notifier, "send_push_messages", lambda *_args: SUCCESS)

    env, path = _run_manual(tmp_path, monkeypatch, _context())
    with env, pytest.raises(IntegrityError):
        run_line_notification(str(path))
