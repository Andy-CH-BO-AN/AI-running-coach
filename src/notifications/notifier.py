"""LINE notification coordinator with persistent and stateless delivery."""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, ContextManager, Generator, Protocol, Sequence

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
from src.notifications.line_client import LineSendResult, send_push_messages

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


class _NotificationProfile(Enum):
    """Sealed differences between existing manual and Daily wrappers."""

    MANUAL = auto()
    DAILY = auto()


@dataclass(frozen=True, slots=True)
class _ActivityCandidate:
    activity: dict[str, Any]
    week: dict[str, Any]

    @property
    def activity_id(self) -> Any:
        return self.activity["activity_id"]


class _LineTransport(Protocol):
    """Internal LINE transport seam; tests can provide a deterministic fake."""

    def send(
        self,
        token: str,
        group_id: str,
        messages: Sequence[str],
    ) -> LineSendResult: ...


@dataclass(frozen=True, slots=True)
class _ProductionLineTransport:
    """Adapter retaining line_client ownership of HTTP, retry, and backoff."""

    def send(
        self,
        token: str,
        group_id: str,
        messages: Sequence[str],
    ) -> LineSendResult:
        # Resolve the module global at call time so existing monkeypatch seams remain valid.
        return send_push_messages(token, group_id, messages)


class _ActivityDeliveryState(Enum):
    READY = auto()
    RENDERED = auto()
    ALL_BATCHES_ACCEPTED = auto()
    LINE_FAILED = auto()
    STATELESS_COMPLETE = auto()
    RECORDED = auto()
    SENT_UNRECORDED = auto()


@dataclass(frozen=True, slots=True)
class _ActivityDeliveryOutcome:
    state: _ActivityDeliveryState
    send_result: LineSendResult
    persistence_error: SQLAlchemyError | None = field(default=None, repr=False)


@dataclass(slots=True, repr=False)
class _ActivityDelivery:
    """Own one Activity's render -> LINE acceptance -> record lifecycle."""

    candidate: _ActivityCandidate
    token: str
    group_id: str
    transport: _LineTransport
    state: _ActivityDeliveryState = field(
        default=_ActivityDeliveryState.READY,
        init=False,
    )

    def run(self, db_session: Session | None) -> _ActivityDeliveryOutcome:
        if self.state is not _ActivityDeliveryState.READY:
            raise RuntimeError("Activity delivery can only run once")

        messages = format_activity_messages(
            self.candidate.activity,
            self.candidate.week,
        )
        self.state = _ActivityDeliveryState.RENDERED
        send_result = self.transport.send(self.token, self.group_id, messages)
        if not send_result.success:
            self.state = _ActivityDeliveryState.LINE_FAILED
            return _ActivityDeliveryOutcome(self.state, send_result)

        # A successful aggregate result means every <=5-message transport batch
        # was accepted (including stable retry-key 409 acceptance).
        self.state = _ActivityDeliveryState.ALL_BATCHES_ACCEPTED
        if db_session is None:
            self.state = _ActivityDeliveryState.STATELESS_COMPLETE
            return _ActivityDeliveryOutcome(self.state, send_result)

        try:
            record_notification(db_session, self.candidate.activity_id)
        except SQLAlchemyError as exc:
            if not is_database_connection_error(exc):
                raise
            self.state = _ActivityDeliveryState.SENT_UNRECORDED
            return _ActivityDeliveryOutcome(self.state, send_result, exc)

        self.state = _ActivityDeliveryState.RECORDED
        return _ActivityDeliveryOutcome(self.state, send_result)


@dataclass
class _RunProgress:
    all_candidates: list[_ActivityCandidate] | None = None
    fallback_candidates: list[_ActivityCandidate] | None = None
    attempted_activity_ids: set[Any] = field(default_factory=set)
    sent: int = 0
    failed: int = 0
    sent_unrecorded_activity_id: Any | None = None


@dataclass(frozen=True, slots=True)
class _PersistenceLoss:
    activity_id: Any


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


