from __future__ import annotations

import io
import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from src.db import session as database_session
from src.notifications.notifier import NotificationResult
from src.pipeline import activity_payloads, daily_run


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily_pipeline.yml"


class _DriverError(Exception):
    def __init__(self, message: str, *, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def _connection_error(
    message: str = "connection refused",
    *,
    sqlstate: str | None = None,
) -> OperationalError:
    return OperationalError(
        "SELECT 1",
        {},
        _DriverError(message, sqlstate=sqlstate),
    )


@pytest.fixture(autouse=True)
def cloud_configuration(monkeypatch):
    monkeypatch.setenv("DATABASE_MODE", "cloud")
    monkeypatch.setenv(
        "NEON_DATABASE_URL",
        "postgresql://daily:secret@pooler.example.invalid/coach",
    )
    monkeypatch.setenv(
        "NEON_DATABASE_DIRECT_URL",
        "postgresql://daily:secret@direct.example.invalid/coach",
    )


class _PayloadProvider:
    direct_limits: list[int] = []
    database_limits: list[int] = []

    def __init__(self, **_kwargs) -> None:
        pass

    def load_or_fetch(self, activity_limit: int, fetch_limit: int, timestamp: str):
        self.database_limits.append(activity_limit)
        assert fetch_limit == activity_limit
        assert timestamp == "20260807"
        return ([{"activity_id": 1}], {})

    def fetch_without_database(self, activity_limit: int, timestamp: str):
        self.direct_limits.append(activity_limit)
        assert timestamp == "20260807"
        return ([{"activity_id": 1}], {})


def _stub_report_pipeline(monkeypatch) -> None:
    _PayloadProvider.direct_limits = []
    _PayloadProvider.database_limits = []
    monkeypatch.setattr(daily_run, "ActivityPayloadProvider", _PayloadProvider)
    monkeypatch.setattr(daily_run.runner, "_build_timestamp", lambda: "20260807")
    monkeypatch.setattr(
        daily_run.runner,
        "_run_pipeline_from_payloads",
        lambda **_kwargs: None,
    )


def _migration_sequence(monkeypatch, outcomes: list[BaseException | None]) -> list[int]:
    remaining = iter(outcomes)
    attempts: list[int] = []

    def upgrade() -> None:
        attempts.append(len(attempts) + 1)
        outcome = next(remaining)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(daily_run, "_run_migration_upgrade", upgrade)
    return attempts


def test_first_migration_success_enters_normal_mode(monkeypatch):
    _stub_report_pipeline(monkeypatch)
    attempts = _migration_sequence(monkeypatch, [None])
    sleeps: list[int] = []
    monkeypatch.setattr(daily_run.time, "sleep", sleeps.append)

    result = daily_run.execute_daily_run()

    assert result.mode is daily_run.DailyRunMode.NORMAL
    assert attempts == [1]
    assert sleeps == []
    assert _PayloadProvider.database_limits == [75]
    assert _PayloadProvider.direct_limits == []


def test_third_migration_success_preserves_backoff_and_normal_mode(monkeypatch):
    _stub_report_pipeline(monkeypatch)
    transient = _connection_error(sqlstate="57P03")
    attempts = _migration_sequence(monkeypatch, [transient, transient, None])
    sleeps: list[int] = []
    monkeypatch.setattr(daily_run.time, "sleep", sleeps.append)

    result = daily_run.execute_daily_run()

    assert result.mode is daily_run.DailyRunMode.NORMAL
    assert attempts == [1, 2, 3]
    assert sleeps == [10, 20]
    assert _PayloadProvider.database_limits == [75]


@pytest.mark.parametrize(
    "error",
    [
        _connection_error(sqlstate="08006"),
        _connection_error(sqlstate="57P01"),
        _connection_error(sqlstate="57P02"),
        _connection_error(sqlstate="57P03"),
        _connection_error("the database system is starting up"),
        _connection_error("terminating connection due to administrator command"),
        _connection_error("connection timeout expired"),
        _connection_error("connect timeout"),
        _connection_error("SSL transport lost its connection"),
    ],
)
def test_three_transient_failures_enter_degraded_mode(monkeypatch, error):
    _stub_report_pipeline(monkeypatch)
    attempts = _migration_sequence(monkeypatch, [error, error, error])
    sleeps: list[int] = []
    monkeypatch.setattr(daily_run.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        database_session,
        "SessionLocal",
        lambda: pytest.fail("Degraded mode must not construct a Neon session"),
    )

    result = daily_run.execute_daily_run()

    assert result.mode is daily_run.DailyRunMode.DEGRADED
    assert attempts == [1, 2, 3]
    assert sleeps == [10, 20]
    assert _PayloadProvider.database_limits == []
    assert _PayloadProvider.direct_limits == [10]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (
            _connection_error(
                "password authentication failed for user",
                sqlstate="28P01",
            ),
            daily_run.DailyRunBlockReason.AUTHENTICATION,
        ),
        (
            _connection_error(
                "canceling statement due to statement timeout",
                sqlstate="57014",
            ),
            daily_run.DailyRunBlockReason.MIGRATION,
        ),
        (
            IntegrityError("ALTER TABLE", {}, Exception("constraint failed")),
            daily_run.DailyRunBlockReason.MIGRATION,
        ),
        (
            _connection_error("certificate verify failed"),
            daily_run.DailyRunBlockReason.CONFIGURATION,
        ),
    ],
)
def test_nontransient_preflight_failures_stop_immediately(monkeypatch, error, reason):
    _stub_report_pipeline(monkeypatch)
    attempts = _migration_sequence(monkeypatch, [error])
    sleeps: list[int] = []
    monkeypatch.setattr(daily_run.time, "sleep", sleeps.append)

    with pytest.raises(daily_run.DailyRunBlocked) as raised:
        daily_run.execute_daily_run()

    assert raised.value.reason is reason
    assert attempts == [1]
    assert sleeps == []
    assert _PayloadProvider.database_limits == []
    assert _PayloadProvider.direct_limits == []


