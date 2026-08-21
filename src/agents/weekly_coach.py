"""Gemini adapter for the concise weekly coaching report."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.agents import coach as coach_agent
from src.notifications.text_utils import utf16_length
from src.services.ai_report_resolution import AIReportDraft, AIReportSpec

WEEKLY_PROMPT_PATH = Path("prompts/weekly_coach.md")
WEEKLY_PROMPT_VERSION = "weekly-coach:v5"
MIN_ANALYSIS_UTF16_LENGTH = 140
MAX_ANALYSIS_UTF16_LENGTH = 320
MAX_RECOMMENDATION_UTF16_LENGTH = 320
MAX_PLAN_SESSION_UTF16_LENGTH = 100
MAX_PLAN_DESCRIPTION_UTF16_LENGTH = 360
_UNKNOWN_LOAD_CLAIM = re.compile(
    r"0\s*TSS|負荷.{0,4}(?:偏低|不足|太低|很低)|undertraining|(?:增加|提高|提升).{0,12}(?:TSS|訓練負荷|負荷)",
    re.IGNORECASE,
)
_UNKNOWN_LOAD_NEUTRAL = re.compile(r"負荷(?:資料|數據)(?:不足|不可得)")
_UNKNOWN_LOAD_NO_INCREASE = re.compile(
    r"(?:不(?:應|要|宜|該|需|需要|建議)|避免|無需|不用|勿).{0,8}"
    r"(?:增加|提高|提升).{0,12}(?:TSS|訓練負荷|負荷)",
    re.IGNORECASE,
)


class WeeklyCoachError(RuntimeError):
    """The provider did not return a usable weekly coaching payload."""


def _text(
    value: Any,
    *,
    field: str,
    maximum_utf16_length: int,
    minimum_utf16_length: int = 1,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WeeklyCoachError(f"Weekly AI response is missing {field}")
    normalized = value.strip()
    length = utf16_length(normalized)
    if not minimum_utf16_length <= length <= maximum_utf16_length:
        raise WeeklyCoachError(f"Weekly AI response has an invalid {field} length")
    return normalized


def _normalize_plan(payload: dict[str, Any]) -> list[dict[str, str]]:
    plan = payload.get("next_week_plan")
    if not isinstance(plan, list) or len(plan) != 7:
        raise WeeklyCoachError("Weekly AI response must contain a seven-day plan")
    normalized: list[dict[str, str]] = []
    for entry in plan:
        if not isinstance(entry, dict):
            raise WeeklyCoachError("Weekly AI plan entries must be objects")
        normalized.append(
            {
                "session": _text(
                    entry.get("session"),
                    field="next_week_plan.session",
                    maximum_utf16_length=MAX_PLAN_SESSION_UTF16_LENGTH,
                ),
                "description": _text(
                    entry.get("description"),
                    field="next_week_plan.description",
                    maximum_utf16_length=MAX_PLAN_DESCRIPTION_UTF16_LENGTH,
                ),
            }
        )
    return normalized


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "analysis": _text(
            payload.get("analysis"),
            field="analysis",
            minimum_utf16_length=MIN_ANALYSIS_UTF16_LENGTH,
            maximum_utf16_length=MAX_ANALYSIS_UTF16_LENGTH,
        ),
        "recommendation": _text(
            payload.get("recommendation"),
            field="recommendation",
            maximum_utf16_length=MAX_RECOMMENDATION_UTF16_LENGTH,
        ),
        "next_week_plan": _normalize_plan(payload),
    }


def _has_unknown_load(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (key in {"training_load", "derived_training_load"} and item is None)
            or _has_unknown_load(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_unknown_load(item) for item in value)
    return False


def _contains_unknown_load_claim(payload: dict[str, Any]) -> bool:
    texts = [payload["analysis"], payload["recommendation"]]
    texts.extend(entry["description"] for entry in payload["next_week_plan"])
    for text in texts:
        normalized = _UNKNOWN_LOAD_NEUTRAL.sub("", text)
        normalized = _UNKNOWN_LOAD_NO_INCREASE.sub("", normalized)
        if _UNKNOWN_LOAD_CLAIM.search(normalized):
            return True
    return False


def _generate_payload(full_prompt: str) -> tuple[str, dict[str, Any]]:
    """Reuse the established model fallback and retry policy for weekly output."""
    switched_to_vertexai = False
    last_error: Exception | None = None
    for model_name in coach_agent.MODEL_FALLBACKS:
        try:
            return model_name, _normalize_payload(
                coach_agent._generate_content_with_retries(model_name, full_prompt)
            )
        except Exception as exc:
            last_error = exc
            if (
                not switched_to_vertexai
                and not getattr(coach_agent.client, "vertexai", False)
                and coach_agent._is_vertexai_payload_mismatch(exc)
            ):
                coach_agent.client = coach_agent._build_genai_client(vertexai=True)
                switched_to_vertexai = True
                try:
                    return model_name, _normalize_payload(
                        coach_agent._generate_content_with_retries(model_name, full_prompt)
                    )
                except Exception as vertex_error:
                    last_error = vertex_error
            continue
    raise WeeklyCoachError("Weekly AI coach is unavailable") from last_error


def generate_weekly_report(spec: AIReportSpec) -> AIReportDraft:
    """Generate one validated coaching draft from deterministic weekly facts."""
    if spec.report_scope != "weekly" or spec.weekly_summary_id is None:
        raise ValueError("Weekly generation requires a weekly AI report spec")
    try:
        system_prompt = WEEKLY_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise WeeklyCoachError("Weekly AI prompt could not be read") from exc
    full_prompt = (
        f"{system_prompt}\n\n"
        "### Deterministic weekly facts (source of truth)\n"
        f"{json.dumps(spec.input_json, ensure_ascii=False, indent=2)}"
    )
    model_name, payload = _generate_payload(full_prompt)
    if _has_unknown_load(spec.input_json) and _contains_unknown_load_claim(payload):
        raise WeeklyCoachError("Weekly AI response misinterprets unknown training load")
    report_text = f"{payload['analysis']}\n\n建議：{payload['recommendation']}"
    return AIReportDraft(
        report_text=report_text,
        model_name=model_name,
        report_json=payload,
    )
