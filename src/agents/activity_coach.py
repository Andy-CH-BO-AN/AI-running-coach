"""Gemini adapter for concise analysis of one completed Garmin activity."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agents import coach as coach_agent
from src.notifications.text_utils import utf16_length
from src.services.ai_report_resolution import AIReportDraft, AIReportSpec

ACTIVITY_PROMPT_PATH = Path("prompts/activity_coach.md")
ACTIVITY_PROMPT_VERSION = "activity-coach:v3"
MIN_ANALYSIS_UTF16_LENGTH = 100
MAX_ANALYSIS_UTF16_LENGTH = 600


class ActivityCoachError(RuntimeError):
    """The provider did not return usable Activity coaching output."""


def _normalize_analysis(payload: dict[str, Any]) -> str:
    analysis = payload.get("analysis")
    if not isinstance(analysis, str) or not analysis.strip():
        raise ActivityCoachError("Activity AI response is missing analysis")
    normalized = analysis.strip()
    if not MIN_ANALYSIS_UTF16_LENGTH <= utf16_length(normalized) <= MAX_ANALYSIS_UTF16_LENGTH:
        raise ActivityCoachError("Activity AI response has an invalid analysis length")
    return normalized


def _generate_analysis(full_prompt: str) -> tuple[str, str]:
    """Reuse established model fallbacks while validating the compact response."""
    switched_to_vertexai = False
    last_error: Exception | None = None
    for model_name in coach_agent.MODEL_FALLBACKS:
        try:
            return model_name, _normalize_analysis(
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
                    return model_name, _normalize_analysis(
                        coach_agent._generate_content_with_retries(model_name, full_prompt)
                    )
                except Exception as vertex_error:
                    last_error = vertex_error
            continue
    raise ActivityCoachError("Activity AI coach is unavailable") from last_error


def generate_activity_report(spec: AIReportSpec) -> AIReportDraft:
    """Generate one short interpretation from deterministic Activity facts only."""
    if spec.report_scope != "activity" or spec.activity_id is None:
        raise ValueError("Activity generation requires an Activity AI report spec")
    try:
        system_prompt = ACTIVITY_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ActivityCoachError("Activity AI prompt could not be read") from exc

    full_prompt = (
        f"{system_prompt}\n\n"
        "### Deterministic activity facts (source of truth)\n"
        f"{json.dumps(spec.input_json, ensure_ascii=False, indent=2)}"
    )
    model_name, analysis = _generate_analysis(full_prompt)
    return AIReportDraft(
        report_text=analysis,
        model_name=model_name,
        report_json={"analysis": analysis},
    )
