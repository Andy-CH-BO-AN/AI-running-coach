"""phase2 database persistence

Revision ID: 20260510_0001
Revises:
Create Date: 2026-05-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260510_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_source", sa.Text(), server_default="garmin", nullable=False),
        sa.Column("external_user_id", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("external_source", "external_user_id", name="uq_users_external_identity"),
    )

    op.create_table(
        "user_profile_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("max_heart_rate", sa.Numeric(), nullable=True),
        sa.Column("resting_heart_rate", sa.Numeric(), nullable=True),
        sa.Column("vo2max_running", sa.Numeric(), nullable=True),
        sa.Column("lactate_threshold_speed_mps", sa.Numeric(), nullable=True),
        sa.Column("lactate_threshold_pace", sa.Text(), nullable=True),
        sa.Column("lactate_threshold_heart_rate", sa.Numeric(), nullable=True),
        sa.Column("weight_kg", sa.Numeric(), nullable=True),
        sa.Column("height_cm", sa.Numeric(), nullable=True),
        sa.Column("available_training_days", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("preferred_long_training_days", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pr_running", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pr_swimming", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pr_cycling", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_profile_snapshots_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_profile_snapshots")),
        sa.UniqueConstraint("user_id", "captured_at", name="uq_user_profile_snapshots_user_captured_at"),
    )
    op.create_index(
        "ix_user_profile_snapshots_user_id_captured_at",
        "user_profile_snapshots",
        ["user_id", sa.text("captured_at DESC")],
    )

    op.create_table(
        "activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("garmin_activity_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_type", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("distance_km", sa.Numeric(), nullable=True),
        sa.Column("duration_min", sa.Numeric(), nullable=True),
        sa.Column("duration_sec", sa.Numeric(), nullable=True),
        sa.Column("average_pace_min_per_km", sa.Numeric(), nullable=True),
        sa.Column("average_heart_rate", sa.Numeric(), nullable=True),
        sa.Column("max_heart_rate", sa.Numeric(), nullable=True),
        sa.Column("average_power", sa.Numeric(), nullable=True),
        sa.Column("max_power", sa.Numeric(), nullable=True),
        sa.Column("average_cadence", sa.Numeric(), nullable=True),
        sa.Column("max_cadence", sa.Numeric(), nullable=True),
        sa.Column("elevation_gain", sa.Numeric(), nullable=True),
        sa.Column("elevation_loss", sa.Numeric(), nullable=True),
        sa.Column("temperature", sa.Numeric(), nullable=True),
        sa.Column("training_stress_score", sa.Numeric(), nullable=True),
        sa.Column("intensity_factor", sa.Numeric(), nullable=True),
        sa.Column("aerobic_training_effect", sa.Numeric(), nullable=True),
        sa.Column("anaerobic_training_effect", sa.Numeric(), nullable=True),
        sa.Column("raw_metrics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.Text(), server_default="garmin", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_activities_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activities")),
        sa.UniqueConstraint("garmin_activity_id", name="uq_activities_garmin_activity_id"),
    )
    op.create_index("ix_activities_activity_type", "activities", ["activity_type"])
    op.create_index("ix_activities_raw_metrics_gin", "activities", ["raw_metrics"], postgresql_using="gin")
    op.create_index("ix_activities_user_id_started_at", "activities", ["user_id", sa.text("started_at DESC")])

    op.create_table(
        "activity_splits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("split_index", sa.Integer(), nullable=False),
        sa.Column("distance_km", sa.Numeric(), nullable=True),
        sa.Column("duration_min", sa.Numeric(), nullable=True),
        sa.Column("duration_sec", sa.Numeric(), nullable=True),
        sa.Column("pace_min_per_km", sa.Numeric(), nullable=True),
        sa.Column("average_heart_rate", sa.Numeric(), nullable=True),
        sa.Column("max_heart_rate", sa.Numeric(), nullable=True),
        sa.Column("average_power", sa.Numeric(), nullable=True),
        sa.Column("max_power", sa.Numeric(), nullable=True),
        sa.Column("average_cadence", sa.Numeric(), nullable=True),
        sa.Column("max_cadence", sa.Numeric(), nullable=True),
        sa.Column("temperature", sa.Numeric(), nullable=True),
        sa.Column("stride_length_cm", sa.Numeric(), nullable=True),
        sa.Column("ground_contact_time_ms", sa.Numeric(), nullable=True),
        sa.Column("vertical_oscillation_cm", sa.Numeric(), nullable=True),
        sa.Column("vertical_ratio", sa.Numeric(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], name=op.f("fk_activity_splits_activity_id_activities"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_splits")),
        sa.UniqueConstraint("activity_id", "split_index", name="uq_activity_splits_activity_id_split_index"),
    )
    op.create_index("ix_activity_splits_activity_id", "activity_splits", ["activity_id"])
    op.create_index("ix_activity_splits_activity_id_split_index", "activity_splits", ["activity_id", "split_index"])
    op.create_index("ix_activity_splits_metrics_gin", "activity_splits", ["metrics"], postgresql_using="gin")

    op.create_table(
        "swimming_lengths",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_split_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("length_index", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Numeric(), nullable=True),
        sa.Column("duration_sec", sa.Numeric(), nullable=True),
        sa.Column("swim_stroke", sa.Text(), nullable=True),
        sa.Column("strokes", sa.Integer(), nullable=True),
        sa.Column("swolf", sa.Numeric(), nullable=True),
        sa.Column("avg_hr", sa.Numeric(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["activity_split_id"], ["activity_splits.id"], name=op.f("fk_swimming_lengths_activity_split_id_activity_splits"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_swimming_lengths")),
        sa.UniqueConstraint("activity_split_id", "length_index", name="uq_swimming_lengths_split_id_length_index"),
    )

    op.create_table(
        "activity_features",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_version", sa.Text(), nullable=False),
        sa.Column("algorithm_version", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], name=op.f("fk_activity_features_activity_id_activities"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_features")),
        sa.UniqueConstraint("activity_id", "feature_version", name="uq_activity_features_activity_version"),
    )

    op.create_table(
        "weekly_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("summary_version", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_distance_km", sa.Numeric(), nullable=True),
        sa.Column("total_duration_min", sa.Numeric(), nullable=True),
        sa.Column("running_distance_km", sa.Numeric(), nullable=True),
        sa.Column("swimming_distance_km", sa.Numeric(), nullable=True),
        sa.Column("workout_count", sa.Integer(), nullable=True),
        sa.Column("running_count", sa.Integer(), nullable=True),
        sa.Column("swimming_count", sa.Integer(), nullable=True),
        sa.Column("high_intensity_count", sa.Integer(), nullable=True),
        sa.Column("long_run_count", sa.Integer(), nullable=True),
        sa.Column("training_load", sa.Numeric(), nullable=True),
        sa.Column("acute_load", sa.Numeric(), nullable=True),
        sa.Column("chronic_load", sa.Numeric(), nullable=True),
        sa.Column("acute_chronic_ratio", sa.Numeric(), nullable=True),
        sa.Column("monotony", sa.Numeric(), nullable=True),
        sa.Column("strain", sa.Numeric(), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_weekly_summaries_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_summaries")),
        sa.UniqueConstraint("user_id", "week_start", "summary_version", name="uq_weekly_summaries_user_week_version"),
    )

    op.create_table(
        "ai_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("weekly_summary_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("report_scope", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("feature_version", sa.Text(), nullable=True),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=True),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("report_scope in ('activity', 'weekly', 'profile', 'custom')", name=op.f("ck_ai_reports_report_scope_allowed")),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], name=op.f("fk_ai_reports_activity_id_activities"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_reports_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["weekly_summary_id"], ["weekly_summaries.id"], name=op.f("fk_ai_reports_weekly_summary_id_weekly_summaries"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_reports")),
    )
    op.create_index("ix_ai_reports_activity_id", "ai_reports", ["activity_id"])
    op.create_index("ix_ai_reports_model_prompt", "ai_reports", ["model_name", "prompt_version"])
    op.create_index("ix_ai_reports_report_json_gin", "ai_reports", ["report_json"], postgresql_using="gin")
    op.create_index("ix_ai_reports_user_id", "ai_reports", ["user_id"])
    op.create_index("ix_ai_reports_weekly_summary_id", "ai_reports", ["weekly_summary_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_reports_weekly_summary_id", table_name="ai_reports")
    op.drop_index("ix_ai_reports_user_id", table_name="ai_reports")
    op.drop_index("ix_ai_reports_report_json_gin", table_name="ai_reports")
    op.drop_index("ix_ai_reports_model_prompt", table_name="ai_reports")
    op.drop_index("ix_ai_reports_activity_id", table_name="ai_reports")
    op.drop_table("ai_reports")
    op.drop_table("weekly_summaries")
    op.drop_table("activity_features")
    op.drop_table("swimming_lengths")
    op.drop_index("ix_activity_splits_metrics_gin", table_name="activity_splits")
    op.drop_index("ix_activity_splits_activity_id_split_index", table_name="activity_splits")
    op.drop_index("ix_activity_splits_activity_id", table_name="activity_splits")
    op.drop_table("activity_splits")
    op.drop_index("ix_activities_user_id_started_at", table_name="activities")
    op.drop_index("ix_activities_raw_metrics_gin", table_name="activities")
    op.drop_index("ix_activities_activity_type", table_name="activities")
    op.drop_table("activities")
    op.drop_index("ix_user_profile_snapshots_user_id_captured_at", table_name="user_profile_snapshots")
    op.drop_table("user_profile_snapshots")
    op.drop_table("users")
