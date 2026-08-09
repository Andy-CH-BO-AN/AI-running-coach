from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

import src.notifications.notifier as notifier
from src.notifications.line_client import LineSendResult
from src.notifications.notifier import (
    NotificationDatabaseAccess,
    _ActivityDeliveryState,
    _NotificationProfile,
    _NotificationRun,
)


SUCCESS = LineSendResult(True, 200, 1, None)
LINE_FAILURE = LineSendResult(False, 500, 3, "server_error")


def _connection_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, ConnectionError("connection refused"))


def _activity(activity_id: int, activity_date: date) -> dict[str, Any]:
    return {
        "activity_id": activity_id,
        "date": activity_date.isoformat(),
        "type": "easy",
        "source_activity_type": "running",
        "distance_km": 5.0,
        "duration_min": 30.0,
        "training_load": 50.0,
        "avg_hr": 140,
        "avg_pace": "6:00",
        "segments": [],
        "environment": {},
        "data_quality": {"status": "complete", "missing_fields": []},
    }


def _context(*weeks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "weekly_analysis": [
            {
                "week_label": f"Week {index}",
                "week_start": "2026-07-01",
                "week_end": "2026-07-07",
                "derived_training_load": 100.0,
                "sessions": sessions,
            }
            for index, sessions in enumerate(weeks)
        ]
    }


@dataclass
class _FakeTransport:
    failures: set[int] = field(default_factory=set)
    sent_activity_ids: list[int] = field(default_factory=list)
    calls: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)

    def send(
        self,
        token: str,
        group_id: str,
        messages: Sequence[str],
    ) -> LineSendResult:
        rendered = "\n".join(messages)
        match = re.search(r"/activity/(\d+)", rendered)
        assert match is not None, "formatter output must retain Activity identity"
        activity_id = int(match.group(1))
        self.sent_activity_ids.append(activity_id)
        self.calls.append((token, group_id, tuple(messages)))
        return LINE_FAILURE if activity_id in self.failures else SUCCESS


@dataclass
class _FakeSession:
    rollback_calls: int = 0

    def rollback(self) -> None:
        self.rollback_calls += 1


@dataclass
class _FakeDatabase:
    available: bool = True
    lock_error: SQLAlchemyError | None = None
    session_error: SQLAlchemyError | None = None
    revocations: list[SQLAlchemyError] = field(default_factory=list)
    session_entries: int = 0
    lock_entries: int = 0
    session_object: _FakeSession = field(default_factory=_FakeSession)
    lock_object: object = field(default_factory=object)

    @contextmanager
    def session(self) -> Iterator[_FakeSession]:
        self.session_entries += 1
        try:
            if self.session_error is not None:
                raise self.session_error
            yield self.session_object
        except SQLAlchemyError as exc:
            if notifier.is_database_connection_error(exc):
                self.revoke(exc)
            raise

    @contextmanager
    def lock_connection(self) -> Iterator[object]:
        self.lock_entries += 1
        try:
            if self.lock_error is not None:
                raise self.lock_error
            yield self.lock_object
        except SQLAlchemyError as exc:
            if notifier.is_database_connection_error(exc):
                self.revoke(exc)
            raise

    def revoke(self, error: BaseException) -> None:
        assert isinstance(error, SQLAlchemyError)
        if self.available:
            self.available = False
            self.revocations.append(error)

    def access(self) -> NotificationDatabaseAccess:
        return NotificationDatabaseAccess(
            is_available=lambda: self.available,
            session=self.session,
            lock_connection=self.lock_connection,
            revoke=self.revoke,
        )


