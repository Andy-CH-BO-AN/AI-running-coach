from __future__ import annotations

import re
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
        match = re.search(r"/activity/(\d+)", "\n".join(messages))
        assert match is not None
        self.sent_activity_ids.append(int(match.group(1)))
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


def test_real_seed_dedup_and_record_roundtrip(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Random key keeps concurrent local/CI test runs from sharing an advisory lock.
    monkeypatch.setattr(notifier, "LINE_NOTIFICATION_LOCK_KEY", secrets.randbelow(2**62) + 1)
    database = _database_access(db_session)
    transport = _FakeTransport()
    baseline = _context(
        _activity(101, "2026-07-01"),
        _activity(102, "2026-07-02"),
    )

    seeded = _execute(baseline, database=database, transport=transport)

    assert seeded.status == "seeded"
    assert transport.sent_activity_ids == []
    assert get_notified_activity_ids(db_session) == {
        SYSTEM_INITIALIZED_MARKER_ID,
        101,
        102,
    }

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
    assert get_notified_activity_ids(db_session) == {
        SYSTEM_INITIALIZED_MARKER_ID,
        101,
        102,
        103,
    }
    notification = db_session.scalar(
        select(LineNotification).where(LineNotification.garmin_activity_id == 103)
    )
    assert notification is not None
    assert notification.is_seed is False
