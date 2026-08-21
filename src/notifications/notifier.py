"""Persistent Activity LINE notifications with concise AI coaching."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, ContextManager, Generator, Protocol, Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.agents.activity_coach import (
    ACTIVITY_PROMPT_VERSION,
    ActivityCoachError,
    generate_activity_report,
)
from src.db.mappers import jsonable
from src.db.repositories import (
    get_activity_by_garmin_id,
    get_notified_activity_ids,
    get_prepared_activity_notification,
    list_pending_activity_notifications,
    mark_notification_sent,
    seed_baseline_notifications,
)
from src.db.settings import is_database_connection_error
from src.notifications.constants import (
    LINE_NOTIFICATION_LOCK_KEY,
    MAX_LINE_NOTIFICATIONS_PER_RUN,
)
from src.notifications.formatter import format_activity_coach_messages
from src.notifications.line_client import LineSendResult, send_push_messages
from src.services.ai_report_resolution import (
    ActivityPersistenceUnavailable,
    AIReportSpec,
    ActivityAINotificationPreparer,
    PreparedLineDelivery,
)

logger = logging.getLogger(__name__)

ACTIVITY_CONTEXT_VERSION = "activity-context:v2"


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
    """Cloud Daily Run's revocable persistence capability."""

    is_available: Callable[[], bool]
    session: Callable[[], ContextManager[Session]]
    lock_connection: Callable[[], ContextManager[Any]]
    revoke: Callable[[BaseException], None]


class _NotificationProfile(Enum):
    MANUAL = auto()
    DAILY = auto()


class _NotificationLockUnavailable(RuntimeError):
    """Another worker currently owns the Activity notification lock."""


@dataclass(frozen=True, slots=True)
class _ActivityCandidate:
    activity: dict[str, Any]
    week: dict[str, Any]

    @property
    def activity_id(self) -> Any:
        return self.activity["activity_id"]


@dataclass(frozen=True, slots=True)
class _PendingActivityDelivery:
    garmin_activity_id: int
    delivery: PreparedLineDelivery


@dataclass(frozen=True, slots=True)
class _NotificationWork:
    pending: tuple[_PendingActivityDelivery, ...]
    candidates: tuple[_ActivityCandidate, ...]


@dataclass(frozen=True, slots=True)
class _DeliveryOutcome:
    status: str
    sent: int = 0
    failed: int = 0


class _LineTransport(Protocol):
    def send(
        self,
        token: str,
        group_id: str,
        messages: Sequence[str],
    ) -> LineSendResult: ...


@dataclass(frozen=True, slots=True)
class _ProductionLineTransport:
    def send(
        self,
        token: str,
        group_id: str,
        messages: Sequence[str],
    ) -> LineSendResult:
        return send_push_messages(token, group_id, messages)


@contextmanager
def _get_db_session() -> Generator[Session, None, None]:
    from src.db.session import SessionLocal

    with SessionLocal() as session:
        yield session


@contextmanager
def _get_lock_connection() -> Generator[Any, None, None]:
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


