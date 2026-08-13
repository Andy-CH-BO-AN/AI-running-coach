"""add AI report idempotency and prepared LINE delivery

Revision ID: 20260812_0005
Revises: 20260726_0004
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0005"
down_revision: Union[str, None] = "20260726_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_reports", sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.execute(
        "update ai_reports set idempotency_key = 'legacy:' || id::text "
        "where idempotency_key is null"
    )
    op.alter_column("ai_reports", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_ai_reports_user_idempotency_key",
        "ai_reports",
        ["user_id", "idempotency_key"],
    )

    op.alter_column(
        "line_notifications",
        "garmin_activity_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.add_column(
        "line_notifications",
        sa.Column("weekly_summary_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "line_notifications",
        sa.Column("ai_report_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "line_notifications",
        sa.Column("rendered_messages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "line_notifications",
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "update line_notifications set sent_at = recorded_at where not is_seed"
    )
    op.create_unique_constraint(
        "uq_line_notifications_weekly_summary_id",
        "line_notifications",
        ["weekly_summary_id"],
    )
    op.create_foreign_key(
        op.f("fk_line_notifications_weekly_summary_id_weekly_summaries"),
        "line_notifications",
        "weekly_summaries",
        ["weekly_summary_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_line_notifications_ai_report_id_ai_reports"),
        "line_notifications",
        "ai_reports",
        ["ai_report_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_line_notifications_ai_report_id",
        "line_notifications",
        ["ai_report_id"],
    )
    op.create_check_constraint(
        op.f("ck_line_notifications_subject_exactly_one"),
        "line_notifications",
        "(garmin_activity_id is not null and weekly_summary_id is null) "
        "or (garmin_activity_id is null and weekly_summary_id is not null and not is_seed)",
    )
    op.create_check_constraint(
        op.f("ck_line_notifications_rendered_messages_valid"),
        "line_notifications",
        "rendered_messages is null "
        "or (ai_report_id is not null and jsonb_typeof(rendered_messages) = 'array')",
    )
    op.create_check_constraint(
        op.f("ck_line_notifications_seed_shape"),
        "line_notifications",
        "not is_seed or (ai_report_id is null and rendered_messages is null and sent_at is null)",
    )


def downgrade() -> None:
    op.execute(
        "do $$ begin "
        "if exists ("
        "select 1 from line_notifications "
        "where weekly_summary_id is not null and sent_at is not null"
        ") then "
        "raise exception 'cannot downgrade: sent weekly LINE notifications would lose idempotency'; "
        "end if; end $$"
    )
    # Rows without an old-schema representation must not become false sent markers.
    op.execute(
        "delete from line_notifications "
        "where weekly_summary_id is not null "
        "or (not is_seed and sent_at is null)"
    )
    op.execute(
        "update line_notifications set recorded_at = sent_at "
        "where not is_seed and sent_at is not null"
    )

    op.drop_constraint(
        op.f("ck_line_notifications_seed_shape"),
        "line_notifications",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_line_notifications_rendered_messages_valid"),
        "line_notifications",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_line_notifications_subject_exactly_one"),
        "line_notifications",
        type_="check",
    )
    op.drop_index("ix_line_notifications_ai_report_id", table_name="line_notifications")
    op.drop_constraint(
        op.f("fk_line_notifications_ai_report_id_ai_reports"),
        "line_notifications",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_line_notifications_weekly_summary_id_weekly_summaries"),
        "line_notifications",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_line_notifications_weekly_summary_id",
        "line_notifications",
        type_="unique",
    )
    op.drop_column("line_notifications", "sent_at")
    op.drop_column("line_notifications", "rendered_messages")
    op.drop_column("line_notifications", "ai_report_id")
    op.drop_column("line_notifications", "weekly_summary_id")
    op.alter_column(
        "line_notifications",
        "garmin_activity_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )

    op.drop_constraint(
        "uq_ai_reports_user_idempotency_key",
        "ai_reports",
        type_="unique",
    )
    op.drop_column("ai_reports", "idempotency_key")