@dataclass
class _PersistenceProbe:
    notified_ids: set[int] = field(default_factory=lambda: {-1})
    recorded_ids: list[int] = field(default_factory=list)
    seeded_ids: list[list[int]] = field(default_factory=list)
    acquire: bool = True
    acquire_error: SQLAlchemyError | None = None
    load_error: SQLAlchemyError | None = None
    seed_error: SQLAlchemyError | None = None
    record_error: SQLAlchemyError | None = None
    release_error: SQLAlchemyError | None = None
    release_calls: int = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def acquire(_connection: object) -> bool:
            if self.acquire_error is not None:
                raise self.acquire_error
            return self.acquire

        def release(_connection: object) -> None:
            self.release_calls += 1
            if self.release_error is not None:
                raise self.release_error

        def load(_session: object) -> set[int]:
            if self.load_error is not None:
                raise self.load_error
            return set(self.notified_ids)

        def seed(_session: object, activity_ids: list[int]) -> int:
            if self.seed_error is not None:
                raise self.seed_error
            self.seeded_ids.append(list(activity_ids))
            return len(activity_ids)

        def record(_session: object, activity_id: int) -> bool:
            if self.record_error is not None:
                raise self.record_error
            self.recorded_ids.append(activity_id)
            return True

        monkeypatch.setattr(notifier, "_acquire_advisory_lock", acquire)
        monkeypatch.setattr(notifier, "_release_advisory_lock", release)
        monkeypatch.setattr(notifier, "get_notified_activity_ids", load)
        monkeypatch.setattr(notifier, "seed_baseline_notifications", seed)
        monkeypatch.setattr(notifier, "record_notification", record)


def _execute(
    monkeypatch: pytest.MonkeyPatch,
    *,
    context: dict[str, Any],
    profile: _NotificationProfile,
    transport: _FakeTransport,
    probe: _PersistenceProbe,
    database: _FakeDatabase | None = None,
):
    probe.install(monkeypatch)
    database = database or _FakeDatabase()

    if profile is _NotificationProfile.MANUAL:
        monkeypatch.setattr(notifier, "_get_db_session", database.session)
        monkeypatch.setattr(notifier, "_get_lock_connection", database.lock_connection)
        access = None
    else:
        access = database.access()

    result = _NotificationRun(
        context=context,
        token="test-token",
        group_id="test-group",
        profile=profile,
        database=access,
        transport=transport,
    ).execute()
    return result, database


@pytest.mark.parametrize(
    "profile",
    [_NotificationProfile.MANUAL, _NotificationProfile.DAILY],
)
def test_persistent_profiles_share_newest_first_dedup_and_twenty_cap(
    monkeypatch: pytest.MonkeyPatch,
    profile: _NotificationProfile,
) -> None:
    start = date(2026, 7, 1)
    activities = [_activity(activity_id, start + timedelta(days=activity_id)) for activity_id in range(1, 23)]
    # Same Activity can appear in overlapping weeks; it still owns one lifecycle.
    context = _context(activities[:11] + [_activity(22, start + timedelta(days=22))], activities[11:])
    transport = _FakeTransport()
    probe = _PersistenceProbe()

    result, _database = _execute(
        monkeypatch,
        context=context,
        profile=profile,
        transport=transport,
        probe=probe,
    )

    assert result.status == "done"
    assert (result.sent, result.failed) == (20, 0)
    assert transport.sent_activity_ids == list(range(22, 2, -1))
    assert probe.recorded_ids == transport.sent_activity_ids


def test_daily_unavailable_is_newest_first_and_capped_at_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = date(2026, 7, 1)
    context = _context([_activity(activity_id, start + timedelta(days=activity_id)) for activity_id in range(1, 6)])
    transport = _FakeTransport()
    probe = _PersistenceProbe()
    database = _FakeDatabase(available=False)

    result, database = _execute(
        monkeypatch,
        context=context,
        profile=_NotificationProfile.DAILY,
        transport=transport,
        probe=probe,
        database=database,
    )

    assert result.status == "stateless_done"
    assert (result.sent, result.failed) == (3, 0)
    assert transport.sent_activity_ids == [5, 4, 3]
    assert database.lock_entries == 0
    assert database.session_entries == 0
    assert probe.recorded_ids == []


