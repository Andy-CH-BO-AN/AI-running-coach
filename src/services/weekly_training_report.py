"""Create, persist, and deliver one previous-complete-week coaching report."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Protocol

from sqlalchemy.orm import Session

from src.db.mappers import jsonable
from src.db.models import AIReport, LineNotification, WeeklySummary, utc_now
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

WEEKLY_REPORT_PROMPT_VERSION = "weekly-coach:v4"
# LINE retains a retry key for 24 hours.  Stop one hour earlier so a delayed
# request never leaves the documented duplicate-protection window.
LINE_RETRY_KEY_SAFE_WINDOW = timedelta(hours=23)


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
    input_json: Mapping[str, Any],
) -> str:
    canonical_input = json.dumps(
        jsonable(input_json),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()[:16]
    return (
        f"weekly:{projection.week_start.isoformat()}:"
        f"{WEEKLY_REPORT_PROMPT_VERSION}:{digest}"
    )


def _athlete_profile_input(
    deterministic_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Select existing deterministic athlete facts useful to weekly coaching."""
    physio_metrics = deterministic_context.get("physio_metrics")
    if not isinstance(physio_metrics, Mapping):
        physio_metrics = {}
    personal_records = deterministic_context.get("pb_validation_seed")
    return {
        "vo2max": physio_metrics.get("vo2max"),
        "max_heart_rate": physio_metrics.get("max_heart_rate"),
        "resting_heart_rate": physio_metrics.get("resting_heart_rate"),
        "lactate_threshold": physio_metrics.get("lactate_threshold"),
        "running_personal_records": [
            {"event": record.get("event"), "raw_value": record.get("raw_value")}
            for record in personal_records
            if isinstance(record, Mapping)
        ]
        if isinstance(personal_records, list)
        else [],
        "pace_zones": physio_metrics.get("pace_zones", []),
    }


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
        core_goal: str | None = None,
        training_preferences: str | None = None,
    ) -> WeeklyTrainingReportResult:
        projection = build_completed_week_summary(
            deterministic_context,
            today=today,
        )
        summary = self._save_summary(user_id, projection)
        pending_result = self._deliver_existing_pending(
            user_id,
            report_expired=False,
        )
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

        input_json = jsonable(
            {
                **summary.summary_json,
                "core_goal": core_goal,
                "training_preferences": training_preferences,
                "athlete_profile": _athlete_profile_input(deterministic_context),
            }
        )
        spec = AIReportSpec(
            idempotency_key=_weekly_ai_idempotency_key(projection, input_json),
            user_id=user_id,
            report_scope="weekly",
            input_json=input_json,
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
        *,
        report_expired: bool = True,
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
        expired_summary_id: uuid.UUID | None = None
        for summary_id in pending_ids:
            with self.session_factory() as session:
                notification = get_prepared_weekly_notification(session, summary_id)
                if notification is None:
                    raise RuntimeError(
                        "Pending weekly notification is not a valid prepared delivery"
                    )
                delivery = PreparedLineDelivery.from_model(notification)
                if not delivery.should_send:
                    continue
                if self._retry_window_expired(delivery):
                    expired_summary_id = expired_summary_id or summary_id
                    continue
            result = self._send_delivery(delivery, summary_id)
            sent += result.sent
            if result.failed:
                return WeeklyTrainingReportResult(
                    status=result.status,
                    sent=sent,
                    failed=result.failed,
                    weekly_summary_id=summary_id,
                )
        if expired_summary_id is not None and report_expired:
            return WeeklyTrainingReportResult(
                status="retry_window_expired",
                sent=sent,
                failed=1,
                weekly_summary_id=expired_summary_id,
            )
        return (
            WeeklyTrainingReportResult(status="retried_pending", sent=sent)
            if sent
            else None
        )

    @staticmethod
    def _retry_window_expired(delivery: PreparedLineDelivery) -> bool:
        """Fail closed before LINE can no longer deduplicate this payload."""
        return utc_now() - delivery.recorded_at >= LINE_RETRY_KEY_SAFE_WINDOW

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
        if self._retry_window_expired(delivery):
            return WeeklyTrainingReportResult(
                status="retry_window_expired",
                failed=1,
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