def _garmin_activity_id(candidate: _ActivityCandidate) -> int:
    try:
        return int(candidate.activity_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Activity notification requires an integer Garmin activity ID") from exc


def _week_facts(week: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "week_start",
        "week_end",
        "derived_total_distance_km",
        "derived_total_duration_min",
        "derived_training_load",
        "session_counts",
        "risk_flags",
        "intensity_focuses",
        "cross_training_focus",
    )
    return {key: week[key] for key in keys if key in week}


def _athlete_profile_input(context: dict[str, Any]) -> dict[str, Any]:
    """Select existing deterministic athlete facts useful to Activity coaching."""
    physio_metrics = context.get("physio_metrics")
    if not isinstance(physio_metrics, dict):
        physio_metrics = {}
    personal_records = context.get("pb_validation_seed")
    return {
        "vo2max": physio_metrics.get("vo2max"),
        "max_heart_rate": physio_metrics.get("max_heart_rate"),
        "resting_heart_rate": physio_metrics.get("resting_heart_rate"),
        "lactate_threshold": physio_metrics.get("lactate_threshold"),
        "running_personal_records": [
            {"event": record.get("event"), "raw_value": record.get("raw_value")}
            for record in personal_records
            if isinstance(record, dict)
        ]
        if isinstance(personal_records, list)
        else [],
        "pace_zones": physio_metrics.get("pace_zones", []),
    }


@dataclass(repr=False)
class _NotificationRun:
    """Deep module owning Activity AI preparation and persistent delivery."""

    context: dict[str, Any]
    token: str
    group_id: str
    profile: _NotificationProfile
    database: NotificationDatabaseAccess | None
    transport: _LineTransport
    core_goal: str | None = None
    training_preferences: str | None = None

    def execute(self) -> NotificationResult:
        if self._daily_persistence_unavailable():
            return self._persistence_unavailable()

        try:
            work = self._select_work()
        except _NotificationLockUnavailable:
            logger.info("LINE notification: skipped (advisory lock held by another process)")
            return NotificationResult(status="skipped_locked")
        except SQLAlchemyError as exc:
            if not is_database_connection_error(exc):
                raise
            self._revoke_database(exc)
            return self._persistence_unavailable()

        if isinstance(work, NotificationResult):
            return work
        if self._daily_persistence_unavailable():
            return self._persistence_unavailable()

        sent = 0
        failed = 0
        skipped_locked = False
        ai_failed = False
        persistence_deferred = False

        for pending in work.pending:
            if self._daily_persistence_unavailable():
                return NotificationResult(
                    status="persistence_unavailable", sent=sent, failed=failed
                )
            outcome = self._send_prepared(
                garmin_activity_id=pending.garmin_activity_id,
                expected_delivery=pending.delivery,
            )
            sent += outcome.sent
            failed += outcome.failed
            skipped_locked = skipped_locked or outcome.status == "skipped_locked"
            if outcome.status == "persistence_unavailable":
                return NotificationResult(status=outcome.status, sent=sent, failed=failed)

        for candidate in work.candidates:
            if self._daily_persistence_unavailable():
                return NotificationResult(
                    status="persistence_unavailable", sent=sent, failed=failed
                )
            try:
                delivery = self._prepare_candidate(candidate)
            except _NotificationLockUnavailable:
                skipped_locked = True
                continue
            except ActivityCoachError as exc:
                logger.warning("Activity AI coach unavailable (%s)", type(exc).__name__)
                failed += 1
                ai_failed = True
                continue
            except ActivityPersistenceUnavailable:
                return NotificationResult(
                    status="persistence_unavailable",
                    sent=sent,
                    failed=failed + 1,
                )
            except LookupError:
                logger.warning(
                    "LINE notification: Activity subject is not persisted; delivery deferred"
                )
                failed += 1
                persistence_deferred = True
                continue
            except SQLAlchemyError as exc:
                if not is_database_connection_error(exc):
                    raise
                self._revoke_database(exc)
                return NotificationResult(
                    status="persistence_unavailable",
                    sent=sent,
                    failed=failed + 1,
                )
            if self._daily_persistence_unavailable():
                return NotificationResult(
                    status="persistence_unavailable", sent=sent, failed=failed
                )

            outcome = self._send_prepared(
                garmin_activity_id=_garmin_activity_id(candidate),
                expected_delivery=delivery,
            )
            sent += outcome.sent
            failed += outcome.failed
            skipped_locked = skipped_locked or outcome.status == "skipped_locked"
            if outcome.status == "persistence_unavailable":
                return NotificationResult(status=outcome.status, sent=sent, failed=failed)

        if persistence_deferred:
            return NotificationResult(
                status="persistence_unavailable",
                sent=sent,
                failed=failed,
            )
        if ai_failed and not sent:
            return NotificationResult(status="ai_failed", failed=failed)
        if skipped_locked and not sent and not failed:
            return NotificationResult(status="skipped_locked")
        return NotificationResult(status="done", sent=sent, failed=failed)

    def _select_work(self) -> _NotificationWork | NotificationResult:
        with self._advisory_lock():
            with self._db_session() as session:
                notified_ids = get_notified_activity_ids(session)
                all_candidates = self._all_candidates()
                all_ids = [_garmin_activity_id(candidate) for candidate in all_candidates]
                if not notified_ids:
                    logger.info(
                        "LINE notification: first run detected — seeding %d activities as baseline",
                        len(all_ids),
                    )
                    seed_baseline_notifications(session, all_ids)
                    return NotificationResult(status="seeded")

                pending = tuple(
                    _PendingActivityDelivery(
                        garmin_activity_id=notification.garmin_activity_id,
                        delivery=PreparedLineDelivery.from_model(notification),
                    )
                    for notification in list_pending_activity_notifications(
                        session,
                        limit=MAX_LINE_NOTIFICATIONS_PER_RUN,
                    )
                    if notification.garmin_activity_id is not None
                )
                available_slots = MAX_LINE_NOTIFICATIONS_PER_RUN - len(pending)
                new_candidates = [
                    candidate
                    for candidate in all_candidates
                    if _garmin_activity_id(candidate) not in notified_ids
                ]
                selected = tuple(new_candidates[:available_slots])
                deferred = len(new_candidates) - len(selected)
                if deferred:
                    logger.warning(
                        "LINE notification: capped at %d; deferring %d activities to later runs",
                        MAX_LINE_NOTIFICATIONS_PER_RUN,
                        deferred,
                    )
                if not pending and not selected:
                    logger.info("LINE notification: no new activities to notify")
                    return NotificationResult(status="no_new")
                return _NotificationWork(pending=pending, candidates=selected)

    def _prepare_candidate(self, candidate: _ActivityCandidate) -> PreparedLineDelivery:
        garmin_activity_id = _garmin_activity_id(candidate)
        spec = self._build_activity_spec(candidate, garmin_activity_id=garmin_activity_id)
        return ActivityAINotificationPreparer(
            session_factory=self._db_session,
            notification_lock=self._advisory_lock,
            generate=generate_activity_report,
            render=lambda report: format_activity_coach_messages(
                candidate.activity,
                candidate.week,
                analysis=report.report_text,
            ),
            persistence_available=lambda: not self._daily_persistence_unavailable(),
        ).prepare(spec=spec, garmin_activity_id=garmin_activity_id)

    def _build_activity_spec(
        self,
        candidate: _ActivityCandidate,
        *,
        garmin_activity_id: int,
    ) -> AIReportSpec:
        input_json = jsonable(
            {
                "activity": candidate.activity,
                "activity_week": _week_facts(candidate.week),
                "recent_training_weeks": [
                    _week_facts(week)
                    for week in self.context.get("weekly_analysis", [])
                    if isinstance(week, dict)
                ],
                "core_goal": self.core_goal,
                "training_preferences": self.training_preferences,
                "athlete_profile": _athlete_profile_input(self.context),
            }
        )
        canonical_input = json.dumps(
            input_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()[:16]
        with self._db_session() as session:
            activity = get_activity_by_garmin_id(session, garmin_activity_id)
            if activity is None:
                raise LookupError("Activity notification subject was not persisted")
            return AIReportSpec(
                idempotency_key=(
                    f"activity:{garmin_activity_id}:{ACTIVITY_PROMPT_VERSION}:{digest}"
                ),
                user_id=activity.user_id,
                report_scope="activity",
                input_json=input_json,
                prompt_version=ACTIVITY_PROMPT_VERSION,
                activity_id=activity.id,
                feature_version=ACTIVITY_CONTEXT_VERSION,
            )

    def _send_prepared(
        self,
        *,
        garmin_activity_id: int,
        expected_delivery: PreparedLineDelivery,
    ) -> _DeliveryOutcome:
        try:
            with self._advisory_lock():
                with self._db_session() as session:
                    notification = get_prepared_activity_notification(
                        session,
                        garmin_activity_id,
                    )
                    if notification is None:
                        raise RuntimeError("Prepared Activity delivery disappeared")
                    delivery = PreparedLineDelivery.from_model(notification)
                    if delivery.notification_id != expected_delivery.notification_id:
                        raise RuntimeError("Prepared Activity delivery changed unexpectedly")
                    if not delivery.should_send:
                        return _DeliveryOutcome(status="already_sent")

                    result = self.transport.send(
                        self.token,
                        self.group_id,
                        delivery.rendered_messages,
                    )
                    if not result.success:
                        self._log_send_failure(garmin_activity_id, result)
                        return _DeliveryOutcome(status="line_failed", failed=1)

                    try:
                        mark_notification_sent(session, delivery.notification_id)
                        session.commit()
                    except SQLAlchemyError as exc:
                        if not is_database_connection_error(exc):
                            raise
                        self._revoke_database(exc)
                        logger.error(
                            "LINE notification: accepted Activity %s but acknowledgement was not persisted (%s)",
                            garmin_activity_id,
                            type(exc).__name__,
                        )
                        return _DeliveryOutcome(
                            status="persistence_unavailable",
                            sent=1,
                            failed=1,
                        )
                    return _DeliveryOutcome(status="sent", sent=1)
        except _NotificationLockUnavailable:
            return _DeliveryOutcome(status="skipped_locked")
        except SQLAlchemyError as exc:
            if not is_database_connection_error(exc):
                raise
            self._revoke_database(exc)
            return _DeliveryOutcome(status="persistence_unavailable", failed=1)

    def _all_candidates(self) -> list[_ActivityCandidate]:
        candidates: list[_ActivityCandidate] = []
        for week in self.context.get("weekly_analysis", []):
            if not isinstance(week, dict):
                continue
            for activity in week.get("sessions", []):
                if isinstance(activity, dict) and activity.get("activity_id") is not None:
                    candidates.append(_ActivityCandidate(activity, week))
        candidates.sort(key=_activity_recency_key, reverse=True)
        deduplicated: list[_ActivityCandidate] = []
        seen_activity_ids: set[Any] = set()
        for candidate in candidates:
            if candidate.activity_id in seen_activity_ids:
                continue
            seen_activity_ids.add(candidate.activity_id)
            deduplicated.append(candidate)
        return deduplicated

    @contextmanager
    def _advisory_lock(self) -> Generator[None, None, None]:
        with self._lock_connection() as connection:
            if not _acquire_advisory_lock(connection):
                raise _NotificationLockUnavailable()
            try:
                yield
            finally:
                self._release_lock(connection)

    def _release_lock(self, connection: Any) -> None:
        """Release when safe; a revoked Daily Neon capability must stay untouched."""
        if self.profile is _NotificationProfile.DAILY:
            if self.database is None or not self.database.is_available():
                return
            try:
                _release_advisory_lock(connection)
            except SQLAlchemyError as exc:
                if not is_database_connection_error(exc):
                    raise
                self._revoke_database(exc)
                logger.warning(
                    "LINE notification: persistence lost while releasing advisory lock (%s)",
                    type(exc).__name__,
                )
            return

        try:
            _release_advisory_lock(connection)
        except SQLAlchemyError as exc:
            if not is_database_connection_error(exc):
                raise
            logger.warning(
                "LINE notification: advisory-lock release failed (%s)",
                type(exc).__name__,
            )

    def _daily_persistence_unavailable(self) -> bool:
        return self.profile is _NotificationProfile.DAILY and (
            self.database is None or not self.database.is_available()
        )

    def _lock_connection(self) -> ContextManager[Any]:
        if self.profile is _NotificationProfile.MANUAL:
            return _get_lock_connection()
        if self.database is None:
            raise RuntimeError("Daily Activity notification requires persistence")
        return self.database.lock_connection()

    def _db_session(self) -> ContextManager[Session]:
        if self.profile is _NotificationProfile.MANUAL:
            return _get_db_session()
        if self.database is None:
            raise RuntimeError("Daily Activity notification requires persistence")
        return self.database.session()

    def _revoke_database(self, exc: BaseException) -> None:
        if self.profile is _NotificationProfile.DAILY and self.database is not None:
            self.database.revoke(exc)

    @staticmethod
    def _log_send_failure(activity_id: int, result: LineSendResult) -> None:
        logger.error(
            "LINE notification: send FAILED for activity %s (status=%s, attempts=%d, error=%s)",
            activity_id,
            result.status_code,
            result.attempts,
            result.error_type,
        )

    @staticmethod
    def _persistence_unavailable() -> NotificationResult:
        logger.warning("LINE notification: persistence unavailable; delivery deferred")
        return NotificationResult(status="persistence_unavailable", failed=1)


def _run_notification(
    coach_context_path: str,
    *,
    profile: _NotificationProfile,
    database: NotificationDatabaseAccess | None,
    transport: _LineTransport,
    core_goal: str | None = None,
    training_preferences: str | None = None,
) -> NotificationResult:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    group_id = os.environ.get("LINE_GROUP_ID")
    if not token or not group_id:
        logger.info("LINE notification disabled: missing required environment variables")
        return NotificationResult(status="disabled")
    return _NotificationRun(
        context=_load_coach_context(coach_context_path),
        token=token,
        group_id=group_id,
        profile=profile,
        database=database,
        transport=transport,
        core_goal=core_goal,
        training_preferences=training_preferences,
    ).execute()


def run_daily_line_notification(
    coach_context_path: str,
    *,
    database: NotificationDatabaseAccess | None,
    core_goal: str | None = None,
    training_preferences: str | None = None,
) -> NotificationResult:
    """Run Daily Activity notifications; DB unavailability defers LINE delivery."""
    return _run_notification(
        coach_context_path,
        profile=_NotificationProfile.DAILY,
        database=database,
        transport=_ProductionLineTransport(),
        core_goal=core_goal,
        training_preferences=training_preferences,
    )


def run_line_notification(
    coach_context_path: str,
    *,
    core_goal: str | None = None,
    training_preferences: str | None = None,
) -> NotificationResult:
    """Run manual Activity notifications with the same persistent delivery contract."""
    return _run_notification(
        coach_context_path,
        profile=_NotificationProfile.MANUAL,
        database=None,
        transport=_ProductionLineTransport(),
        core_goal=core_goal,
        training_preferences=training_preferences,
    )
