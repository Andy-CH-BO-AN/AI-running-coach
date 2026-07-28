from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_neon_migrations.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "daily_pipeline.yml"


def _run_migration_script(
    tmp_path: Path,
    *,
    fail_until: int,
    failure_message: str = "connection refused",
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str], list[str]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    attempts_path = tmp_path / "attempts.txt"
    sleeps_path = tmp_path / "sleeps.txt"
    github_env = tmp_path / "github_env.txt"

    (fake_bin / "alembic").write_text(
        "#!/usr/bin/env bash\n"
        "echo attempt >> \"$ATTEMPTS_PATH\"\n"
        "attempt_count=$(wc -l < \"$ATTEMPTS_PATH\")\n"
        "if (( attempt_count <= FAKE_FAIL_UNTIL )); then\n"
        "  echo \"$FAKE_FAILURE_MESSAGE\" >&2\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (fake_bin / "sleep").write_text(
        "#!/usr/bin/env bash\n"
        "echo \"$1\" >> \"$SLEEPS_PATH\"\n",
        encoding="utf-8",
    )
    (fake_bin / "alembic").chmod(0o755)
    (fake_bin / "sleep").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "ATTEMPTS_PATH": str(attempts_path),
        "SLEEPS_PATH": str(sleeps_path),
        "GITHUB_ENV": str(github_env),
        "FAKE_FAIL_UNTIL": str(fail_until),
        "FAKE_FAILURE_MESSAGE": failure_message,
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    env_lines = github_env.read_text(encoding="utf-8").splitlines() if github_env.exists() else []
    attempts = attempts_path.read_text(encoding="utf-8").splitlines()
    sleeps = sleeps_path.read_text(encoding="utf-8").splitlines() if sleeps_path.exists() else []
    return result, env_lines, attempts, sleeps


def test_migration_first_attempt_success_sets_normal_mode(tmp_path):
    result, env_lines, attempts, sleeps = _run_migration_script(tmp_path, fail_until=0)

    assert result.returncode == 0
    assert attempts == ["attempt"]
    assert sleeps == []
    assert env_lines == ["DATABASE_AVAILABLE=true", "GARMIN_ACTIVITY_LIMIT=75"]
    assert "Running database migration attempt 1/3..." in result.stdout


def test_migration_third_attempt_success_sets_normal_mode(tmp_path):
    result, env_lines, attempts, sleeps = _run_migration_script(tmp_path, fail_until=2)

    assert result.returncode == 0
    assert len(attempts) == 3
    assert sleeps == ["10", "20"]
    assert env_lines == ["DATABASE_AVAILABLE=true", "GARMIN_ACTIVITY_LIMIT=75"]
    assert "Database migration attempt 1 failed." in result.stdout
    assert "Running database migration attempt 3/3..." in result.stdout


def test_migration_three_failures_enters_degraded_mode_without_failing(tmp_path):
    result, env_lines, attempts, sleeps = _run_migration_script(tmp_path, fail_until=3)

    assert result.returncode == 0
    assert len(attempts) == 3
    assert sleeps == ["10", "20"]
    assert env_lines == ["DATABASE_AVAILABLE=false", "GARMIN_ACTIVITY_LIMIT=10"]
    assert "::warning::Neon database unavailable after 3 attempts. Continuing in degraded mode." in result.stdout


def test_connection_timeout_expired_retries_then_enters_degraded_mode(tmp_path):
    result, env_lines, attempts, sleeps = _run_migration_script(
        tmp_path,
        fail_until=3,
        failure_message="connection timeout expired",
    )

    assert result.returncode == 0
    assert len(attempts) == 3
    assert sleeps == ["10", "20"]
    assert env_lines == ["DATABASE_AVAILABLE=false", "GARMIN_ACTIVITY_LIMIT=10"]


