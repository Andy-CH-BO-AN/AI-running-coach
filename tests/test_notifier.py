"""Public notification-wrapper contract tests.

Lifecycle branching belongs to ``test_activity_notification.py``. This module
keeps only behavior that is observable at the manual and Daily entry points.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from src.db.settings import is_database_connection_error
from src.notifications.line_client import LineSendResult
from src.notifications.notifier import (
    NotificationDatabaseAccess,
    run_daily_line_notification,
    run_line_notification,
)


DUMMY_TOKEN = "dummy-token"
DUMMY_GROUP = "dummy-group"
SUCCESS_RESULT = LineSendResult(True, 200, 1, None)
ACTIVITY_MARKER_PREFIX = "activity-marker:"


def _make_coach_context(
    sessions_by_week: list[list[dict]] | None = None,
) -> dict:
    if sessions_by_week is None:
        sessions_by_week = [[
            {
                "activity_id": 1001,
                "date": "2026-07-20",
                "type": "easy",
                "source_activity_type": "running",
                "distance_km": 8.0,
                "duration_min": 50.0,
                "training_load": 100.0,
                "avg_hr": 150,
                "avg_pace": "6:15",
                "segments": [],
                "environment": {},
                "data_quality": {"status": "complete", "missing_fields": []},
            }
        ]]

    return {
        "meta": {"today": "2026-07-26"},
        "weekly_analysis": [
            {
                "week_label": f"Week {index}",
                "week_start": "2026-07-20",
                "week_end": "2026-07-26",
                "derived_training_load": 500.0,
                "sessions": sessions,
            }
            for index, sessions in enumerate(sessions_by_week)
        ],
    }


def _write_context(tmp_path: Path, context: dict) -> Path:
    path = tmp_path / "coach_context.json"
    path.write_text(json.dumps(context), encoding="utf-8")
    return path


def _env() -> dict[str, str]:
    return {
        "LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN,
        "LINE_GROUP_ID": DUMMY_GROUP,
    }


def _connection_error(message: str = "connection refused") -> OperationalError:
    return OperationalError("SELECT 1", {}, ConnectionError(message))


@pytest.fixture(autouse=True)
def mock_lock_connection():
    """Keep manual wrapper tests away from a real PostgreSQL connection."""
    connection = MagicMock()
    with patch("src.notifications.notifier._get_lock_connection") as get_connection:
        get_connection.return_value.__enter__.return_value = connection
        yield connection


def _database_access():
    state = {"available": True, "revocations": 0}
    session = MagicMock()
    connection = MagicMock()

    def revoke(_error: BaseException) -> None:
        if state["available"]:
            state["available"] = False
            state["revocations"] += 1
            session.invalidate()
            connection.invalidate()

    @contextmanager
    def session_context():
        try:
            yield session
        except SQLAlchemyError as error:
            if is_database_connection_error(error):
                revoke(error)
            raise

    @contextmanager
    def connection_context():
        try:
            yield connection
        except SQLAlchemyError as error:
            if is_database_connection_error(error):
                revoke(error)
            raise

    access = NotificationDatabaseAccess(
        is_available=lambda: state["available"],
        session=session_context,
        lock_connection=connection_context,
        revoke=revoke,
    )
    return access, state


def test_activity_pages_are_accepted_before_notification_is_recorded(tmp_path):
    """One Activity is recorded only after its whole message sequence succeeds."""
    context_path = _write_context(tmp_path, _make_coach_context())
    pages = ["activity-marker:1001", "detail-marker:1001"]
    recorded_ids: list[int] = []

    def accept_messages(_token, _group_id, messages):
        assert recorded_ids == []
        assert list(messages) == pages
        return SUCCESS_RESULT

    def record_activity(_session, activity_id):
        recorded_ids.append(activity_id)
        return True

    with patch.dict(os.environ, _env(), clear=True), patch(
        "src.notifications.notifier.get_notified_activity_ids",
        return_value={9999},
    ), patch(
        "src.notifications.notifier._acquire_advisory_lock",
        return_value=True,
    ), patch(
        "src.notifications.notifier._release_advisory_lock",
    ), patch(
        "src.notifications.notifier._get_db_session",
    ), patch(
        "src.notifications.notifier.format_activity_messages",
        return_value=pages,
    ), patch(
        "src.notifications.notifier.send_push_messages",
        side_effect=accept_messages,
    ), patch(
        "src.notifications.notifier.record_notification",
        side_effect=record_activity,
    ):
        result = run_line_notification(str(context_path))

    assert (result.status, result.sent, result.failed) == ("done", 1, 0)
    assert recorded_ids == [1001]


def test_manual_connection_loss_before_send_uses_stateless_fallback(tmp_path):
    context_path = _write_context(tmp_path, _make_coach_context())
    sent_markers: list[str] = []

    def send(_token, _group_id, messages):
        sent_markers.extend(messages)
        return SUCCESS_RESULT

    with patch.dict(os.environ, _env(), clear=True), patch(
        "src.notifications.notifier._acquire_advisory_lock",
        return_value=True,
    ), patch(
        "src.notifications.notifier._release_advisory_lock",
    ) as release, patch(
        "src.notifications.notifier._get_db_session",
    ), patch(
        "src.notifications.notifier.get_notified_activity_ids",
        side_effect=_connection_error(),
    ), patch(
        "src.notifications.notifier.format_activity_messages",
        side_effect=lambda activity, _week: [
            f"{ACTIVITY_MARKER_PREFIX}{activity['activity_id']}"
        ],
    ), patch(
        "src.notifications.notifier.send_push_messages",
        side_effect=send,
    ):
        result = run_line_notification(str(context_path))

    assert (result.status, result.sent, result.failed) == ("stateless_done", 1, 0)
    assert sent_markers == ["activity-marker:1001"]
    assert release.call_count == 1


def test_manual_nonconnection_record_error_propagates(tmp_path):
    context_path = _write_context(tmp_path, _make_coach_context())

    with patch.dict(os.environ, _env(), clear=True), patch(
        "src.notifications.notifier.get_notified_activity_ids",
        return_value={9999},
    ), patch(
        "src.notifications.notifier._acquire_advisory_lock",
        return_value=True,
    ), patch(
        "src.notifications.notifier._release_advisory_lock",
    ), patch(
        "src.notifications.notifier._get_db_session",
    ), patch(
        "src.notifications.notifier.send_push_messages",
        return_value=SUCCESS_RESULT,
    ), patch(
        "src.notifications.notifier.record_notification",
        side_effect=IntegrityError("INSERT", {}, Exception("constraint failed")),
    ), pytest.raises(IntegrityError):
        run_line_notification(str(context_path))


def test_bad_json_raises_instead_of_entering_fallback(tmp_path):
    context_path = tmp_path / "bad.json"
    context_path.write_text("{not valid json", encoding="utf-8")

    with patch.dict(os.environ, _env(), clear=True), pytest.raises(json.JSONDecodeError):
        run_line_notification(str(context_path))


def test_daily_nontransient_persistence_error_does_not_revoke_database(tmp_path):
    context_path = _write_context(tmp_path, _make_coach_context())
    access, state = _database_access()

    with patch.dict(os.environ, _env(), clear=True), patch(
        "src.notifications.notifier._acquire_advisory_lock",
        return_value=True,
    ), patch(
        "src.notifications.notifier._release_advisory_lock",
    ) as release, patch(
        "src.notifications.notifier.get_notified_activity_ids",
        return_value={9999},
    ), patch(
        "src.notifications.notifier.record_notification",
        side_effect=IntegrityError("INSERT", {}, Exception("constraint failed")),
    ), patch(
        "src.notifications.notifier.send_push_messages",
        return_value=SUCCESS_RESULT,
    ), pytest.raises(IntegrityError):
        run_daily_line_notification(str(context_path), database=access)

    assert state == {"available": True, "revocations": 0}
    assert release.call_count == 1


def test_daily_formatter_error_does_not_revoke_database(tmp_path):
    context_path = _write_context(tmp_path, _make_coach_context())
    access, state = _database_access()

    with patch.dict(os.environ, _env(), clear=True), patch(
        "src.notifications.notifier._acquire_advisory_lock",
        return_value=True,
    ), patch(
        "src.notifications.notifier._release_advisory_lock",
    ) as release, patch(
        "src.notifications.notifier.get_notified_activity_ids",
        return_value={9999},
    ), patch(
        "src.notifications.notifier.format_activity_messages",
        side_effect=ValueError("formatter failed"),
    ), pytest.raises(ValueError, match="formatter failed"):
        run_daily_line_notification(str(context_path), database=access)

    assert state == {"available": True, "revocations": 0}
    assert release.call_count == 1
