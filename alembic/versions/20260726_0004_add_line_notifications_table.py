"""add line_notifications table

Revision ID: 20260726_0004
Revises: 20260511_0003
Create Date: 2026-07-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0004"
down_revision: Union[str, None] = "20260511_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "line_notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("garmin_activity_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "is_seed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_line_notifications")),
        sa.UniqueConstraint(
            "garmin_activity_id",
            name="uq_line_notifications_garmin_activity_id",
        ),
    )
    op.create_index(
        "ix_line_notifications_garmin_activity_id",
        "line_notifications",
        ["garmin_activity_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_line_notifications_garmin_activity_id",
        table_name="line_notifications",
    )
    op.drop_table("line_notifications")
