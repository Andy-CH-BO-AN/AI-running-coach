from __future__ import annotations

import io
import logging
import threading
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generator

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from src.db import session as database_session
from src.db.settings import (
    get_cloud_database_url,
    get_database_mode,
    is_database_authentication_error,
    is_database_configuration_error,
    is_database_connection_error,
)
from src.notifications.notifier import (
    NotificationDatabaseAccess,
    NotificationResult,
    run_daily_line_notification,
)
from src.pipeline import runner
from src.pipeline.activity_payloads import ActivityPayloadProvider
from src.pipeline.goal_prompt import GoalPromptOverrides
from src.services.artifacts import pipeline_artifact_paths

logger = logging.getLogger(__name__)

NORMAL_ACTIVITY_WINDOW = 75
DEGRADED_ACTIVITY_WINDOW = 10
MIGRATION_ATTEMPTS = 3
MIGRATION_BACKOFF_SECONDS = (10, 20)
REPO_ROOT = Path(__file__).resolve().parents[2]


class DailyRunMode(str, Enum):
    NORMAL = "normal"
    DEGRADED = "degraded"
    PERSISTENCE_LOSS = "persistence_loss"

    def __str__(self) -> str:
        return self.value


class DailyRunBlockReason(str, Enum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    MIGRATION = "migration"
    PERSISTENCE = "persistence"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class DailyRunResult:
    mode: DailyRunMode
    report_path: Path | None
    notification: NotificationResult | None


class DailyRunBlocked(RuntimeError):
    def __init__(self, reason: DailyRunBlockReason, safe_message: str) -> None:
        super().__init__(safe_message)
        self.reason = reason
        self.safe_message = safe_message


class _NeonAccessRevoked(RuntimeError):
    pass


@dataclass
class _RunState:
    mode: DailyRunMode
    activity_window: int

    def lose_persistence(self) -> None:
        if self.mode is DailyRunMode.NORMAL:
            self.mode = DailyRunMode.PERSISTENCE_LOSS


class _NeonGate:
    """Sole application-level Neon capability for one Cloud Daily Run."""

    def __init__(
        self,
        state: _RunState,
        *,
        session_factory: Callable[[], Any] | None = None,
        engine_factory: Callable[[], Any] | None = None,
        disposer: Callable[[], None] | None = None,
    ) -> None:
        self._state = state
        self._session_factory = session_factory or database_session.SessionLocal
        self._engine_factory = engine_factory or database_session.get_engine
        self._disposer = disposer or database_session.dispose_database_connections
        self._lock = threading.RLock()
        self._revoked = False
        self._disposed = False
        self._active_sessions: set[Any] = set()
        self._active_connections: set[Any] = set()
        self._invalidated_handle_ids: set[int] = set()

    def is_available(self) -> bool:
        with self._lock:
            return not self._revoked

    def _require_available(self) -> None:
        if not self.is_available():
            raise _NeonAccessRevoked(
                "Neon access was revoked for this Cloud Daily Run."
            )

    @staticmethod
    def _invalidate(handle: Any) -> bool:
        try:
            handle.invalidate()
        except Exception as exc:  # Cleanup must not expose driver details or reopen Neon.
            logger.warning(
                "Daily Run: local Neon handle invalidation failed (%s)",
                type(exc).__name__,
            )
            return False
        return True

    def _register_handle(self, handle: Any, active_handles: set[Any]) -> bool:
        with self._lock:
            if self._revoked:
                return False
            active_handles.add(handle)
            return True

    def _close_losing_race_handle(self, handle: Any) -> None:
        if not self._invalidate(handle):
            return
        try:
            handle.close()
        except Exception as exc:
            logger.warning(
                "Daily Run: local Neon handle close failed (%s)",
                type(exc).__name__,
            )

    def _close_registered_handle(self, handle: Any, active_handles: set[Any]) -> None:
        with self._lock:
            should_close = not self._revoked or id(handle) in self._invalidated_handle_ids
        try:
            if should_close:
                handle.close()
        except SQLAlchemyError as exc:
            self._revoke_if_transient(exc)
            if not is_database_connection_error(exc):
                raise
        finally:
            with self._lock:
                active_handles.discard(handle)
                self._invalidated_handle_ids.discard(id(handle))

    def revoke(self, _cause: BaseException | None = None) -> None:
        with self._lock:
            if self._revoked:
                return
            self._revoked = True
            self._state.lose_persistence()
            for session in tuple(self._active_sessions):
                if self._invalidate(session):
                    self._invalidated_handle_ids.add(id(session))
            for connection in tuple(self._active_connections):
                if self._invalidate(connection):
                    self._invalidated_handle_ids.add(id(connection))
            if self._disposed:
                return
            self._disposed = True
        try:
            self._disposer()
        except Exception as exc:  # Availability is already revoked; keep cleanup fail-safe.
            logger.warning(
                "Daily Run: Neon engine disposal failed (%s)",
                type(exc).__name__,
            )

        logger.warning(
            "Daily Run entered Persistence-loss mode; Neon access is revoked for the rest of this run."
        )

    def _revoke_if_transient(self, exc: SQLAlchemyError) -> None:
        if is_database_connection_error(exc):
            self.revoke(exc)

    @contextmanager
    def session(self) -> Generator[Any, None, None]:
        self._require_available()
        try:
            session = self._session_factory()
        except SQLAlchemyError as exc:
            self._revoke_if_transient(exc)
            raise

        if not self._register_handle(session, self._active_sessions):
            self._close_losing_race_handle(session)
            raise _NeonAccessRevoked(
                "Neon access was revoked for this Cloud Daily Run."
            )
        try:
            yield session
        except SQLAlchemyError as exc:
            self._revoke_if_transient(exc)
            raise
        finally:
            self._close_registered_handle(session, self._active_sessions)

    @contextmanager
    def connection(self) -> Generator[Any, None, None]:
        self._require_available()
        try:
            connection = self._engine_factory().connect()
        except SQLAlchemyError as exc:
            self._revoke_if_transient(exc)
            raise

        if not self._register_handle(connection, self._active_connections):
            self._close_losing_race_handle(connection)
            raise _NeonAccessRevoked(
                "Neon access was revoked for this Cloud Daily Run."
            )
        try:
            yield connection
        except SQLAlchemyError as exc:
            self._revoke_if_transient(exc)
            raise
        finally:
            self._close_registered_handle(connection, self._active_connections)


def _validate_cloud_configuration() -> None:
    try:
        if get_database_mode() != "cloud":
            raise ValueError("Cloud Daily Run requires DATABASE_MODE=cloud.")
        get_cloud_database_url(purpose="app")
        get_cloud_database_url(purpose="direct")
    except (ArgumentError, ValueError):
        raise DailyRunBlocked(
            DailyRunBlockReason.CONFIGURATION,
            "Cloud Daily Run database configuration is missing or invalid.",
        ) from None


def _run_migration_upgrade() -> None:
    captured_output = io.StringIO()
    config = Config(str(REPO_ROOT / "alembic.ini"), stdout=captured_output)
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.attributes["database_url"] = get_cloud_database_url(purpose="direct")
    config.attributes["skip_logging_config"] = True
    with redirect_stdout(captured_output), redirect_stderr(captured_output):
        command.upgrade(config, "head")


def _blocked_preflight(exc: BaseException) -> DailyRunBlocked:
    if is_database_authentication_error(exc):
        return DailyRunBlocked(
            DailyRunBlockReason.AUTHENTICATION,
            "Cloud Daily Run database authentication was rejected.",
        )
    if is_database_configuration_error(exc):
        return DailyRunBlocked(
            DailyRunBlockReason.CONFIGURATION,
            "Cloud Daily Run database configuration was rejected.",
        )
    return DailyRunBlocked(
        DailyRunBlockReason.MIGRATION,
        "Cloud Daily Run database migration failed closed.",
    )


def _select_initial_state() -> _RunState:
    for attempt in range(1, MIGRATION_ATTEMPTS + 1):
        print(f"Daily Run: database migration attempt {attempt}/{MIGRATION_ATTEMPTS}.")
        try:
            _run_migration_upgrade()
        except Exception as exc:
            if not is_database_connection_error(exc):
                raise _blocked_preflight(exc) from None
            if attempt == MIGRATION_ATTEMPTS:
                print(
                    "Daily Run: Neon unavailable after three migration attempts; "
                    "entering Degraded mode."
                )
                return _RunState(
                    mode=DailyRunMode.DEGRADED,
                    activity_window=DEGRADED_ACTIVITY_WINDOW,
                )

            backoff = MIGRATION_BACKOFF_SECONDS[attempt - 1]
            print(f"Daily Run: migration retry scheduled in {backoff} seconds.")
            time.sleep(backoff)
            continue

        print("Daily Run: database migration succeeded; entering Normal mode.")
        return _RunState(
            mode=DailyRunMode.NORMAL,
            activity_window=NORMAL_ACTIVITY_WINDOW,
        )

    raise AssertionError("Migration attempt loop must return or raise.")


def _block_runtime_persistence_failure() -> DailyRunBlocked:
    return DailyRunBlocked(
        DailyRunBlockReason.PERSISTENCE,
        "Cloud Daily Run persistence failed closed.",
    )


def execute_daily_run(
    *,
    goal_overrides: GoalPromptOverrides | None = None,
) -> DailyRunResult:
    """Execute one cloud-scheduled Daily Run behind a single policy interface."""
    _validate_cloud_configuration()
    state = _select_initial_state()
    timestamp = runner._build_timestamp()
    print(
        f"Daily Run: starting {state.mode.value} pipeline with "
        f"Activity window={state.activity_window}."
    )

    gate: _NeonGate | None = None
    if state.mode is DailyRunMode.DEGRADED:
        provider = ActivityPayloadProvider(
            raw_data_dir=runner.RAW_DATA_DIR,
            database_available=lambda: False,
        )
        raw_activities, user_data = provider.fetch_without_database(
            activity_limit=state.activity_window,
            timestamp=timestamp,
        )
    else:
        gate = _NeonGate(state)
        provider = ActivityPayloadProvider(
            session_factory=gate.session,
            database_available=gate.is_available,
            preserve_activity_window_on_connection_loss=True,
            raw_data_dir=runner.RAW_DATA_DIR,
        )
        try:
            raw_activities, user_data = provider.load_or_fetch(
                activity_limit=state.activity_window,
                fetch_limit=state.activity_window,
                timestamp=timestamp,
            )
        except SQLAlchemyError as exc:
            if not is_database_connection_error(exc):
                raise _block_runtime_persistence_failure() from None
            gate.revoke(exc)
            raw_activities, user_data = provider.fetch_without_database(
                activity_limit=state.activity_window,
                timestamp=timestamp,
            )

    report_path = runner._run_pipeline_from_payloads(
        timestamp=timestamp,
        raw_activities=raw_activities,
        user_data=user_data,
        goal_overrides=goal_overrides,
    )
    if report_path is None:
        result = DailyRunResult(
            mode=state.mode,
            report_path=None,
            notification=None,
        )
        print(f"Daily Run: completed in {result.mode.value} mode without a report.")
        return result

    database_access = None
    if gate is not None and gate.is_available():
        database_access = NotificationDatabaseAccess(
            is_available=gate.is_available,
            session=gate.session,
            lock_connection=gate.connection,
            revoke=gate.revoke,
        )

    coach_context_path = pipeline_artifact_paths(
        timestamp,
        processed_dir=runner.PROCESSED_DATA_DIR,
        output_dir=runner.OUTPUT_DIR,
    )["coach_context"]
    try:
        notification = run_daily_line_notification(
            str(coach_context_path),
            database=database_access,
        )
    except SQLAlchemyError:
        raise _block_runtime_persistence_failure() from None

    result = DailyRunResult(
        mode=state.mode,
        report_path=report_path,
        notification=notification,
    )
    print(
        f"Daily Run: completed in {result.mode.value} mode; "
        f"notification={notification.status}."
    )
    return result
