from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.db.mappers import jsonable
from src.db.models import AIReport, Activity, LineNotification
from src.db.repositories import (
    get_ai_report_by_idempotency_key,
    prepare_activity_notification,
    save_ai_report,
)


@dataclass(frozen=True, slots=True, repr=False)
class AIReportSpec:
    """Stable identity and deterministic input for one logical AI report."""

    idempotency_key: str
    user_id: uuid.UUID
    report_scope: str
    input_json: dict[str, Any]
    prompt_version: str
    activity_id: uuid.UUID | None = None
    weekly_summary_id: uuid.UUID | None = None
    feature_version: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class AIReportDraft:
    """Unpersisted provider output; never pass this object downstream."""

    report_text: str
    model_name: str
    report_json: dict[str, Any] | None = None
    confidence: str | None = None
    output_path: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class PersistedAIReport:
    """Detached snapshot of the canonical DB row selected by idempotency key."""

    id: uuid.UUID
    idempotency_key: str
    user_id: uuid.UUID
    activity_id: uuid.UUID | None
    weekly_summary_id: uuid.UUID | None
    report_scope: str
    report_text: str
    input_json: dict[str, Any]
    model_name: str
    prompt_version: str
    feature_version: str | None
    report_json: dict[str, Any] | None
    confidence: str | None
    output_path: str | None

    @classmethod
    def from_model(cls, report: AIReport) -> PersistedAIReport:
        return cls(
            id=report.id,
            idempotency_key=report.idempotency_key,
            user_id=report.user_id,
            activity_id=report.activity_id,
            weekly_summary_id=report.weekly_summary_id,
            report_scope=report.report_scope,
            report_text=report.report_text,
            input_json=deepcopy(report.input_json),
            model_name=report.model_name,
            prompt_version=report.prompt_version,
            feature_version=report.feature_version,
            report_json=deepcopy(report.report_json),
            confidence=report.confidence,
            output_path=report.output_path,
        )


@dataclass(frozen=True, slots=True, repr=False)
class PreparedLineDelivery:
    """Canonical persisted payload that downstream LINE transport must use."""

    notification_id: uuid.UUID
    ai_report_id: uuid.UUID
    rendered_messages: tuple[str, ...]
    already_sent: bool

    @classmethod
    def from_model(cls, notification: LineNotification) -> PreparedLineDelivery:
        payload = notification.rendered_messages
        if (
            notification.ai_report_id is None
            or payload is None
            or isinstance(payload, str)
            or not payload
            or any(not isinstance(message, str) or not message for message in payload)
        ):
            raise RuntimeError("Prepared AI notification is missing its persisted payload")
        return cls(
            notification_id=notification.id,
            ai_report_id=notification.ai_report_id,
            rendered_messages=tuple(payload),
            already_sent=notification.sent_at is not None,
        )

    @property
    def should_send(self) -> bool:
        return not self.already_sent


SessionContextFactory = Callable[[], AbstractContextManager[Session]]
NotificationLockFactory = Callable[[], AbstractContextManager[Any]]
AIReportGenerator = Callable[[AIReportSpec], AIReportDraft]
AIReportRenderer = Callable[[PersistedAIReport], Sequence[str]]


@dataclass(frozen=True, slots=True, repr=False)
class ActivityAINotificationPreparer:
    """Resolve canonical AI output and persist one immutable Activity payload.

    The external generator runs before the LINE advisory-lock context is entered.
    A unique-key race may call the provider more than once, but only the canonical
    persisted AIReport is rendered, referenced, and returned downstream.
    """

    session_factory: SessionContextFactory
    notification_lock: NotificationLockFactory
    generate: AIReportGenerator
    render: AIReportRenderer

    def prepare(
        self,
        *,
        spec: AIReportSpec,
        garmin_activity_id: int,
    ) -> PreparedLineDelivery:
        if (
            spec.report_scope != "activity"
            or spec.activity_id is None
            or spec.weekly_summary_id is not None
        ):
            raise ValueError("Activity preparation requires an Activity AI report spec")
        normalized_spec = AIReportSpec(
            idempotency_key=spec.idempotency_key,
            user_id=spec.user_id,
            report_scope=spec.report_scope,
            input_json=jsonable(spec.input_json),
            prompt_version=spec.prompt_version,
            activity_id=spec.activity_id,
            weekly_summary_id=spec.weekly_summary_id,
            feature_version=spec.feature_version,
        )
        canonical_report = self._resolve_report(
            normalized_spec,
            garmin_activity_id=garmin_activity_id,
        )
        rendered_messages = self.render(canonical_report)

        # This is the only advisory-lock scope owned by this module. Provider I/O
        # and rendering are deliberately complete before entry.
        with self.notification_lock():
            with self.session_factory() as session:
                canonical_notification = prepare_activity_notification(
                    session,
                    garmin_activity_id=garmin_activity_id,
                    ai_report_id=canonical_report.id,
                    rendered_messages=rendered_messages,
                )
                session.commit()
                return PreparedLineDelivery.from_model(canonical_notification)

    def _resolve_report(
        self,
        spec: AIReportSpec,
        *,
        garmin_activity_id: int,
    ) -> PersistedAIReport:
        with self.session_factory() as session:
            activity = session.get(Activity, spec.activity_id)
            if (
                activity is None
                or activity.user_id != spec.user_id
                or activity.garmin_activity_id != garmin_activity_id
            ):
                raise ValueError(
                    "Activity AI report spec does not match the notification subject"
                )
            existing = get_ai_report_by_idempotency_key(
                session,
                spec.user_id,
                spec.idempotency_key,
            )
            if existing is not None:
                self._validate_canonical_report(spec, existing)
                return PersistedAIReport.from_model(existing)

        # No DB transaction/session and no LINE advisory lock spans provider I/O.
        draft = self.generate(
            AIReportSpec(
                idempotency_key=spec.idempotency_key,
                user_id=spec.user_id,
                report_scope=spec.report_scope,
                input_json=deepcopy(spec.input_json),
                prompt_version=spec.prompt_version,
                activity_id=spec.activity_id,
                weekly_summary_id=spec.weekly_summary_id,
                feature_version=spec.feature_version,
            )
        )

        with self.session_factory() as session:
            canonical = save_ai_report(
                session,
                idempotency_key=spec.idempotency_key,
                user_id=spec.user_id,
                report_scope=spec.report_scope,
                report_text=draft.report_text,
                input_json=spec.input_json,
                model_name=draft.model_name,
                prompt_version=spec.prompt_version,
                activity_id=spec.activity_id,
                weekly_summary_id=spec.weekly_summary_id,
                feature_version=spec.feature_version,
                report_json=draft.report_json,
                confidence=draft.confidence,
                output_path=draft.output_path,
            )
            self._validate_canonical_report(spec, canonical)
            session.commit()
            return PersistedAIReport.from_model(canonical)

    @staticmethod
    def _validate_canonical_report(spec: AIReportSpec, report: AIReport) -> None:
        expected_identity = (
            spec.user_id,
            spec.idempotency_key,
            spec.report_scope,
            spec.activity_id,
            spec.weekly_summary_id,
            spec.prompt_version,
            spec.feature_version,
        )
        persisted_identity = (
            report.user_id,
            report.idempotency_key,
            report.report_scope,
            report.activity_id,
            report.weekly_summary_id,
            report.prompt_version,
            report.feature_version,
        )
        if (
            persisted_identity != expected_identity
            or report.input_json != jsonable(spec.input_json)
        ):
            raise RuntimeError(
                "Canonical AI report does not match the requested report identity"
            )