def test_invalid_cloud_configuration_stops_before_migration(monkeypatch):
    _stub_report_pipeline(monkeypatch)
    monkeypatch.setenv("DATABASE_MODE", "local")
    migration = pytest.fail
    monkeypatch.setattr(daily_run, "_run_migration_upgrade", migration)

    with pytest.raises(daily_run.DailyRunBlocked) as raised:
        daily_run.execute_daily_run()

    assert raised.value.reason is daily_run.DailyRunBlockReason.CONFIGURATION


def test_invalid_cloud_url_is_reported_as_safe_configuration_block(monkeypatch):
    _stub_report_pipeline(monkeypatch)
    monkeypatch.setenv("NEON_DATABASE_DIRECT_URL", "not a valid postgres url %")
    monkeypatch.setattr(
        daily_run,
        "_run_migration_upgrade",
        lambda: pytest.fail("migration must not start with an invalid URL"),
    )

    with pytest.raises(daily_run.DailyRunBlocked) as raised:
        daily_run.execute_daily_run()

    assert raised.value.reason is daily_run.DailyRunBlockReason.CONFIGURATION
    assert "not a valid" not in raised.value.safe_message


def test_preflight_output_and_error_are_secret_safe(monkeypatch, capsys):
    _stub_report_pipeline(monkeypatch)
    secret = "postgresql://owner:super-secret@db.example.invalid/coach"
    error = _connection_error(f"password authentication failed; dsn={secret}", sqlstate="28P01")
    _migration_sequence(monkeypatch, [error])

    with pytest.raises(daily_run.DailyRunBlocked) as raised:
        daily_run.execute_daily_run()

    output = capsys.readouterr()
    assert secret not in output.out
    assert secret not in output.err
    assert secret not in raised.value.safe_message
    assert "super-secret" not in str(raised.value)


def test_programmatic_alembic_adapter_uses_absolute_paths_and_discards_output(
    monkeypatch,
    capsys,
):
    secret = "postgresql://owner:adapter-secret@example.invalid/coach"
    captured = {}

    def upgrade(config, revision):
        captured["config_file"] = config.config_file_name
        captured["script_location"] = config.get_main_option("script_location")
        captured["database_url"] = config.attributes["database_url"]
        captured["skip_logging_config"] = config.attributes["skip_logging_config"]
        captured["revision"] = revision
        print(secret)
        print(secret, file=sys.stderr)

    monkeypatch.setattr(daily_run.command, "upgrade", upgrade)
    monkeypatch.setenv(
        "ALEMBIC_DATABASE_URL",
        "postgresql://wrong:wrong@local.example.invalid/wrong",
    )
    monkeypatch.setenv("DATABASE_MIGRATION_TARGET", "local")

    daily_run._run_migration_upgrade()

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert Path(captured["config_file"]).is_absolute()
    assert Path(captured["script_location"]).is_absolute()
    assert captured["database_url"].startswith("postgresql+psycopg://daily:")
    assert "direct.example.invalid" in captured["database_url"]
    assert captured["skip_logging_config"] is True
    assert captured["revision"] == "head"


