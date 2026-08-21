"""Gemini adapter for concise analysis of one completed Garmin activity."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.agents import coach as coach_agent
from src.notifications.text_utils import utf16_length
from src.services.ai_report_resolution import AIReportDraft, AIReportSpec

ACTIVITY_PROMPT_PATH = Path("prompts/activity_coach.md")
ACTIVITY_PROMPT_VERSION = "activity-coach:v5"
MIN_ANALYSIS_UTF16_LENGTH = 100
MAX_ANALYSIS_UTF16_LENGTH = 600
_UNKNOWN_LOAD_CLAIM = re.compile(
    r"0\s*TSS|負荷.{0,4}(?:偏低|不足|太低|很低)|undertraining|(?:增加|提高|提升).{0,12}(?:TSS|訓練負荷|負荷)",
    re.IGNORECASE,
)
_UNKNOWN_LOAD_NEUTRAL = re.compile(r"負荷(?:資料|數據)(?:不足|不可得)")
_UNKNOWN_LOAD_NO_INCREASE = re.compile(
    r"(?:不(?:應|要|宜|該|需|需要|建議)|避免|無需|不用|勿)"
    r"(?:(?:再|額外|進一步|立即|直接|刻意|主動|盲目|過度|貿然|急著|輕易)\s*){0,2}"
    r"(?:增加|提高|提升).{0,12}(?:TSS|訓練負荷|負荷)",
    re.IGNORECASE,
)


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


def _subject_activity_has_unknown_load(input_json: dict[str, Any]) -> bool:
    activity = input_json.get("activity")
    return isinstance(activity, dict) and activity.get("training_load") is None


def _contains_unknown_load_claim(text: str) -> bool:
    normalized = _UNKNOWN_LOAD_NEUTRAL.sub("", text)
    normalized = _UNKNOWN_LOAD_NO_INCREASE.sub("", normalized)
    return bool(_UNKNOWN_LOAD_CLAIM.search(normalized))


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
    if _subject_activity_has_unknown_load(spec.input_json) and _contains_unknown_load_claim(analysis):
        raise ActivityCoachError("Activity AI response misinterprets unknown training load")
    return AIReportDraft(
        report_text=analysis,
        model_name=model_name,
        report_json={"analysis": analysis},
    )
