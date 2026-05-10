import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("external_source", "external_user_id", name="uq_users_external_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_source: Mapped[str] = mapped_column(Text, nullable=False, default="garmin", server_default="garmin")
    external_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    profile_snapshots: Mapped[list["UserProfileSnapshot"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    activities: Mapped[list["Activity"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserProfileSnapshot(Base):
    __tablename__ = "user_profile_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "captured_at", name="uq_user_profile_snapshots_user_captured_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_heart_rate: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    resting_heart_rate: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    vo2max_running: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    lactate_threshold_speed_mps: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    lactate_threshold_pace: Mapped[str | None] = mapped_column(Text, nullable=True)
    lactate_threshold_heart_rate: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    available_training_days: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    preferred_long_training_days: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    pr_running: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    pr_swimming: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    pr_cycling: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    raw_profile: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="profile_snapshots")


Index(
    "ix_user_profile_snapshots_user_id_captured_at",
    UserProfileSnapshot.user_id,
    UserProfileSnapshot.captured_at.desc(),
)


class Activity(Base, TimestampMixin):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("garmin_activity_id", name="uq_activities_garmin_activity_id"),
        Index("ix_activities_activity_type", "activity_type"),
        Index("ix_activities_raw_metrics_gin", "raw_metrics", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    garmin_activity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    duration_min: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    average_pace_min_per_km: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    average_heart_rate: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    max_heart_rate: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    average_power: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    max_power: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    average_cadence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    max_cadence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    elevation_gain: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    elevation_loss: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    training_stress_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    intensity_factor: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    aerobic_training_effect: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    anaerobic_training_effect: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    raw_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="garmin", server_default="garmin")

    user: Mapped[User] = relationship(back_populates="activities")
    splits: Mapped[list["ActivitySplit"]] = relationship(back_populates="activity", cascade="all, delete-orphan")
    features: Mapped[list["ActivityFeature"]] = relationship(back_populates="activity", cascade="all, delete-orphan")
    ai_reports: Mapped[list["AIReport"]] = relationship(back_populates="activity")


Index("ix_activities_user_id_started_at", Activity.user_id, Activity.started_at.desc())


class ActivitySplit(Base, TimestampMixin):
    __tablename__ = "activity_splits"
    __table_args__ = (
        UniqueConstraint("activity_id", "split_index", name="uq_activity_splits_activity_id_split_index"),
        Index("ix_activity_splits_activity_id", "activity_id"),
        Index("ix_activity_splits_activity_id_split_index", "activity_id", "split_index"),
        Index("ix_activity_splits_metrics_gin", "metrics", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    split_index: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_km: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    duration_min: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pace_min_per_km: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    average_heart_rate: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    max_heart_rate: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    average_power: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    max_power: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    average_cadence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    max_cadence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    stride_length_cm: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    ground_contact_time_ms: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    vertical_oscillation_cm: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    vertical_ratio: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    activity: Mapped[Activity] = relationship(back_populates="splits")
    swimming_lengths: Mapped[list["SwimmingLength"]] = relationship(
        back_populates="activity_split", cascade="all, delete-orphan"
    )


class SwimmingLength(Base, TimestampMixin):
    __tablename__ = "swimming_lengths"
    __table_args__ = (
        UniqueConstraint("activity_split_id", "length_index", name="uq_swimming_lengths_split_id_length_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    activity_split_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activity_splits.id", ondelete="CASCADE"), nullable=False
    )
    length_index: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    swim_stroke: Mapped[str | None] = mapped_column(Text, nullable=True)
    strokes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    swolf: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    activity_split: Mapped[ActivitySplit] = relationship(back_populates="swimming_lengths")


class ActivityFeature(Base):
    __tablename__ = "activity_features"
    __table_args__ = (UniqueConstraint("activity_id", "feature_version", name="uq_activity_features_activity_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    feature_version: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )

    activity: Mapped[Activity] = relationship(back_populates="features")


class WeeklySummary(Base):
    __tablename__ = "weekly_summaries"
    __table_args__ = (UniqueConstraint("user_id", "week_start", "summary_version", name="uq_weekly_summaries_user_week_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    summary_version: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    total_distance_km: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    total_duration_min: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    running_distance_km: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    swimming_distance_km: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    workout_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    running_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    swimming_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    high_intensity_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    long_run_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    training_load: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    acute_load: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    chronic_load: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    acute_chronic_ratio: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    monotony: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    strain: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )

    user: Mapped[User] = relationship()
    ai_reports: Mapped[list["AIReport"]] = relationship(back_populates="weekly_summary")


class AIReport(Base):
    __tablename__ = "ai_reports"
    __table_args__ = (
        CheckConstraint("report_scope in ('activity', 'weekly', 'profile', 'custom')", name="report_scope_allowed"),
        Index("ix_ai_reports_user_id", "user_id"),
        Index("ix_ai_reports_activity_id", "activity_id"),
        Index("ix_ai_reports_weekly_summary_id", "weekly_summary_id"),
        Index("ix_ai_reports_model_prompt", "model_name", "prompt_version"),
        Index("ix_ai_reports_report_json_gin", "report_json", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    weekly_summary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("weekly_summaries.id", ondelete="SET NULL"), nullable=True
    )
    report_scope: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    feature_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    report_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )

    user: Mapped[User] = relationship()
    activity: Mapped[Activity | None] = relationship(back_populates="ai_reports")
    weekly_summary: Mapped[WeeklySummary | None] = relationship(back_populates="ai_reports")