def test_real_alembic_environment_preserves_application_logging(monkeypatch):
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    sentinel = logging.StreamHandler(io.StringIO())
    root_logger.handlers = [sentinel]
    root_logger.setLevel(logging.INFO)

    config = daily_run.Config(
        str(daily_run.REPO_ROOT / "alembic.ini"),
        stdout=io.StringIO(),
    )
    config.set_main_option(
        "script_location",
        str(daily_run.REPO_ROOT / "alembic"),
    )
    config.attributes["database_url"] = (
        "postgresql+psycopg://offline:p%40ss@example.invalid/coach"
    )
    config.attributes["skip_logging_config"] = True
    monkeypatch.setenv(
        "ALEMBIC_DATABASE_URL",
        "postgresql://wrong:wrong@local.example.invalid/wrong",
    )
    monkeypatch.setenv("DATABASE_MIGRATION_TARGET", "local")

    try:
        with daily_run.redirect_stdout(io.StringIO()), daily_run.redirect_stderr(io.StringIO()):
            daily_run.command.upgrade(config, "head", sql=True)
        assert root_logger.handlers == [sentinel]
        assert root_logger.handlers[0].stream is sentinel.stream
        assert root_logger.level == logging.INFO
        assert config.get_main_option("sqlalchemy.url") == config.attributes["database_url"]
    finally:
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)


def test_wrapped_transient_migration_error_still_retries(monkeypatch):
    _stub_report_pipeline(monkeypatch)
    transient = _connection_error(sqlstate="57P03")
    try:
        raise transient
    except OperationalError as cause:
        wrapped = RuntimeError("migration adapter wrapper")
        wrapped.__cause__ = cause
    attempts = _migration_sequence(monkeypatch, [wrapped, None])
    sleeps: list[int] = []
    monkeypatch.setattr(daily_run.time, "sleep", sleeps.append)

    result = daily_run.execute_daily_run()

    assert result.mode is daily_run.DailyRunMode.NORMAL
    assert attempts == [1, 2]
    assert sleeps == [10]


class _TrackedHandle:
    def __init__(self) -> None:
        self.invalidated = 0
        self.closed = 0

    def invalidate(self) -> None:
        self.invalidated += 1

    def close(self) -> None:
        self.closed += 1


class _TrackedEngine:
    def __init__(self, connection: _TrackedHandle) -> None:
        self.connection = connection
        self.connect_calls = 0

    def connect(self) -> _TrackedHandle:
        self.connect_calls += 1
        return self.connection


def test_neon_gate_revokes_active_handles_once_and_blocks_locally():
    state = daily_run._RunState(daily_run.DailyRunMode.NORMAL, 75)
    session = _TrackedHandle()
    connection = _TrackedHandle()
    engine = _TrackedEngine(connection)
    disposed: list[bool] = []
    session_calls: list[bool] = []

    def session_factory():
        session_calls.append(True)
        return session

    gate = daily_run._NeonGate(
        state,
        session_factory=session_factory,
        engine_factory=lambda: engine,
        disposer=lambda: disposed.append(True),
    )

    with gate.connection():
        with gate.session():
            gate.revoke(_connection_error())

    gate.revoke(_connection_error())

    assert state.mode is daily_run.DailyRunMode.PERSISTENCE_LOSS
    assert state.activity_window == 75
    assert session.invalidated == 1
    assert connection.invalidated == 1
    assert session.closed == 1
    assert connection.closed == 1
    assert disposed == [True]
    with pytest.raises(daily_run._NeonAccessRevoked):
        with gate.session():
            pass
    assert session_calls == [True]
    assert engine.connect_calls == 1


def test_neon_gate_does_not_close_handle_when_invalidation_fails():
    class FailingInvalidationHandle(_TrackedHandle):
        def invalidate(self) -> None:
            self.invalidated += 1
            raise RuntimeError("invalidate failed")

    state = daily_run._RunState(daily_run.DailyRunMode.NORMAL, 75)
    session = FailingInvalidationHandle()
    gate = daily_run._NeonGate(
        state,
        session_factory=lambda: session,
        disposer=lambda: None,
    )

    with gate.session():
        gate.revoke(_connection_error())

    assert state.mode is daily_run.DailyRunMode.PERSISTENCE_LOSS
    assert session.invalidated == 1
    assert session.closed == 0