def test_seed_no_new_and_lock_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context([_activity(10, date(2026, 7, 10))])

    seed_probe = _PersistenceProbe(notified_ids=set())
    seed_transport = _FakeTransport()
    seeded, _database = _execute(
        monkeypatch,
        context=context,
        profile=_NotificationProfile.DAILY,
        transport=seed_transport,
        probe=seed_probe,
    )
    assert seeded.status == "seeded"
    assert seed_probe.seeded_ids == [[10]]
    assert seed_transport.sent_activity_ids == []

    no_new_probe = _PersistenceProbe(notified_ids={-1, 10})
    no_new_transport = _FakeTransport()
    no_new, _database = _execute(
        monkeypatch,
        context=context,
        profile=_NotificationProfile.DAILY,
        transport=no_new_transport,
        probe=no_new_probe,
    )
    assert no_new.status == "no_new"
    assert no_new_transport.sent_activity_ids == []

    locked_probe = _PersistenceProbe(acquire=False)
    locked_transport = _FakeTransport()
    locked, locked_database = _execute(
        monkeypatch,
        context=context,
        profile=_NotificationProfile.DAILY,
        transport=locked_transport,
        probe=locked_probe,
    )
    assert locked.status == "skipped_locked"
    assert locked_transport.sent_activity_ids == []
    assert locked_database.session_entries == 0
    assert locked_probe.release_calls == 0


def test_line_failure_continues_and_records_only_accepted_activities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(
        [
            _activity(1, date(2026, 7, 1)),
            _activity(2, date(2026, 7, 2)),
            _activity(3, date(2026, 7, 3)),
        ]
    )
    transport = _FakeTransport(failures={3})
    probe = _PersistenceProbe()

    result, _database = _execute(
        monkeypatch,
        context=context,
        profile=_NotificationProfile.DAILY,
        transport=transport,
        probe=probe,
    )

    assert result.status == "done"
    assert (result.sent, result.failed) == (2, 1)
    assert transport.sent_activity_ids == [3, 2, 1]
    assert probe.recorded_ids == [2, 1]


@pytest.mark.parametrize(
    ("profile", "expected_status", "expected_ids", "expected_counts"),
    [
        (_NotificationProfile.MANUAL, "done", [4], (0, 1)),
        (_NotificationProfile.DAILY, "persistence_loss_done", [4, 3, 2], (3, 0)),
    ],
)
def test_sent_unrecorded_has_profile_specific_stop_and_count_semantics(
    monkeypatch: pytest.MonkeyPatch,
    profile: _NotificationProfile,
    expected_status: str,
    expected_ids: list[int],
    expected_counts: tuple[int, int],
) -> None:
    context = _context([_activity(activity_id, date(2026, 7, activity_id)) for activity_id in range(1, 5)])
    transport = _FakeTransport()
    probe = _PersistenceProbe(record_error=_connection_error())

    result, database = _execute(
        monkeypatch,
        context=context,
        profile=profile,
        transport=transport,
        probe=probe,
    )

    assert result.status == expected_status
    assert (result.sent, result.failed) == expected_counts
    assert transport.sent_activity_ids == expected_ids
    assert len(set(transport.sent_activity_ids)) == len(transport.sent_activity_ids)
    assert probe.recorded_ids == []
    if profile is _NotificationProfile.MANUAL:
        assert database.session_object.rollback_calls == 1
        assert database.revocations == []
    else:
        assert len(database.revocations) == 1
        assert database.session_object.rollback_calls == 0