def test_cannot_connect_now_retries_then_enters_degraded_mode(tmp_path):
    failure_message = "FATAL: the database system is starting up (SQLSTATE 57P03)"
    result, env_lines, attempts, sleeps = _run_migration_script(
        tmp_path,
        fail_until=3,
        failure_message=failure_message,
    )

    assert result.returncode == 0
    assert len(attempts) == 3
    assert sleeps == ["10", "20"]
    assert env_lines == ["DATABASE_AVAILABLE=false", "GARMIN_ACTIVITY_LIMIT=10"]
    assert failure_message not in result.stdout
    assert failure_message not in result.stderr


@pytest.mark.parametrize(
    ("sqlstate", "failure_text"),
    [
        ("57P01", "FATAL: terminating connection due to administrator command"),
        ("57P02", "FATAL: the database system is in recovery mode after a crash"),
    ],
)
def test_shutdown_sqlstates_retry_then_enter_degraded_mode(
    tmp_path,
    sqlstate,
    failure_text,
):
    failure_message = f"{failure_text} (SQLSTATE {sqlstate})"
    result, env_lines, attempts, sleeps = _run_migration_script(
        tmp_path,
        fail_until=3,
        failure_message=failure_message,
    )

    assert result.returncode == 0
    assert len(attempts) == 3
    assert sleeps == ["10", "20"]
    assert env_lines == ["DATABASE_AVAILABLE=false", "GARMIN_ACTIVITY_LIMIT=10"]
    assert failure_message not in result.stdout
    assert failure_message not in result.stderr


@pytest.mark.parametrize(
    ("sqlstate", "failure_text"),
    [
        ("57014", "canceling statement due to user request"),
        ("57P04", "FATAL: database was dropped"),
    ],
)
def test_non_transient_operator_sqlstates_fail_closed(
    tmp_path,
    sqlstate,
    failure_text,
):
    failure_message = f"{failure_text} (SQLSTATE {sqlstate})"
    result, env_lines, attempts, sleeps = _run_migration_script(
        tmp_path,
        fail_until=1,
        failure_message=failure_message,
    )

    assert result.returncode == 1
    assert attempts == ["attempt"]
    assert sleeps == []
    assert env_lines == []
    assert failure_message not in result.stdout
    assert failure_message not in result.stderr


def test_server_closed_connection_retries_then_enters_degraded_mode(tmp_path):
    failure_message = "server closed the connection unexpectedly"
    result, env_lines, attempts, sleeps = _run_migration_script(
        tmp_path,
        fail_until=3,
        failure_message=failure_message,
    )

    assert result.returncode == 0
    assert len(attempts) == 3
    assert sleeps == ["10", "20"]
    assert env_lines == ["DATABASE_AVAILABLE=false", "GARMIN_ACTIVITY_LIMIT=10"]
    assert failure_message not in result.stdout
    assert failure_message not in result.stderr


def test_non_connection_migration_failure_stops_without_leaking_output(tmp_path):
    result, env_lines, attempts, sleeps = _run_migration_script(
        tmp_path,
        fail_until=1,
        failure_message="migration revision is invalid",
    )

    assert result.returncode == 1
    assert attempts == ["attempt"]
    assert sleeps == []
    assert env_lines == []
    assert "::error::Database migration failed with a non-connection error. Pipeline stopped." in result.stdout
    assert "migration revision is invalid" not in result.stdout
    assert "migration revision is invalid" not in result.stderr


def test_auth_failure_with_connection_prefix_stops_without_leaking_output(tmp_path):
    failure_message = (
        "could not connect to server: FATAL: password authentication failed "
        "for user (SQLSTATE 28P01)"
    )
    result, env_lines, attempts, sleeps = _run_migration_script(
        tmp_path,
        fail_until=1,
        failure_message=failure_message,
    )

    assert result.returncode == 1
    assert attempts == ["attempt"]
    assert sleeps == []
    assert env_lines == []
    assert "::error::Database migration failed with a non-connection error. Pipeline stopped." in result.stdout
    assert failure_message not in result.stdout
    assert failure_message not in result.stderr


def test_workflow_runs_pipeline_after_migration_script_without_condition():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "run: bash scripts/run_neon_migrations.sh" in workflow
    pipeline_step = workflow.split("- name: Run AI Coach Pipeline", maxsplit=1)[1]
    assert "if:" not in pipeline_step