def test_neon_gate_cleans_handle_created_during_revocation_race():
    state = daily_run._RunState(daily_run.DailyRunMode.NORMAL, 75)
    session = _TrackedHandle()
    holder = {}
    disposed: list[bool] = []

    def session_factory():
        holder["gate"].revoke(_connection_error())
        return session

    gate = daily_run._NeonGate(
        state,
        session_factory=session_factory,
        disposer=lambda: disposed.append(True),
    )
    holder["gate"] = gate

    with pytest.raises(daily_run._NeonAccessRevoked):
        with gate.session():
            pass

    assert state.mode is daily_run.DailyRunMode.PERSISTENCE_LOSS
    assert session.invalidated == 1
    assert session.closed == 1
    assert disposed == [True]


class _FakeSession(_TrackedHandle):
    pass


def _prepare_runtime_loss_test(monkeypatch):
    _migration_sequence(monkeypatch, [None])
    monkeypatch.setattr(daily_run.runner, "_build_timestamp", lambda: "20260807")
    captured: dict[str, object] = {}

    def pipeline_from_payloads(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(daily_run.runner, "_run_pipeline_from_payloads", pipeline_from_payloads)
    fake_session = _FakeSession()
    monkeypatch.setattr(database_session, "SessionLocal", lambda: fake_session)
    disposed: list[bool] = []
    monkeypatch.setattr(
        database_session,
        "dispose_database_connections",
        lambda: disposed.append(True),
    )
    return captured, fake_session, disposed


def test_runtime_loss_before_garmin_fetch_keeps_seventy_five_window(monkeypatch):
    captured, fake_session, disposed = _prepare_runtime_loss_test(monkeypatch)
    direct_calls: list[tuple[int, str]] = []
    monkeypatch.setattr(
        activity_payloads,
        "get_or_create_default_user",
        lambda _session: (_ for _ in ()).throw(_connection_error()),
    )

    def direct_fetch(self, activity_limit: int, timestamp: str):
        direct_calls.append((activity_limit, timestamp))
        return ([{"activity_id": 75}], {"source": "direct"})

    monkeypatch.setattr(
        activity_payloads.ActivityPayloadProvider,
        "fetch_without_database",
        direct_fetch,
    )

    result = daily_run.execute_daily_run()

    assert result.mode is daily_run.DailyRunMode.PERSISTENCE_LOSS
    assert direct_calls == [(75, "20260807")]
    assert captured["raw_activities"] == [{"activity_id": 75}]
    assert fake_session.invalidated == 1
    assert disposed == [True]


def test_runtime_loss_after_garmin_fetch_reuses_payload_without_second_neon_read(monkeypatch):
    captured, fake_session, disposed = _prepare_runtime_loss_test(monkeypatch)
    fetched = {
        "activities": [{"activity_id": 80}, {"activity_id": 79}],
        "user_data": {"source": "garmin"},
    }
    monkeypatch.setattr(
        activity_payloads,
        "get_or_create_default_user",
        lambda _session: SimpleNamespace(id="user-1"),
    )
    monkeypatch.setattr(
        activity_payloads,
        "get_recent_max_heart_rate",
        lambda *_args, **_kwargs: 190,
    )
    monkeypatch.setattr(
        activity_payloads.ActivityPayloadProvider,
        "_get_latest_activity_date",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        activity_payloads.ActivityPayloadProvider,
        "_fetch_garmin_updates",
        lambda *_args, **_kwargs: fetched,
    )
    monkeypatch.setattr(
        activity_payloads.ActivityPayloadProvider,
        "_sync_garmin_to_db",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_connection_error()),
    )
    second_read = []
    monkeypatch.setattr(
        activity_payloads.ActivityPayloadProvider,
        "_load_existing_db_payloads",
        lambda *_args, **_kwargs: second_read.append(True),
    )

    result = daily_run.execute_daily_run()

    assert result.mode is daily_run.DailyRunMode.PERSISTENCE_LOSS
    assert captured["raw_activities"] == fetched["activities"]
    assert captured["user_data"] == fetched["user_data"]
    assert second_read == []
    assert fake_session.invalidated == 1
    assert disposed == [True]