@pytest.mark.parametrize("phase", ["lock", "acquire", "session", "load", "seed"])
def test_daily_connection_loss_phase_matrix_enters_stateless_once(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    context = _context([_activity(activity_id, date(2026, 7, activity_id)) for activity_id in range(1, 5)])
    probe = _PersistenceProbe(notified_ids=set() if phase == "seed" else {-1})
    database = _FakeDatabase()
    if phase == "lock":
        database.lock_error = _connection_error()
    elif phase == "acquire":
        probe.acquire_error = _connection_error()
    elif phase == "session":
        database.session_error = _connection_error()
    elif phase == "load":
        probe.load_error = _connection_error()
    else:
        probe.seed_error = _connection_error()

    transport = _FakeTransport()
    result, database = _execute(
        monkeypatch,
        context=context,
        profile=_NotificationProfile.DAILY,
        transport=transport,
        probe=probe,
        database=database,
    )

    assert result.status == "persistence_loss_done"
    assert (result.sent, result.failed) == (3, 0)
    assert transport.sent_activity_ids == [4, 3, 2]
    assert len(database.revocations) == 1
    assert probe.release_calls == 0


def test_daily_failed_send_and_sent_unrecorded_are_not_retried_stateless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(
        [_activity(activity_id, date(2026, 7, activity_id)) for activity_id in range(1, 6)]
    )
    transport = _FakeTransport(failures={5})
    probe = _PersistenceProbe(record_error=_connection_error())

    result, database = _execute(
        monkeypatch,
        context=context,
        profile=_NotificationProfile.DAILY,
        transport=transport,
        probe=probe,
    )

    assert result.status == "persistence_loss_done"
    assert (result.sent, result.failed) == (3, 1)
    assert transport.sent_activity_ids == [5, 4, 3, 2]
    assert len(set(transport.sent_activity_ids)) == 4
    assert len(database.revocations) == 1


def test_daily_unlock_loss_revokes_without_resend_or_status_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeTransport()
    probe = _PersistenceProbe(release_error=_connection_error())

    result, database = _execute(
        monkeypatch,
        context=_context([_activity(9, date(2026, 7, 9))]),
        profile=_NotificationProfile.DAILY,
        transport=transport,
        probe=probe,
    )

    assert result.status == "done"
    assert (result.sent, result.failed) == (1, 0)
    assert transport.sent_activity_ids == [9]
    assert probe.recorded_ids == [9]
    assert len(database.revocations) == 1
    assert probe.release_calls == 1


def test_nontransient_db_and_formatter_errors_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context([_activity(7, date(2026, 7, 7))])

    integrity_probe = _PersistenceProbe(
        record_error=IntegrityError("INSERT", {}, Exception("constraint failed"))
    )
    integrity_database = _FakeDatabase()
    with pytest.raises(IntegrityError):
        _execute(
            monkeypatch,
            context=context,
            profile=_NotificationProfile.DAILY,
            transport=_FakeTransport(),
            probe=integrity_probe,
            database=integrity_database,
        )
    assert integrity_database.revocations == []

    formatter_probe = _PersistenceProbe()
    formatter_database = _FakeDatabase()
    monkeypatch.setattr(
        notifier,
        "format_activity_messages",
        lambda _activity, _week: (_ for _ in ()).throw(ValueError("bad formatter")),
    )
    with pytest.raises(ValueError, match="bad formatter"):
        _execute(
            monkeypatch,
            context=context,
            profile=_NotificationProfile.DAILY,
            transport=_FakeTransport(),
            probe=formatter_probe,
            database=formatter_database,
        )
    assert formatter_database.revocations == []


def test_transport_program_error_propagates_without_revoking_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context([_activity(7, date(2026, 7, 7))])
    probe = _PersistenceProbe()
    database = _FakeDatabase()
    transport = MagicMock()
    transport.send.side_effect = RuntimeError("transport programming error")

    with pytest.raises(RuntimeError, match="transport programming error"):
        _execute(
            monkeypatch,
            context=context,
            profile=_NotificationProfile.DAILY,
            transport=transport,
            probe=probe,
            database=database,
        )

    assert database.revocations == []


def test_delivery_outcome_state_is_terminal_and_delivery_runs_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = notifier._ActivityCandidate(
        _activity(8, date(2026, 7, 8)),
        {"derived_training_load": 100.0},
    )
    delivery = notifier._ActivityDelivery(
        candidate=candidate,
        token="test-token",
        group_id="test-group",
        transport=_FakeTransport(),
    )
    monkeypatch.setattr(notifier, "record_notification", lambda _session, _activity_id: True)

    outcome = delivery.run(_FakeSession())

    assert isinstance(outcome, notifier._ActivityDeliveryOutcome)
    assert outcome.state is _ActivityDeliveryState.RECORDED
    assert delivery.state is _ActivityDeliveryState.RECORDED
    assert outcome.send_result is SUCCESS
    with pytest.raises(RuntimeError, match="only run once"):
        delivery.run(_FakeSession())


def test_production_transport_partial_batch_failure_never_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = notifier._ActivityCandidate(
        _activity(8, date(2026, 7, 8)),
        {"derived_training_load": 100.0},
    )
    pages = [f"page {index}" for index in range(6)]
    monkeypatch.setattr(notifier, "format_activity_messages", lambda _activity, _week: pages)

    accepted = MagicMock(status_code=200, headers={})
    rejected = MagicMock(status_code=400, headers={})
    http = MagicMock()
    http.__enter__.return_value = http
    http.__exit__.return_value = False
    http.post.side_effect = [accepted, rejected]
    monkeypatch.setattr("src.notifications.line_client.requests.Session", lambda: http)

    recorded: list[int] = []
    monkeypatch.setattr(
        notifier,
        "record_notification",
        lambda _session, activity_id: recorded.append(activity_id),
    )
    delivery = notifier._ActivityDelivery(
        candidate=candidate,
        token="test-token",
        group_id="test-group",
        transport=notifier._ProductionLineTransport(),
    )

    outcome = delivery.run(_FakeSession())

    assert outcome.state is _ActivityDeliveryState.LINE_FAILED
    assert recorded == []
    assert http.post.call_count == 2
    assert len(http.post.call_args_list[0].kwargs["json"]["messages"]) == 5
    assert len(http.post.call_args_list[1].kwargs["json"]["messages"]) == 1
    retry_keys = [
        call.kwargs["headers"]["X-Line-Retry-Key"]
        for call in http.post.call_args_list
    ]
    assert retry_keys[0] != retry_keys[1]


@pytest.mark.parametrize("daily", [False, True])
def test_public_wrappers_disable_before_loading_context_or_transport(
    monkeypatch: pytest.MonkeyPatch,
    daily: bool,
) -> None:
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_GROUP_ID", raising=False)
    monkeypatch.setattr(
        notifier,
        "_load_coach_context",
        lambda _path: (_ for _ in ()).throw(AssertionError("context loaded")),
    )
    monkeypatch.setattr(
        notifier,
        "send_push_messages",
        lambda *_args: (_ for _ in ()).throw(AssertionError("transport called")),
    )

    if daily:
        result = notifier.run_daily_line_notification("missing.json", database=None)
    else:
        result = notifier.run_line_notification("missing.json")

    assert result == notifier.NotificationResult(status="disabled")


def test_internal_lifecycle_repr_hides_credentials_and_persistence_details() -> None:
    marker_token = "token-must-not-leak"
    marker_group = "group-must-not-leak"
    marker_database_error = "database-secret-must-not-leak"
    candidate = notifier._ActivityCandidate(
        _activity(8, date(2026, 7, 8)),
        {"derived_training_load": 100.0},
    )
    transport = _FakeTransport()
    delivery = notifier._ActivityDelivery(
        candidate=candidate,
        token=marker_token,
        group_id=marker_group,
        transport=transport,
    )
    run = _NotificationRun(
        context=_context([candidate.activity]),
        token=marker_token,
        group_id=marker_group,
        profile=_NotificationProfile.DAILY,
        database=None,
        transport=transport,
    )
    outcome = notifier._ActivityDeliveryOutcome(
        _ActivityDeliveryState.SENT_UNRECORDED,
        SUCCESS,
        OperationalError("INSERT", {}, ConnectionError(marker_database_error)),
    )

    combined = " ".join((repr(delivery), repr(run), repr(outcome)))
    assert marker_token not in combined
    assert marker_group not in combined
    assert marker_database_error not in combined