def _activity_recency_key(candidate: _ActivityCandidate) -> tuple[str, int]:
    try:
        activity_id = int(candidate.activity_id)
    except (TypeError, ValueError):
        activity_id = -1
    return (str(candidate.activity.get("date") or ""), activity_id)


@dataclass(repr=False)
class _NotificationRun:
    """One notification run engine shared by manual and Cloud Daily wrappers."""

    context: dict[str, Any]
    token: str
    group_id: str
    profile: _NotificationProfile
    database: NotificationDatabaseAccess | None
    transport: _LineTransport
    progress: _RunProgress = field(default_factory=_RunProgress)

    def execute(self) -> NotificationResult:
        if self.profile is _NotificationProfile.DAILY and (
            self.database is None or not self.database.is_available()
        ):
            return self._continue_stateless(
                status="stateless_done",
                budget=MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN,
            )

        try:
            result = self._run_persistent()
        except SQLAlchemyError as exc:
            if not is_database_connection_error(exc):
                raise
            return self._handle_persistence_loss(exc)

        if isinstance(result, _PersistenceLoss):
            return self._finish_daily_persistence_loss()
        return result

    def _result(self, status: str) -> NotificationResult:
        return NotificationResult(
            status=status,
            sent=self.progress.sent,
            failed=self.progress.failed,
        )

    def _all_candidates(self) -> list[_ActivityCandidate]:
        if self.progress.all_candidates is None:
            candidates: list[_ActivityCandidate] = []
            for week in self.context.get("weekly_analysis", []):
                for activity in week.get("sessions", []):
                    if activity.get("activity_id") is not None:
                        candidates.append(_ActivityCandidate(activity, week))
            candidates.sort(key=_activity_recency_key, reverse=True)
            seen_activity_ids: set[Any] = set()
            deduplicated: list[_ActivityCandidate] = []
            for candidate in candidates:
                if candidate.activity_id in seen_activity_ids:
                    continue
                seen_activity_ids.add(candidate.activity_id)
                deduplicated.append(candidate)
            self.progress.all_candidates = deduplicated
        return self.progress.all_candidates

    def _lock_connection(self) -> ContextManager[Any]:
        if self.profile is _NotificationProfile.MANUAL:
            return _get_lock_connection()
        if self.database is None:
            raise AssertionError("Daily persistent notification requires database access")
        return self.database.lock_connection()

    def _db_session(self) -> ContextManager[Session]:
        if self.profile is _NotificationProfile.MANUAL:
            return _get_db_session()
        if self.database is None:
            raise AssertionError("Daily persistent notification requires database access")
        return self.database.session()

    def _run_persistent(self) -> NotificationResult | _PersistenceLoss:
        with self._lock_connection() as lock_conn:
            lock_acquired = False
            try:
                lock_acquired = _acquire_advisory_lock(lock_conn)
                if not lock_acquired:
                    logger.info(
                        "LINE notification: skipped (advisory lock held by another process)"
                    )
                    return NotificationResult(status="skipped_locked")

                with self._db_session() as db_session:
                    return self._run_under_lock(db_session)
            finally:
                if lock_acquired:
                    self._release_lock(lock_conn)

    def _release_lock(self, lock_conn: Any) -> None:
        if self.profile is _NotificationProfile.DAILY:
            if self.database is None or not self.database.is_available():
                return
            try:
                _release_advisory_lock(lock_conn)
            except SQLAlchemyError as exc:
                if not is_database_connection_error(exc):
                    raise
                self.database.revoke(exc)
                logger.warning(
                    "LINE notification: persistence lost while releasing advisory lock (%s)",
                    type(exc).__name__,
                )
            return

        try:
            _release_advisory_lock(lock_conn)
        except SQLAlchemyError as exc:
            if not is_database_connection_error(exc):
                raise
            logger.warning(
                "LINE notification: advisory-lock release failed (%s)",
                type(exc).__name__,
            )

    def _run_under_lock(
        self,
        db_session: Session,
    ) -> NotificationResult | _PersistenceLoss:
        notified_ids = get_notified_activity_ids(db_session)
        all_candidates = self._all_candidates()
        all_ids = [candidate.activity_id for candidate in all_candidates]

        if not notified_ids:
            logger.info(
                "LINE notification: first run detected — seeding %d activities as baseline",
                len(all_ids),
            )
            seed_baseline_notifications(db_session, all_ids)
            return NotificationResult(status="seeded")

        new_candidates = [
            candidate
            for candidate in all_candidates
            if candidate.activity_id not in notified_ids
        ]
        if not new_candidates:
            logger.info("LINE notification: no new activities to notify")
            return NotificationResult(status="no_new")

        selected = new_candidates[:MAX_LINE_NOTIFICATIONS_PER_RUN]
        self.progress.fallback_candidates = selected
        deferred = len(new_candidates) - len(selected)
        if self.profile is _NotificationProfile.MANUAL:
            logger.info("LINE notification: %d new activities to send", len(selected))
        if deferred:
            logger.warning(
                "LINE notification: capped at %d; deferring %d activities to later runs",
                MAX_LINE_NOTIFICATIONS_PER_RUN,
                deferred,
            )
        return self._deliver_persistent(selected, db_session)

    def _delivery(self, candidate: _ActivityCandidate) -> _ActivityDelivery:
        return _ActivityDelivery(
            candidate=candidate,
            token=self.token,
            group_id=self.group_id,
            transport=self.transport,
        )

    def _deliver_persistent(
        self,
        candidates: list[_ActivityCandidate],
        db_session: Session,
    ) -> NotificationResult | _PersistenceLoss:
        for index, candidate in enumerate(candidates):
            activity_id = candidate.activity_id
            self.progress.attempted_activity_ids.add(activity_id)
            outcome = self._delivery(candidate).run(db_session)

            if outcome.state is _ActivityDeliveryState.LINE_FAILED:
                self._log_send_failure(activity_id, outcome.send_result, stateless=False)
                self.progress.failed += 1
                continue

            if outcome.state is _ActivityDeliveryState.RECORDED:
                self.progress.sent += 1
                self.progress.sent_unrecorded_activity_id = None
                logger.info(
                    "LINE notification: sent and recorded activity %s",
                    activity_id,
                )
                continue

            if outcome.state is not _ActivityDeliveryState.SENT_UNRECORDED:
                raise AssertionError("Persistent Activity delivery returned invalid state")

            self.progress.sent_unrecorded_activity_id = activity_id
            persistence_error = outcome.persistence_error
            if persistence_error is None:
                raise AssertionError("Sent-unrecorded outcome requires persistence error")

            if self.profile is _NotificationProfile.DAILY:
                self.progress.sent += 1
                if self.database is None:
                    raise AssertionError("Daily persistence loss requires database access")
                self.database.revoke(persistence_error)
                return _PersistenceLoss(activity_id)

            logger.warning(
                "LINE notification: DB recording failed for activity %s (%s); "
                "this activity may be sent again",
                activity_id,
                type(persistence_error).__name__,
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
            self.progress.failed += 1
            remaining = len(candidates) - index - 1
            logger.warning(
                "LINE notification: persistence unavailable; stopping delivery with "
                "%d activities not sent this run",
                remaining,
            )
            return self._result("done")

        return self._result("done")

    def _handle_persistence_loss(self, exc: SQLAlchemyError) -> NotificationResult:
        if self.profile is _NotificationProfile.MANUAL:
            logger.warning(
                "LINE notification: DB access failed (%s); continuing with stateless notification",
                type(exc).__name__,
            )
            return self._continue_stateless(
                status="stateless_done",
                budget=MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN,
            )

        if self.database is None:
            raise AssertionError("Daily persistence loss requires database access")
        self.database.revoke(exc)
        return self._finish_daily_persistence_loss()

    def _finish_daily_persistence_loss(self) -> NotificationResult:
        sent_but_unrecorded = self.progress.sent_unrecorded_activity_id is not None
        budget = MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN - int(sent_but_unrecorded)
        if sent_but_unrecorded:
            logger.warning(
                "LINE notification: activity %s was sent but not recorded; "
                "it consumes one stateless notification slot and will not be resent this run",
                self.progress.sent_unrecorded_activity_id,
            )
        return self._continue_stateless(
            status="persistence_loss_done",
            budget=budget,
        )

    def _continue_stateless(self, *, status: str, budget: int) -> NotificationResult:
        candidates = self.progress.fallback_candidates or self._all_candidates()
        remaining = [
            candidate
            for candidate in candidates
            if candidate.activity_id not in self.progress.attempted_activity_ids
        ]
        selected = remaining[:max(budget, 0)]
        deferred = len(remaining) - len(selected)

        if self.profile is _NotificationProfile.MANUAL:
            logger.warning(
                "LINE notification: stateless fallback; sending up to %d activities "
                "without DB deduplication. Repeated notifications are possible while "
                "Neon is unavailable.",
                max(budget, 0),
            )
            if deferred:
                logger.warning(
                    "LINE notification: stateless fallback capped at %d; "
                    "%d activities not sent this run",
                    max(budget, 0),
                    deferred,
                )
        else:
            logger.warning(
                "LINE notification: persistence unavailable; sending up to %d remaining "
                "activities statelessly. Repeated notifications are possible on a later run.",
                max(budget, 0),
            )
            if deferred:
                logger.warning(
                    "LINE notification: stateless notification capped; "
                    "%d activities not sent this run",
                    deferred,
                )

        self._deliver_stateless(selected)
        return self._result(status)

    def _deliver_stateless(self, candidates: list[_ActivityCandidate]) -> None:
        for candidate in candidates:
            activity_id = candidate.activity_id
            self.progress.attempted_activity_ids.add(activity_id)
            outcome = self._delivery(candidate).run(None)
            if outcome.state is _ActivityDeliveryState.LINE_FAILED:
                self._log_send_failure(
                    activity_id,
                    outcome.send_result,
                    stateless=self.profile is _NotificationProfile.DAILY,
                )
                self.progress.failed += 1
                continue
            if outcome.state is not _ActivityDeliveryState.STATELESS_COMPLETE:
                raise AssertionError("Stateless Activity delivery returned invalid state")
            self.progress.sent += 1
            logger.info("LINE notification: sent stateless activity %s", activity_id)

    @staticmethod
    def _log_send_failure(
        activity_id: Any,
        result: LineSendResult,
        *,
        stateless: bool,
    ) -> None:
        qualifier = "stateless " if stateless else ""
        logger.error(
            "LINE notification: %ssend FAILED for activity %s "
            "(status=%s, attempts=%d, error=%s)",
            qualifier,
            activity_id,
            result.status_code,
            result.attempts,
            result.error_type,
        )


def _run_notification(
    coach_context_path: str,
    *,
    profile: _NotificationProfile,
    database: NotificationDatabaseAccess | None,
    transport: _LineTransport,
) -> NotificationResult:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    group_id = os.environ.get("LINE_GROUP_ID")
    if not token or not group_id:
        logger.info("LINE notification disabled: missing required environment variables")
        return NotificationResult(status="disabled")

    # Context, formatter, and program errors deliberately propagate.
    context = _load_coach_context(coach_context_path)
    return _NotificationRun(
        context=context,
        token=token,
        group_id=group_id,
        profile=profile,
        database=database,
        transport=transport,
    ).execute()


def run_daily_line_notification(
    coach_context_path: str,
    *,
    database: NotificationDatabaseAccess | None,
) -> NotificationResult:
    """Run LINE notification under the Cloud Daily Run's monotonic persistence policy."""
    return _run_notification(
        coach_context_path,
        profile=_NotificationProfile.DAILY,
        database=database,
        transport=_ProductionLineTransport(),
    )


def run_line_notification(coach_context_path: str) -> NotificationResult:
    """Send manual-flow activity notifications with stateless DB-loss fallback."""
    return _run_notification(
        coach_context_path,
        profile=_NotificationProfile.MANUAL,
        database=None,
        transport=_ProductionLineTransport(),
    )
