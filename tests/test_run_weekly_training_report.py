from __future__ import annotations

from sqlalchemy.exc import OperationalError

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
