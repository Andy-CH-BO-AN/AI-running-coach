from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.db_settings import require_safe_test_database_url_or_skip


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def migration_database_url() -> Iterator[URL]:
    database_url = make_url(require_safe_test_database_url_or_skip())
    admin_engine = sqlalchemy.create_engine(database_url, future=True)
    schema_name = f"test_migration_{uuid.uuid4().hex}"
    with admin_engine.begin() as connection:
        connection.execute(text(f"create schema {schema_name}"))

    schema_url = database_url.update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    )
    try:
        yield schema_url
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f"drop schema if exists {schema_name} cascade"))
        admin_engine.dispose()


def _alembic_config(database_url: URL) -> Config:
    output = io.StringIO()
    config = Config(str(REPO_ROOT / "alembic.ini"), stdout=output)
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.attributes["database_url"] = database_url.render_as_string(
        hide_password=False
    )
    config.attributes["skip_logging_config"] = True
    return config


def test_0005_upgrade_and_downgrade_preserve_representable_delivery_state(
    migration_database_url: URL,
) -> None:
    command.upgrade(_alembic_config(migration_database_url), "20260726_0004")
    engine = sqlalchemy.create_engine(migration_database_url, future=True)
    user_id = uuid.uuid4()
    legacy_report_id = uuid.uuid4()
    seed_id = uuid.uuid4()
    sent_id = uuid.uuid4()

    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into users "
                "(id, external_source, external_user_id, created_at, updated_at) "
                "values (:id, 'local', 'migration-test', now(), now())"
            ),
            {"id": user_id},
        )
        connection.execute(
            text(
                "insert into ai_reports "
                "(id, user_id, report_scope, model_name, prompt_version, "
                "input_json, report_text, created_at) "
                "values (:id, :user_id, 'custom', 'legacy-model', 'legacy:v1', "
                "'{}'::jsonb, 'legacy report', now())"
            ),
            {"id": legacy_report_id, "user_id": user_id},
        )
        connection.execute(
            text(
                "insert into line_notifications "
                "(id, garmin_activity_id, recorded_at, is_seed, created_at) "
                "values (:seed_id, -1, '2026-08-01T00:00:00+00', true, now()), "
                "(:sent_id, 1001, '2026-08-02T00:00:00+00', false, now())"
            ),
            {"seed_id": seed_id, "sent_id": sent_id},
        )

    command.upgrade(_alembic_config(migration_database_url), "head")

    with engine.connect() as connection:
        legacy_key = connection.scalar(
            text("select idempotency_key from ai_reports where id = :id"),
            {"id": legacy_report_id},
        )
        seed_sent_at = connection.scalar(
            text("select sent_at from line_notifications where id = :id"),
            {"id": seed_id},
        )
        sent_times = connection.execute(
            text(
                "select recorded_at, sent_at from line_notifications where id = :id"
            ),
            {"id": sent_id},
        ).one()

    assert legacy_key == f"legacy:{legacy_report_id}"
    assert seed_sent_at is None
    assert sent_times.sent_at == sent_times.recorded_at
    ai_columns = {column["name"]: column for column in inspect(engine).get_columns("ai_reports")}
    assert ai_columns["idempotency_key"]["nullable"] is False

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into ai_reports "
                    "(id, idempotency_key, user_id, report_scope, model_name, "
                    "prompt_version, input_json, report_text, created_at) "
                    "values (:id, :key, :user_id, 'custom', 'duplicate', 'v1', "
                    "'{}'::jsonb, 'duplicate', now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "key": legacy_key,
                    "user_id": user_id,
                },
            )

    second_user_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into users "
                "(id, external_source, external_user_id, created_at, updated_at) "
                "values (:id, 'local', 'migration-test-two', now(), now())"
            ),
            {"id": second_user_id},
        )
        connection.execute(
            text(
                "insert into ai_reports "
                "(id, idempotency_key, user_id, report_scope, model_name, "
                "prompt_version, input_json, report_text, created_at) "
                "values (:id, :key, :user_id, 'custom', 'second-user', 'v1', "
                "'{}'::jsonb, 'same key, different owner', now())"
            ),
            {
                "id": uuid.uuid4(),
                "key": legacy_key,
                "user_id": second_user_id,
            },
        )

    weekly_summary_id = uuid.uuid4()
    weekly_report_id = uuid.uuid4()
    weekly_notification_id = uuid.uuid4()
    pending_report_id = uuid.uuid4()
    pending_notification_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into weekly_summaries "
                "(id, user_id, week_start, week_end, summary_version, computed_at, "
                "summary_json, created_at) values "
                "(:id, :user_id, '2026-08-03', '2026-08-09', 'weekly:v1', now(), "
                "'{}'::jsonb, now())"
            ),
            {"id": weekly_summary_id, "user_id": user_id},
        )
        for report_id, key in (
            (weekly_report_id, "weekly:2026-08-03:v1"),
            (pending_report_id, "activity:1002:v1"),
        ):
            connection.execute(
                text(
                    "insert into ai_reports "
                    "(id, idempotency_key, user_id, weekly_summary_id, report_scope, "
                    "model_name, prompt_version, input_json, report_text, created_at) "
                    "values (:id, :key, :user_id, :summary_id, :scope, 'model', 'v1', "
                    "'{}'::jsonb, 'report', now())"
                ),
                {
                    "id": report_id,
                    "key": key,
                    "user_id": user_id,
                    "summary_id": weekly_summary_id if report_id == weekly_report_id else None,
                    "scope": "weekly" if report_id == weekly_report_id else "activity",
                },
            )
        connection.execute(
            text(
                "insert into line_notifications "
                "(id, garmin_activity_id, weekly_summary_id, ai_report_id, "
                "rendered_messages, recorded_at, is_seed, sent_at, created_at) "
                "values (:weekly_id, null, :summary_id, :weekly_report_id, "
                "'[\"weekly payload\"]'::jsonb, now(), false, null, now()), "
                "(:pending_id, 1002, null, :pending_report_id, "
                "'[\"activity payload\"]'::jsonb, now(), false, null, now())"
            ),
            {
                "weekly_id": weekly_notification_id,
                "summary_id": weekly_summary_id,
                "weekly_report_id": weekly_report_id,
                "pending_id": pending_notification_id,
                "pending_report_id": pending_report_id,
            },
        )

    with engine.begin() as connection:
        connection.execute(
            text("delete from ai_reports where id = :id"),
            {"id": weekly_report_id},
        )
        assert connection.scalar(
            text("select count(*) from line_notifications where id = :id"),
            {"id": weekly_notification_id},
        ) == 0

    command.downgrade(_alembic_config(migration_database_url), "20260726_0004")

    remaining_columns = {
        column["name"] for column in inspect(engine).get_columns("line_notifications")
    }
    with engine.connect() as connection:
        remaining_ids = set(
            connection.scalars(text("select id from line_notifications"))
        )
        downgraded_sent_time = connection.scalar(
            text("select recorded_at from line_notifications where id = :id"),
            {"id": sent_id},
        )

    assert remaining_ids == {seed_id, sent_id}
    assert downgraded_sent_time == sent_times.sent_at
    assert {
        "weekly_summary_id",
        "ai_report_id",
        "rendered_messages",
        "sent_at",
    }.isdisjoint(remaining_columns)
    assert "idempotency_key" not in {
        column["name"] for column in inspect(engine).get_columns("ai_reports")
    }
    engine.dispose()


