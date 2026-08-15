"""Create, persist, and deliver one previous-complete-week coaching report."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Protocol

from sqlalchemy.orm import Session

from src.db.mappers import jsonable
from src.db.models import AIReport, LineNotification, WeeklySummary
from src.db.repositories import (
    get_ai_report_by_idempotency_key,
    get_prepared_weekly_notification,
    list_pending_weekly_notifications,
    mark_notification_sent,
    prepare_weekly_notification,
    save_ai_report,
    save_weekly_summary,
)
from src.notifications.formatter import format_weekly_report_messages
from src.notifications.line_client import LineSendResult, send_push_messages
from src.preprocessing.weekly_report import (
    WEEKLY_SUMMARY_VERSION,
    CompletedWeekSummary,
    build_completed_week_summary,
)
from src.services.ai_report_resolution import (
    AIReportDraft,
    AIReportSpec,
    PersistedAIReport,
    PreparedLineDelivery,
)

WEEKLY_REPORT_PROMPT_VERSION = "weekly-coach:v1"


class WeeklyLineTransport(Protocol):
    def send(self, token: str, group_id: str, messages: Sequence[str]) -> LineSendResult: ...


class WeeklyReportGenerator(Protocol):
    def __call__(self, spec: AIReportSpec) -> AIReportDraft: ...


SessionContextFactory = Callable[[], AbstractContextManager[Session]]
WeeklyReportRenderer = Callable[[Mapping[str, Any], PersistedAIReport], Sequence[str]]


@dataclass(frozen=True, slots=True, repr=False)
class WeeklyTrainingReportResult:
    status: str
    sent: int = 0
    failed: int = 0
    weekly_summary_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True, repr=False)
class _ProductionWeeklyLineTransport:
    def send(
        self,
        token: str,
        group_id: str,
        messages: Sequence[str],
    ) -> LineSendResult:
        return send_push_messages(token, group_id, messages)


def _weekly_ai_idempotency_key(
    projection: CompletedWeekSummary,
) -> str:
    canonical_input = json.dumps(
        jsonable(projection.summary_json),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()[:16]
    return (
        f"weekly:{projection.week_start.isoformat()}:"
        f"{WEEKLY_REPORT_PROMPT_VERSION}:{digest}"
    )


def _default_renderer(
    summary_json: Mapping[str, Any],
    report: PersistedAIReport,
) -> Sequence[str]:
    return format_weekly_report_messages(
        summary_json,
        report_text=report.report_text,
        report_json=report.report_json,
    )


@dataclass(frozen=True, slots=True, repr=False)
class WeeklyTrainingReportRunner:
    """Deep module owning weekly persistence, AI resolution and LINE retries.

    ``WeeklySummary`` is upserted on every invocation, including after a
    delivery has succeeded.  In contrast, the LineNotification payload is
    prepared once and never changed; retries send that exact canonical payload.
    """

    session_factory: SessionContextFactory
    generate: WeeklyReportGenerator
    token: str
    group_id: str
    transport: WeeklyLineTransport = _ProductionWeeklyLineTransport()
    render: WeeklyReportRenderer = _default_renderer

    def run(
        self,
        *,
        user_id: uuid.UUID,
        deterministic_context: Mapping[str, Any],
        today: date,
    ) -> WeeklyTrainingReportResult:
        projection = build_completed_week_summary(
            deterministic_context,
            today=today,
        )
        summary = self._save_summary(user_id, projection)
        pending_result = self._deliver_existing_pending(user_id)
        if pending_result is not None and pending_result.failed:
            return pending_result
        existing_delivery = self._existing_delivery(summary)
        if existing_delivery is not None:
            result = self._send_delivery(existing_delivery, summary.id)
            if pending_result is not None and pending_result.sent:
                return WeeklyTrainingReportResult(
                    status="retried_pending",
                    sent=pending_result.sent + result.sent,
                    failed=result.failed,
                    weekly_summary_id=summary.id,
                )
            return result

        spec = AIReportSpec(
            idempotency_key=_weekly_ai_idempotency_key(projection),
            user_id=user_id,
            report_scope="weekly",
            input_json=dict(summary.summary_json),
            prompt_version=WEEKLY_REPORT_PROMPT_VERSION,
            weekly_summary_id=summary.id,
            feature_version=WEEKLY_SUMMARY_VERSION,
        )
        canonical_report = self._resolve_report(spec)
        rendered_messages = self.render(summary.summary_json, canonical_report)
        delivery = self._prepare_delivery(
            summary_id=summary.id,
            report_id=canonical_report.id,
            rendered_messages=rendered_messages,
        )
        result = self._send_delivery(delivery, summary.id)
        if pending_result is not None and pending_result.sent:
            return WeeklyTrainingReportResult(
                status="sent" if result.sent else result.status,
                sent=pending_result.sent + result.sent,
                failed=result.failed,
                weekly_summary_id=summary.id,
            )
        return result

    def retry_pending(self, *, user_id: uuid.UUID) -> WeeklyTrainingReportResult:
        """Retry only immutable prepared payloads; never generate a new report."""
        pending_result = self._deliver_existing_pending(user_id)
        return pending_result or WeeklyTrainingReportResult(status="no_pending")

    def _deliver_existing_pending(
        self,
        user_id: uuid.UUID,
    ) -> WeeklyTrainingReportResult | None:
        """Retry earlier weeks before producing a newer report, in order."""
        with self.session_factory() as session:
            pending_ids = [
                notification.weekly_summary_id
                for notification in list_pending_weekly_notifications(
                    session,
                    user_id=user_id,
                )
                if notification.weekly_summary_id is not None
            ]
        if not pending_ids:
            return None
        sent = 0
        for summary_id in pending_ids:
            with self.session_factory() as session:
                notification = get_prepared_weekly_notification(session, summary_id)
                if notification is None:
                    raise RuntimeError(
                        "Pending weekly notification is not a valid prepared delivery"
                    )
                delivery = PreparedLineDelivery.from_model(notification)
            result = self._send_delivery(delivery, summary_id)
            sent += result.sent
            if result.failed:
                return WeeklyTrainingReportResult(
                    status="line_failed",
                    sent=sent,
                    failed=result.failed,
                    weekly_summary_id=summary_id,
                )
        return WeeklyTrainingReportResult(status="retried_pending", sent=sent)

    def _save_summary(
        self,
        user_id: uuid.UUID,
        projection: CompletedWeekSummary,
    ) -> WeeklySummary:
        with self.session_factory() as session:
            summary = save_weekly_summary(
                session,
                user_id=user_id,
                week_start=projection.week_start,
                week_end=projection.week_end,
                summary_version=WEEKLY_SUMMARY_VERSION,
                summary_json=projection.summary_json,
                **projection.metrics,
            )
            session.commit()
            return summary

    def _existing_delivery(
        self,
        summary: WeeklySummary,
    ) -> PreparedLineDelivery | None:
        with self.session_factory() as session:
            notification = get_prepared_weekly_notification(session, summary.id)
            if notification is None:
                return None
            return PreparedLineDelivery.from_model(notification)

    def _resolve_report(self, spec: AIReportSpec) -> PersistedAIReport:
        with self.session_factory() as session:
            self._validate_summary_subject(session, spec)
            existing = get_ai_report_by_idempotency_key(
                session,
                spec.user_id,
                spec.idempotency_key,
            )
            if existing is not None:
                self._validate_canonical_report(spec, existing)
                return PersistedAIReport.from_model(existing)

        # Provider I/O intentionally happens with no DB session open.
        draft = self.generate(spec)

        with self.session_factory() as session:
            canonical = save_ai_report(
                session,
                user_id=spec.user_id,
                report_scope="weekly",
                report_text=draft.report_text,
                input_json=spec.input_json,
                idempotency_key=spec.idempotency_key,
                model_name=draft.model_name,
                prompt_version=spec.prompt_version,
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
    def _validate_summary_subject(session: Session, spec: AIReportSpec) -> None:
        summary = session.get(WeeklySummary, spec.weekly_summary_id)
        if summary is None or summary.user_id != spec.user_id:
            raise ValueError("Weekly AI report spec does not match its user")

    @staticmethod
    def _validate_canonical_report(spec: AIReportSpec, report: AIReport) -> None:
        identity = (
            report.user_id,
            report.idempotency_key,
            report.report_scope,
            report.activity_id,
            report.weekly_summary_id,
            report.prompt_version,
            report.feature_version,
            report.input_json,
        )
        expected = (
            spec.user_id,
            spec.idempotency_key,
            "weekly",
            None,
            spec.weekly_summary_id,
            spec.prompt_version,
            spec.feature_version,
            jsonable(spec.input_json),
        )
        if identity != expected:
            raise RuntimeError(
                "Canonical weekly AI report does not match the requested identity"
            )

    def _prepare_delivery(
        self,
        *,
        summary_id: uuid.UUID,
        report_id: uuid.UUID,
        rendered_messages: Sequence[str],
    ) -> PreparedLineDelivery:
        with self.session_factory() as session:
            notification = prepare_weekly_notification(
                session,
                weekly_summary_id=summary_id,
                ai_report_id=report_id,
                rendered_messages=rendered_messages,
            )
            session.commit()
            return PreparedLineDelivery.from_model(notification)

    def _send_delivery(
        self,
        delivery: PreparedLineDelivery,
        summary_id: uuid.UUID,
    ) -> WeeklyTrainingReportResult:
        if not delivery.should_send:
            return WeeklyTrainingReportResult(
                status="already_sent",
                weekly_summary_id=summary_id,
            )
        response = self.transport.send(
            self.token,
            self.group_id,
            delivery.rendered_messages,
        )
        if not response.success:
            return WeeklyTrainingReportResult(
                status="line_failed",
                failed=1,
                weekly_summary_id=summary_id,
            )
        with self.session_factory() as session:
            mark_notification_sent(session, delivery.notification_id)
            session.commit()
        return WeeklyTrainingReportResult(
            status="sent",
            sent=1,
            weekly_summary_id=summary_id,
        )
