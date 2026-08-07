from __future__ import annotations

from contextlib import contextmanager
from inspect import signature
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from src.db.settings import is_database_connection_error
from src.pipeline import activity_payloads, daily_run
from src.services import report_generator


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


def test_persistence_loss_merges_incremental_garmin_updates_into_materialized_window(
    monkeypatch,
):
    available = {"value": True}
    existing = [
        {"activity_id": activity_id, "date": "2026-08-01"}
        for activity_id in range(1, 76)
    ]
    fetched = [{"activity_id": 100, "date": "2026-08-01"}]
    calls = {"fetch": 0, "second_db_read": 0, "direct_fetch": 0}

    @contextmanager
    def session_factory():
        yield object()

    provider = activity_payloads.ActivityPayloadProvider(
        session_factory=session_factory,
        database_available=lambda: available["value"],
        preserve_activity_window_on_connection_loss=True,
    )

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
        provider,
        "_get_latest_activity_date",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        provider,
        "_load_recent_raw_activities",
        lambda *_args, **_kwargs: list(existing),
    )
    monkeypatch.setattr(
        provider,
        "_load_latest_user_data",
        lambda *_args, **_kwargs: {"resting_heart_rate": 45, "source": "db"},
    )

    def fetch_updates(*_args, **_kwargs):
        calls["fetch"] += 1
        return {
            "activities": list(fetched),
            "user_data": {"source": "garmin", "max_heart_rate": 210},
        }

    def fail_sync(*_args, **_kwargs):
        available["value"] = False
        raise _connection_error(sqlstate="08006")

    def second_db_read(*_args, **_kwargs):
        calls["second_db_read"] += 1
        pytest.fail("Persistence-loss must not reopen Neon for a second DB read")

    def direct_fetch(*_args, **_kwargs):
        calls["direct_fetch"] += 1
        pytest.fail("Already-fetched Garmin updates must be reused")

    monkeypatch.setattr(provider, "_fetch_garmin_updates", fetch_updates)
    monkeypatch.setattr(provider, "_sync_garmin_to_db", fail_sync)
    monkeypatch.setattr(provider, "_load_existing_db_payloads", second_db_read)
    monkeypatch.setattr(provider, "fetch_without_database", direct_fetch)

    raw_activities, user_data = provider.load_or_fetch(
        activity_limit=75,
        fetch_limit=75,
        timestamp="20260807",
    )

    ids = [activity["activity_id"] for activity in raw_activities]
    assert len(ids) == 75
    assert ids[0] == 100
    assert 1 not in ids
    assert set(ids[1:]) == set(range(2, 76))
    assert user_data == {
        "resting_heart_rate": 45,
        "source": "garmin",
        "max_heart_rate": 210,
    }
    assert calls == {"fetch": 1, "second_db_read": 0, "direct_fetch": 0}


def test_connection_classifier_ignores_unrelated_implicit_exception_context():
    transient = _connection_error(sqlstate="08006")

    try:
        raise transient
    except OperationalError:
        try:
            raise IntegrityError("INSERT", {}, Exception("constraint failed"))
        except IntegrityError as fatal:
            assert fatal.__context__ is transient
            assert is_database_connection_error(fatal) is False


def test_cloud_configuration_does_not_hide_unexpected_programming_errors(monkeypatch):
    def explode() -> str:
        raise RuntimeError("unexpected validation bug")

    monkeypatch.setattr(daily_run, "get_database_mode", explode)

    with pytest.raises(RuntimeError, match="unexpected validation bug"):
        daily_run._validate_cloud_configuration()


def test_lazy_coach_wrapper_keeps_explicit_public_signature():
    parameters = signature(report_generator.coach).parameters

    assert list(parameters) == [
        "data",
        "user_data",
        "deterministic_context",
        "goal_path",
        "goal_text",
    ]
    assert all(parameter.kind.name != "VAR_KEYWORD" for parameter in parameters.values())
    assert all(parameter.kind.name != "VAR_POSITIONAL" for parameter in parameters.values())