def test_0005_downgrade_refuses_to_erase_sent_weekly_idempotency(
    migration_database_url: URL,
) -> None:
    command.upgrade(_alembic_config(migration_database_url), "head")
    engine = sqlalchemy.create_engine(migration_database_url, future=True)
    user_id = uuid.uuid4()
    summary_id = uuid.uuid4()
    report_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into users "
                "(id, external_source, external_user_id, created_at, updated_at) "
                "values (:id, 'local', 'sent-week-migration', now(), now())"
            ),
            {"id": user_id},
        )
        connection.execute(
            text(
                "insert into weekly_summaries "
                "(id, user_id, week_start, week_end, summary_version, computed_at, "
                "summary_json, created_at) values "
                "(:id, :user_id, '2026-08-03', '2026-08-09', 'weekly:v1', now(), "
                "'{}'::jsonb, now())"
            ),
            {"id": summary_id, "user_id": user_id},
        )
        connection.execute(
            text(
                "insert into ai_reports "
                "(id, idempotency_key, user_id, weekly_summary_id, report_scope, "
                "model_name, prompt_version, input_json, report_text, created_at) "
                "values (:id, 'weekly:sent:v1', :user_id, :summary_id, 'weekly', "
                "'model', 'v1', '{}'::jsonb, 'sent report', now())"
            ),
            {"id": report_id, "user_id": user_id, "summary_id": summary_id},
        )
        connection.execute(
            text(
                "insert into line_notifications "
                "(id, weekly_summary_id, ai_report_id, rendered_messages, "
                "recorded_at, is_seed, sent_at, created_at) values "
                "(:id, :summary_id, :report_id, '[\"sent weekly\"]'::jsonb, "
                "now(), false, now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "summary_id": summary_id,
                "report_id": report_id,
            },
        )

    with pytest.raises(DBAPIError, match="sent weekly LINE notifications"):
        command.downgrade(
            _alembic_config(migration_database_url),
            "20260726_0004",
        )

    assert inspect(engine).has_table("line_notifications")
    assert "sent_at" in {
        column["name"] for column in inspect(engine).get_columns("line_notifications")
    }
    engine.dispose()
