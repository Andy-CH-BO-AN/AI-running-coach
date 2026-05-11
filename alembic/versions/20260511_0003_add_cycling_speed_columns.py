"""add cycling speed columns

Revision ID: 20260511_0003
Revises: 20260511_0002
Create Date: 2026-05-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260511_0003"
down_revision: Union[str, None] = "20260511_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("activities", sa.Column("average_speed_kmh", sa.Numeric(), nullable=True))
    op.add_column("activity_splits", sa.Column("speed_kmh", sa.Numeric(), nullable=True))

    op.execute(
        """
        update activities
        set average_speed_kmh = round((distance_km / (duration_min / 60.0))::numeric, 3)
        where activity_type = 'cycling'
          and distance_km is not null
          and duration_min is not null
          and duration_min > 0
        """
    )
    op.execute(
        """
        update activity_splits
        set speed_kmh = round((activity_splits.distance_km / (activity_splits.duration_min / 60.0))::numeric, 3)
        from activities
        where activity_splits.activity_id = activities.id
          and activities.activity_type = 'cycling'
          and activity_splits.distance_km is not null
          and activity_splits.duration_min is not null
          and activity_splits.duration_min > 0
        """
    )


def downgrade() -> None:
    op.drop_column("activity_splits", "speed_kmh")
    op.drop_column("activities", "average_speed_kmh")
