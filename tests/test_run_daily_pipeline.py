from __future__ import annotations

from pathlib import Path

import pytest

import run_pipeline as manual_cli
from src.notifications.notifier import NotificationResult
from src.pipeline.daily_run import (
    DailyRunBlocked,
    DailyRunBlockReason,
    DailyRunMode,
    DailyRunResult,
)
from src.scripts import run_daily_pipeline as daily_cli


@pytest.mark.parametrize("flag", ["--activity-limit", "--fetch-limit"])
def test_daily_cli_rejects_activity_window_overrides(flag):
    with pytest.raises(SystemExit) as raised:
        daily_cli.parse_args([flag, "10"])

    assert raised.value.code == 2


def test_daily_cli_passes_goal_overrides_and_prints_typed_result(
    monkeypatch,
    tmp_path,
    capsys,
):
    captured = {}
    expected = DailyRunResult(
        mode=DailyRunMode.NORMAL,
        report_path=tmp_path / "report.json",
        notification=NotificationResult(status="done", sent=1),
    )

    def execute(*, goal_overrides):
        captured["goal_overrides"] = goal_overrides
        return expected

    monkeypatch.setattr(daily_cli, "execute_daily_run", execute)

    exit_code = daily_cli.main(
        [
            "--core-goal",
            "Half marathon under 1:45",
            "--training-preferences",
            "Run four days per week",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert captured["goal_overrides"].core_goal == "Half marathon under 1:45"
    assert captured["goal_overrides"].training_preferences == "Run four days per week"
    assert "mode=normal" in output.out
    assert str(expected.report_path) in output.out
    assert "notification=done" in output.out


def test_daily_cli_prints_only_safe_blocked_message(monkeypatch, capsys):
    secret = "postgresql://owner:secret-password@example.invalid/coach"

    def execute(**_kwargs):
        try:
            raise RuntimeError(secret)
        except RuntimeError:
            raise DailyRunBlocked(
                DailyRunBlockReason.AUTHENTICATION,
                "Cloud Daily Run database authentication was rejected.",
            ) from None

    monkeypatch.setattr(daily_cli, "execute_daily_run", execute)

    exit_code = daily_cli.main([])

    output = capsys.readouterr()
    assert exit_code == 1
    assert "authentication" in output.err
    assert "authentication was rejected" in output.err
    assert secret not in output.out
    assert secret not in output.err


@pytest.mark.parametrize("mode", ["local", "mirror"])
def test_manual_cli_keeps_custom_limits_for_local_and_mirror(monkeypatch, mode):
    monkeypatch.setenv("DATABASE_MODE", mode)
    captured = {}

    def run(**kwargs):
        captured.update(kwargs)
        return "output/report.json"

    monkeypatch.setattr(manual_cli, "run_pipeline", run)

    result = manual_cli.main(
        [
            "--activity-limit",
            "12",
            "--fetch-limit",
            "999",
        ]
    )

    assert result == "output/report.json"
    assert captured["activity_limit"] == 12
    assert captured["fetch_limit"] == 999


def test_manual_cli_rejects_cloud_mode_and_points_to_daily_command(monkeypatch):
    monkeypatch.setenv("DATABASE_MODE", "cloud")
    monkeypatch.setattr(
        manual_cli,
        "run_pipeline",
        lambda **_kwargs: pytest.fail("manual runner must not start in cloud mode"),
    )

    with pytest.raises(SystemExit, match="src.scripts.run_daily_pipeline"):
        manual_cli.main([])
