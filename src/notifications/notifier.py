"""LINE notification coordinator with normal and stateless degraded modes."""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.repositories import (
    get_notified_activity_ids,
    record_notification,
    seed_baseline_notifications,
)
from src.db.settings import is_database_available, is_database_connection_error
from src.notifications.constants import (
    LINE_NOTIFICATION_LOCK_KEY,
    MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN,
    MAX_LINE_NOTIFICATIONS_PER_RUN,
)
from src.notifications.formatter import format_activity_message
from src.notifications.line_client import send_push_message

logger = logging.getLogger(__name__)


@dataclass
class NotificationResult:
    """Result of one notification run without exposing sensitive values."""

    status: str
    sent: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return f"NotificationResult(status={self.status}, sent={self.sent}, failed={self.failed})"


@contextmanager
def _get_db_session() -> Generator[Session, None, None]:
    from src.db.session import SessionLocal

    with SessionLocal() as session:
        yield session


@contextmanager
def _get_lock_connection() -> Generator[Any, None, None]:
    """Use a dedicated DB connection for PostgreSQL advisory locking."""
    from src.db.session import get_engine

    with get_engine().connect() as conn:
        yield conn


def _acquire_advisory_lock(conn: Any) -> bool:
    from sqlalchemy import text

    result = conn.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": LINE_NOTIFICATION_LOCK_KEY},
    )
    return bool(result.scalar())


def _release_advisory_lock(conn: Any) -> None:
    from sqlalchemy import text

    conn.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": LINE_NOTIFICATION_LOCK_KEY},
    )


def _load_coach_context(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as file_handle:
        return json.load(file_handle)


def _extract_all_sessions(context: dict[str, Any]) -> list[tuple[dict, dict]]:
    pairs: list[tuple[dict, dict]] = []
    for week in context.get("weekly_analysis", []):
        for session in week.get("sessions", []):
            pairs.append((session, week))
    return pairs


def _activity_recency_key(pair: tuple[dict, dict]) -> tuple[str, int]:
    activity, _week = pair
    try:
        activity_id = int(activity.get("activity_id"))
    except (TypeError, ValueError):
        activity_id = -1
    return (str(activity.get("date") or ""), activity_id)


def _send_pairs(
    pairs: list[tuple[dict, dict]],
    token: str,
    group_id: str,
    *,
    db_session: Session | None,
    status: str,
) -> NotificationResult:
    sent = 0
    failed = 0

    for activity, week in pairs:
        activity_id = activity["activity_id"]
        message = format_activity_message(activity, week)
        result = send_push_message(token, group_id, message)

        if not result.success:
            logger.error(
                "LINE notification: send FAILED for activity %s "
                "(status=%s, attempts=%d, error=%s)",
                activity_id,
                result.status_code,
                result.attempts,
                result.error_type,
            )
            failed += 1
            continue

        if db_session is None:
            sent += 1
            logger.info("LINE notification: sent stateless activity %s", activity_id)
            continue

        try:
            record_notification(db_session, activity_id)
        except SQLAlchemyError as exc:
            if not is_database_connection_error(exc):
                raise
            logger.warning(
                "LINE notification: DB recording failed for activity %s (%s); "
                "this activity may be sent again",
                activity_id,
                type(exc).__name__,
            )
            try:
                db_session.rollback()
            except SQLAlchemyError as rollback_exc:
                if not is_database_connection_error(rollback_exc):
                    raise
                logger.warning(
                    "LINE notification: DB rollback failed after recording error (%s)",
                    type(rollback_exc).__name__,
                )
            failed += 1
            continue

        sent += 1
        logger.info("LINE notification: sent and recorded activity %s", activity_id)

    return NotificationResult(status=status, sent=sent, failed=failed)


def _run_without_database(
    context: dict[str, Any],
    token: str,
    group_id: str,
) -> NotificationResult:
    pairs = [pair for pair in _extract_all_sessions(context) if pair[0].get("activity_id") is not None]
    pairs.sort(key=_activity_recency_key, reverse=True)
    selected = pairs[:MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN]
    deferred = len(pairs) - len(selected)

    logger.warning(
        "LINE notification: degraded mode; sending up to %d activities without DB deduplication. "
        "Repeated notifications are possible while Neon is unavailable.",
        MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN,
    )
    if deferred:
        logger.warning(
            "LINE notification: degraded mode capped at %d; %d activities not sent this run",
            MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN,
            deferred,
        )

    return _send_pairs(selected, token, group_id, db_session=None, status="degraded_done")


def _run_with_lock(
    context: dict[str, Any],
    db_session: Session,
    token: str,
    group_id: str,
) -> NotificationResult:
    notified_ids = get_notified_activity_ids(db_session)
    all_pairs = _extract_all_sessions(context)
    all_ids = [session.get("activity_id") for session, _ in all_pairs if session.get("activity_id") is not None]

    if not notified_ids:
        logger.info(
            "LINE notification: first run detected — seeding %d activities as baseline",
            len(all_ids),
        )
        seed_baseline_notifications(db_session, all_ids)
        return NotificationResult(status="seeded")

    new_pairs = [
        pair
        for pair in all_pairs
        if pair[0].get("activity_id") is not None
        and pair[0]["activity_id"] not in notified_ids
    ]
    new_pairs.sort(key=_activity_recency_key, reverse=True)

    if not new_pairs:
        logger.info("LINE notification: no new activities to notify")
        return NotificationResult(status="no_new")

    selected = new_pairs[:MAX_LINE_NOTIFICATIONS_PER_RUN]
    deferred = len(new_pairs) - len(selected)
    logger.info("LINE notification: %d new activities to send", len(selected))
    if deferred:
        logger.warning(
            "LINE notification: capped at %d; deferring %d activities to later runs",
            MAX_LINE_NOTIFICATIONS_PER_RUN,
            deferred,
        )

    return _send_pairs(selected, token, group_id, db_session=db_session, status="done")


def _run_with_database(
    context: dict[str, Any],
    token: str,
    group_id: str,
) -> NotificationResult:
    with _get_lock_connection() as lock_conn:
        lock_acquired = False
        try:
            lock_acquired = _acquire_advisory_lock(lock_conn)
            if not lock_acquired:
                logger.info("LINE notification: skipped (advisory lock held by another process)")
                return NotificationResult(status="skipped_locked")

            with _get_db_session() as db_session:
                return _run_with_lock(context, db_session, token, group_id)
        finally:
            if lock_acquired:
                try:
                    _release_advisory_lock(lock_conn)
                except SQLAlchemyError as exc:
                    if not is_database_connection_error(exc):
                        raise
                    logger.warning(
                        "LINE notification: advisory-lock release failed (%s)",
                        type(exc).__name__,
                    )


def run_line_notification(coach_context_path: str) -> NotificationResult:
    """Send activity notifications; only DB failures use degraded behavior."""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    group_id = os.environ.get("LINE_GROUP_ID")
    if not token or not group_id:
        logger.info("LINE notification disabled: missing required environment variables")
        return NotificationResult(status="disabled")

    # Context, formatter, and program errors deliberately propagate to fail the workflow.
    context = _load_coach_context(coach_context_path)

    if not is_database_available():
        return _run_without_database(context, token, group_id)

    try:
        return _run_with_database(context, token, group_id)
    except SQLAlchemyError as exc:
        if not is_database_connection_error(exc):
            raise
        logger.warning(
            "LINE notification: DB access failed (%s); continuing in degraded mode",
            type(exc).__name__,
        )
        return _run_without_database(context, token, group_id)