def test_activity_persistence_loss_forces_later_notification_to_stay_stateless(
    monkeypatch,
    tmp_path,
):
    _migration_sequence(monkeypatch, [None])
    monkeypatch.setattr(daily_run.runner, "_build_timestamp", lambda: "20260807")
    fake_session = _FakeSession()
    monkeypatch.setattr(database_session, "SessionLocal", lambda: fake_session)
    monkeypatch.setattr(
        database_session,
        "dispose_database_connections",
        lambda: None,
    )
    monkeypatch.setattr(
        activity_payloads,
        "get_or_create_default_user",
        lambda _session: (_ for _ in ()).throw(_connection_error()),
    )
    monkeypatch.setattr(
        activity_payloads.ActivityPayloadProvider,
        "fetch_without_database",
        lambda *_args, **_kwargs: ([{"activity_id": 75}], {}),
    )
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        daily_run.runner,
        "_run_pipeline_from_payloads",
        lambda **_kwargs: report_path,
    )
    monkeypatch.setattr(
        daily_run,
        "pipeline_artifact_paths",
        lambda *_args, **_kwargs: {"coach_context": tmp_path / "context.json"},
    )
    notification_database = []

    def notify(_path, *, database):
        notification_database.append(database)
        return NotificationResult(status="stateless_done", sent=1)

    monkeypatch.setattr(daily_run, "run_daily_line_notification", notify)

    result = daily_run.execute_daily_run()

    assert result.mode is daily_run.DailyRunMode.PERSISTENCE_LOSS
    assert notification_database == [None]


def test_nontransient_runtime_database_failure_is_typed_and_fails_closed(monkeypatch):
    _stub_report_pipeline(monkeypatch)
    _migration_sequence(monkeypatch, [None])

    class FailingProvider(_PayloadProvider):
        def load_or_fetch(self, activity_limit: int, fetch_limit: int, timestamp: str):
            raise IntegrityError("INSERT", {}, Exception("constraint failed"))

        def fetch_without_database(self, activity_limit: int, timestamp: str):
            pytest.fail("nontransient DB failure must not use direct Garmin fallback")

    monkeypatch.setattr(daily_run, "ActivityPayloadProvider", FailingProvider)

    with pytest.raises(daily_run.DailyRunBlocked) as raised:
        daily_run.execute_daily_run()

    assert raised.value.reason is daily_run.DailyRunBlockReason.PERSISTENCE


def test_non_database_runtime_failure_propagates_without_mode_transition(monkeypatch):
    _stub_report_pipeline(monkeypatch)
    _migration_sequence(monkeypatch, [None])

    class FailingProvider(_PayloadProvider):
        def load_or_fetch(self, activity_limit: int, fetch_limit: int, timestamp: str):
            raise ValueError("Garmin payload failed")

    monkeypatch.setattr(daily_run, "ActivityPayloadProvider", FailingProvider)

    with pytest.raises(ValueError, match="Garmin payload failed"):
        daily_run.execute_daily_run()


def test_final_result_exposes_notification_persistence_loss(monkeypatch, tmp_path):
    _stub_report_pipeline(monkeypatch)
    _migration_sequence(monkeypatch, [None])
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        daily_run.runner,
        "_run_pipeline_from_payloads",
        lambda **_kwargs: report_path,
    )
    monkeypatch.setattr(
        daily_run,
        "pipeline_artifact_paths",
        lambda *_args, **_kwargs: {"coach_context": tmp_path / "context.json"},
    )

    def notify(_path, *, database):
        database.revoke(_connection_error())
        return NotificationResult(status="persistence_loss_done", sent=1)

    monkeypatch.setattr(daily_run, "run_daily_line_notification", notify)

    result = daily_run.execute_daily_run()

    assert result.mode is daily_run.DailyRunMode.PERSISTENCE_LOSS
    assert result.report_path == report_path
    assert result.notification == NotificationResult(
        status="persistence_loss_done",
        sent=1,
    )


def test_workflow_uses_one_daily_python_command_without_ambient_mode_handoff():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m src.scripts.run_daily_pipeline" in workflow
    assert "scripts/run_neon_migrations.sh" not in workflow
    assert "python run_pipeline.py" not in workflow
    assert "DATABASE_AVAILABLE" not in workflow
    assert "GARMIN_ACTIVITY_LIMIT" not in workflow


def test_cloud_configuration_does_not_hide_unexpected_programming_errors(monkeypatch):
    def explode() -> str:
        raise RuntimeError("unexpected validation bug")

    monkeypatch.setattr(daily_run, "get_database_mode", explode)

    with pytest.raises(RuntimeError, match="unexpected validation bug"):
        daily_run._validate_cloud_configuration()
