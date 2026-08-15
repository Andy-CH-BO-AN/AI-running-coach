from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy.exc import OperationalError

from src.pipeline import weekly_report as weekly_pipeline
from src.scripts import run_weekly_training_report as weekly_cli
from src.services.weekly_training_report import WeeklyTrainingReportResult


def test_weekly_cli_passes_explicit_date_and_prints_safe_result(monkeypatch, capsys):
    captured = {}

    def execute(*, today, retry_only):
        captured["today"] = today
        captured["retry_only"] = retry_only
        return WeeklyTrainingReportResult(status="sent", sent=1)

    monkeypatch.setattr(weekly_cli, "execute_weekly_training_report", execute)

    exit_code = weekly_cli.main(["--as-of", "2026-08-10"])

    output = capsys.readouterr()
    assert exit_code == 0
    assert captured["today"].isoformat() == "2026-08-10"
    assert captured["retry_only"] is False
    assert "status=sent" in output.out


def test_weekly_cli_hides_database_error_details(monkeypatch, capsys):
    secret = "postgresql://owner:secret-password@example.invalid/coach"

    def execute(*, today, retry_only):
        raise OperationalError("SELECT 1", {}, ConnectionError(secret))

    monkeypatch.setattr(weekly_cli, "execute_weekly_training_report", execute)

    exit_code = weekly_cli.main([])

    output = capsys.readouterr()
    assert exit_code == 1
    assert "OperationalError" in output.err
    assert secret not in output.err


def test_weekly_report_default_date_uses_taiwan_calendar():
    utc_sunday = datetime(2026, 8, 9, 17, tzinfo=timezone.utc)

    assert weekly_pipeline._default_weekly_report_date(utc_sunday) == date(2026, 8, 10)


def test_weekly_context_reads_full_required_time_window(monkeypatch):
    user = SimpleNamespace(id="user-id")
    captured = {}
    monkeypatch.setattr(weekly_pipeline, "get_or_create_default_user", lambda _session: user)
    monkeypatch.setattr(
        weekly_pipeline,
        "get_activities_in_time_window",
        lambda _session, user_id, *, started_at_on_or_after, started_at_before: captured.update(
            user_id=user_id,
            started_at_on_or_after=started_at_on_or_after,
            started_at_before=started_at_before,
        )
        or [],
    )
    monkeypatch.setattr(weekly_pipeline, "get_latest_user_profile", lambda *_args: None)
    monkeypatch.setattr(
        weekly_pipeline,
        "build_deterministic_coach_context",
        lambda _window, **kwargs: captured.update(context_kwargs=kwargs) or {"weekly_analysis": []},
    )

    weekly_pipeline._build_context_from_database(object(), today=date(2026, 8, 10))

    assert captured["user_id"] == "user-id"
    assert captured["started_at_on_or_after"] == datetime(
        2026,
        7,
        12,
        16,
        tzinfo=timezone.utc,
    )
    assert captured["started_at_before"] == datetime(
        2026,
        8,
        10,
        16,
        tzinfo=timezone.utc,
    )
    assert captured["context_kwargs"]["weekly_analysis_weeks"] == 5
