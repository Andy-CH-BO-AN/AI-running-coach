"""LINE notification coordinator with persistent and stateless delivery."""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, ContextManager, Generator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.repositories import (
    get_notified_activity_ids,
    record_notification,
    seed_baseline_notifications,
)
from src.db.settings import is_database_connection_error
from src.notifications.constants import (
    LINE_NOTIFICATION_LOCK_KEY,
    MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN,
    MAX_LINE_NOTIFICATIONS_PER_RUN,
)
from src.notifications.formatter import format_activity_messages
from src.notifications.line_client import send_push_messages

logger = logging.getLogger(__name__)


@dataclass
class NotificationResult:
    """Result of one notification run without exposing sensitive values."""

    status: str
    sent: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return f"NotificationResult(status={self.status}, sent={self.sent}, failed={self.failed})"


@dataclass(frozen=True, slots=True)
class NotificationDatabaseAccess:
    """Internal adapter used by the Cloud Daily Run's revocable Neon gate."""

    is_available: Callable[[], bool]
    session: Callable[[], ContextManager[Session]]
    lock_connection: Callable[[], ContextManager[Any]]
    revoke: Callable[[BaseException], None]


@dataclass
class _DailyDeliveryProgress:
    candidate_pairs: list[tuple[dict, dict]] | None = None
    attempted_activity_ids: set[Any] = field(default_factory=set)
    sent: int = 0
    failed: int = 0
    pending_unrecorded_activity_id: Any | None = None


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

    for index, (activity, week) in enumerate(pairs):
        activity_id = activity["activity_id"]
        messages = format_activity_messages(activity, week)
        result = send_push_messages(token, group_id, messages)

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
            remaining = len(pairs) - index - 1
            logger.warning(
                "LINE notification: persistence unavailable; stopping delivery with "
                "%d activities not sent this run",
                remaining,
            )
            break

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
        "LINE notification: stateless fallback; sending up to %d activities without DB deduplication. "
        "Repeated notifications are possible while Neon is unavailable.",
        MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN,
    )
    if deferred:
        logger.warning(
            "LINE notification: stateless fallback capped at %d; %d activities not sent this run",
            MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN,
            deferred,
        )

    return _send_pairs(selected, token, group_id, db_session=None, status="stateless_done")


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


def _daily_result(status: str, progress: _DailyDeliveryProgress) -> NotificationResult:
    return NotificationResult(
        status=status,
        sent=progress.sent,
        failed=progress.failed,
    )


def _daily_eligible_pairs(context: dict[str, Any]) -> list[tuple[dict, dict]]:
    pairs = [
        pair
        for pair in _extract_all_sessions(context)
        if pair[0].get("activity_id") is not None
    ]
    pairs.sort(key=_activity_recency_key, reverse=True)
    return pairs


def _send_daily_stateless_pairs(
    pairs: list[tuple[dict, dict]],
    token: str,
    group_id: str,
    *,
    progress: _DailyDeliveryProgress,
) -> None:
    for activity, week in pairs:
        activity_id = activity["activity_id"]
        messages = format_activity_messages(activity, week)
        progress.attempted_activity_ids.add(activity_id)
        result = send_push_messages(token, group_id, messages)

        if not result.success:
            logger.error(
                "LINE notification: stateless send FAILED for activity %s "
                "(status=%s, attempts=%d, error=%s)",
                activity_id,
                result.status_code,
                result.attempts,
                result.error_type,
            )
            progress.failed += 1
            continue

        progress.sent += 1
        logger.info("LINE notification: sent stateless activity %s", activity_id)


def _continue_daily_stateless(
    context: dict[str, Any],
    token: str,
    group_id: str,
    *,
    progress: _DailyDeliveryProgress,
    status: str,
    budget: int,
) -> NotificationResult:
    candidates = progress.candidate_pairs or _daily_eligible_pairs(context)
    remaining = [
        pair
        for pair in candidates
        if pair[0].get("activity_id") not in progress.attempted_activity_ids
    ]
    selected = remaining[:max(budget, 0)]
    deferred = len(remaining) - len(selected)

    logger.warning(
        "LINE notification: persistence unavailable; sending up to %d remaining "
        "activities statelessly. Repeated notifications are possible on a later run.",
        max(budget, 0),
    )
    if deferred:
        logger.warning(
            "LINE notification: stateless notification capped; %d activities not sent this run",
            deferred,
        )

    _send_daily_stateless_pairs(
        selected,
        token,
        group_id,
        progress=progress,
    )
    return _daily_result(status, progress)


