"""clear cycling pace columns

Revision ID: 20260511_0002
Revises: 20260510_0001
Create Date: 2026-05-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260511_0002"
down_revision: Union[str, None] = "20260510_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        update activities
        set average_pace_min_per_km = null
        where activity_type = 'cycling'
        """
    )
    op.execute(
        """
        update activity_splits
        set pace_min_per_km = null
        where activity_id in (
            select id
            from activities
            where activity_type = 'cycling'
        )
        """
    )


def downgrade() -> None:
    # Irreversible data cleanup: previous values were cycling speeds stored
    # in min/km pace columns, so restoring them would reintroduce bad units.
    pass
