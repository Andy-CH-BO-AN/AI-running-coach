from __future__ import annotations

import secrets
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import src.notifications.notifier as notifier
from src.db.models import LineNotification
from src.db.repositories import SYSTEM_INITIALIZED_MARKER_ID, get_notified_activity_ids
from src.notifications.line_client import LineSendResult
from src.notifications.notifier import (
    NotificationDatabaseAccess,
    _NotificationProfile,
    _NotificationRun,
)
from tests.db_test_utils import isolated_db_session


ACTIVITY_MARKER_PREFIX = "activity-marker:"


@pytest.fixture()
def db_session() -> Iterator[Session]:
    yield from isolated_db_session()


def _activity(activity_id: int, activity_date: str) -> dict[str, Any]:
    return {
        "activity_id": activity_id,
        "date": activity_date,
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


def _context(*activities: dict[str, Any]) -> dict[str, Any]:
    return {
        "weekly_analysis": [
            {
                "week_label": "Week 1",
                "week_start": "2026-07-01",
                "week_end": "2026-07-07",
                "derived_training_load": 100.0,
                "sessions": list(activities),
            }
        ]
    }


@dataclass
class _FakeTransport:
    sent_activity_ids: list[int] = field(default_factory=list)

    def send(
        self,
        _token: str,
        _group_id: str,
        messages: Sequence[str],
    ) -> LineSendResult:
        markers = [
            message.removeprefix(ACTIVITY_MARKER_PREFIX)
            for message in messages
            if message.startswith(ACTIVITY_MARKER_PREFIX)
        ]
        assert len(markers) == 1
        self.sent_activity_ids.append(int(markers[0]))
        return LineSendResult(True, 200, 1, None)


def _database_access(db_session: Session) -> NotificationDatabaseAccess:
    state = {"available": True}

    @contextmanager
    def session_context() -> Iterator[Session]:
        yield db_session

    @contextmanager
    def lock_context() -> Iterator[Any]:
        bind = db_session.get_bind()
        with bind.engine.connect() as connection:
            yield connection

    def revoke(_error: BaseException) -> None:
        state["available"] = False

    return NotificationDatabaseAccess(
        is_available=lambda: state["available"],
        session=session_context,
        lock_connection=lock_context,
        revoke=revoke,
    )


def _execute(
    context: dict[str, Any],
    *,
    database: NotificationDatabaseAccess,
    transport: _FakeTransport,
):
    return _NotificationRun(
        context=context,
        token="test-token",
        group_id="test-group",
        profile=_NotificationProfile.DAILY,
        database=database,
        transport=transport,
    ).execute()


def _install_activity_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        notifier,
        "format_activity_messages",
        lambda activity, _week: [
            f"{ACTIVITY_MARKER_PREFIX}{activity['activity_id']}"
        ],
    )


def test_real_seed_dedup_and_record_roundtrip(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Random key keeps concurrent local/CI test runs from sharing an advisory lock.
    monkeypatch.setattr(notifier, "LINE_NOTIFICATION_LOCK_KEY", secrets.randbelow(2**62) + 1)
    _install_activity_marker(monkeypatch)
    database = _database_access(db_session)
    transport = _FakeTransport()
    baseline = _context(
        _activity(101, "2026-07-01"),
        _activity(102, "2026-07-02"),
    )

    seeded = _execute(baseline, database=database, transport=transport)

    assert seeded.status == "seeded"
    assert transport.sent_activity_ids == []
    baseline_rows = db_session.scalars(
        select(LineNotification).where(
            LineNotification.garmin_activity_id.in_([101, 102])
        )
    ).all()
    assert {row.garmin_activity_id for row in baseline_rows} == {101, 102}
    assert all(row.is_seed for row in baseline_rows)
    assert {
        SYSTEM_INITIALIZED_MARKER_ID,
        101,
        102,
    }.issubset(get_notified_activity_ids(db_session))

    with_new_activity = _context(
        _activity(101, "2026-07-01"),
        _activity(102, "2026-07-02"),
        _activity(103, "2026-07-03"),
    )
    delivered = _execute(with_new_activity, database=database, transport=transport)
    rerun = _execute(with_new_activity, database=database, transport=transport)

    assert (delivered.status, delivered.sent, delivered.failed) == ("done", 1, 0)
    assert rerun.status == "no_new"
    assert transport.sent_activity_ids == [103]
    assert {
        SYSTEM_INITIALIZED_MARKER_ID,
        101,
        102,
        103,
    }.issubset(get_notified_activity_ids(db_session))
    notification = db_session.scalar(
        select(LineNotification).where(LineNotification.garmin_activity_id == 103)
    )
    assert notification is not None
    assert notification.is_seed is False


def test_real_empty_baseline_then_first_activity_sends_once(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifier, "LINE_NOTIFICATION_LOCK_KEY", secrets.randbelow(2**62) + 1)
    _install_activity_marker(monkeypatch)
    database = _database_access(db_session)
    transport = _FakeTransport()

    initialized = _execute(
        _context(),
        database=database,
        transport=transport,
    )

    assert initialized.status == "seeded"
    assert transport.sent_activity_ids == []
    marker = db_session.scalar(
        select(LineNotification).where(
            LineNotification.garmin_activity_id == SYSTEM_INITIALIZED_MARKER_ID
        )
    )
    assert marker is not None
    assert marker.is_seed is True

    with_first_activity = _context(_activity(201, "2026-07-04"))
    delivered = _execute(
        with_first_activity,
        database=database,
        transport=transport,
    )
    rerun = _execute(
        with_first_activity,
        database=database,
        transport=transport,
    )

    assert (delivered.status, delivered.sent, delivered.failed) == ("done", 1, 0)
    assert rerun.status == "no_new"
    assert transport.sent_activity_ids == [201]
    notification = db_session.scalar(
        select(LineNotification).where(LineNotification.garmin_activity_id == 201)
    )
    assert notification is not None
    assert notification.is_seed is False