def _send_daily_persistent_pairs(
    pairs: list[tuple[dict, dict]],
    token: str,
    group_id: str,
    *,
    db_session: Session,
    progress: _DailyDeliveryProgress,
) -> NotificationResult:
    progress.candidate_pairs = pairs
    for activity, week in pairs:
        activity_id = activity["activity_id"]
        messages = format_activity_messages(activity, week)
        progress.attempted_activity_ids.add(activity_id)
        result = send_push_messages(token, group_id, messages)

        if not result.success:
            logger.error(
                "LINE notification: send FAILED for activity %s "
                "(status=%s, attempts=%d, error=%s)",
                activity_id,
                result.status_code,
                result.attempts,
                result.error_type,
            )
            progress.failed += 1
            continue

        progress.sent += 1
        progress.pending_unrecorded_activity_id = activity_id
        record_notification(db_session, activity_id)
        progress.pending_unrecorded_activity_id = None
        logger.info("LINE notification: sent and recorded activity %s", activity_id)

    return _daily_result("done", progress)


def _run_daily_with_lock(
    context: dict[str, Any],
    db_session: Session,
    token: str,
    group_id: str,
    *,
    progress: _DailyDeliveryProgress,
) -> NotificationResult:
    notified_ids = get_notified_activity_ids(db_session)
    all_pairs = _extract_all_sessions(context)
    all_ids = [
        session.get("activity_id")
        for session, _ in all_pairs
        if session.get("activity_id") is not None
    ]

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
    if deferred:
        logger.warning(
            "LINE notification: capped at %d; deferring %d activities to later runs",
            MAX_LINE_NOTIFICATIONS_PER_RUN,
            deferred,
        )
    return _send_daily_persistent_pairs(
        selected,
        token,
        group_id,
        db_session=db_session,
        progress=progress,
    )


def _run_daily_with_database(
    context: dict[str, Any],
    token: str,
    group_id: str,
    *,
    database: NotificationDatabaseAccess,
    progress: _DailyDeliveryProgress,
) -> NotificationResult:
    with database.lock_connection() as lock_conn:
        lock_acquired = False
        try:
            lock_acquired = _acquire_advisory_lock(lock_conn)
            if not lock_acquired:
                logger.info("LINE notification: skipped (advisory lock held by another process)")
                return NotificationResult(status="skipped_locked")

            with database.session() as db_session:
                return _run_daily_with_lock(
                    context,
                    db_session,
                    token,
                    group_id,
                    progress=progress,
                )
        finally:
            if lock_acquired and database.is_available():
                try:
                    _release_advisory_lock(lock_conn)
                except SQLAlchemyError as exc:
                    if not is_database_connection_error(exc):
                        raise
                    database.revoke(exc)
                    logger.warning(
                        "LINE notification: persistence lost while releasing advisory lock (%s)",
                        type(exc).__name__,
                    )


def run_daily_line_notification(
    coach_context_path: str,
    *,
    database: NotificationDatabaseAccess | None,
) -> NotificationResult:
    """Run LINE notification under the Cloud Daily Run's monotonic persistence policy."""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    group_id = os.environ.get("LINE_GROUP_ID")
    if not token or not group_id:
        logger.info("LINE notification disabled: missing required environment variables")
        return NotificationResult(status="disabled")

    context = _load_coach_context(coach_context_path)
    progress = _DailyDeliveryProgress()
    if database is None or not database.is_available():
        return _continue_daily_stateless(
            context,
            token,
            group_id,
            progress=progress,
            status="stateless_done",
            budget=MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN,
        )

    try:
        return _run_daily_with_database(
            context,
            token,
            group_id,
            database=database,
            progress=progress,
        )
    except SQLAlchemyError as exc:
        if not is_database_connection_error(exc):
            raise
        database.revoke(exc)
        sent_but_unrecorded = progress.pending_unrecorded_activity_id is not None
        budget = MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN - int(sent_but_unrecorded)
        if sent_but_unrecorded:
            logger.warning(
                "LINE notification: activity %s was sent but not recorded; "
                "it consumes one stateless notification slot and will not be resent this run",
                progress.pending_unrecorded_activity_id,
            )
        return _continue_daily_stateless(
            context,
            token,
            group_id,
            progress=progress,
            status="persistence_loss_done",
            budget=budget,
        )


def run_line_notification(coach_context_path: str) -> NotificationResult:
    """Send manual-flow activity notifications with stateless DB-loss fallback."""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    group_id = os.environ.get("LINE_GROUP_ID")
    if not token or not group_id:
        logger.info("LINE notification disabled: missing required environment variables")
        return NotificationResult(status="disabled")

    # Context, formatter, and program errors deliberately propagate to fail the workflow.
    context = _load_coach_context(coach_context_path)

    try:
        return _run_with_database(context, token, group_id)
    except SQLAlchemyError as exc:
        if not is_database_connection_error(exc):
            raise
        logger.warning(
            "LINE notification: DB access failed (%s); continuing with stateless notification",
            type(exc).__name__,
        )
        return _run_without_database(context, token, group_id)
