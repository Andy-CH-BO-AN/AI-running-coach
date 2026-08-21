from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List

from src.preprocessing.coach_context_athlete_metrics import (
    _mechanics_assessment,
    _mechanics_tips,
)
from src.preprocessing.coach_context_session_facts import (
    SessionEvidenceIndex,
    SessionFactContractError,
    build_session_evidence_index,
    reconcile_session_facts,
)
from src.preprocessing.coach_context_utils import _round_or_none

WEEKLY_TOTAL_KEYS = {
    "total_distance_km",
    "total_duration_min",
    "training_load",
    "derived_total_distance_km",
    "derived_total_duration_min",
    "derived_training_load",
}


def overlay_deterministic(ai_value: Any, deterministic_value: Any) -> Any:
    if isinstance(ai_value, dict) and isinstance(deterministic_value, dict):
        merged = deepcopy(ai_value)
        for key, value in deterministic_value.items():
            merged[key] = overlay_deterministic(merged.get(key), value)
        return merged
    return deepcopy(deterministic_value)


def _enforce_running_mechanics(
    result: Dict[str, Any],
    deterministic_context: Dict[str, Any],
) -> None:
    context_mechanics = deterministic_context.get("running_mechanics") or {}
    if not context_mechanics:
        return

    ai_mechanics = result.get("running_mechanics") or {}
    mechanics = overlay_deterministic(ai_mechanics, context_mechanics)
    for key in (
        "cadence_avg",
        "ground_contact_ms",
        "vertical_oscillation_cm",
        "stride_length_m",
    ):
        if isinstance(mechanics.get(key), dict):
            mechanics[key]["assessment"] = _mechanics_assessment(key, mechanics[key].get("value"))
    mechanics["improvement_tips"] = _mechanics_tips(mechanics)

    result["running_mechanics"] = mechanics


def _enforce_weekly_analysis(
    report: Dict[str, Any],
    deterministic_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    raw_ai_weeks = report.get("weekly_analysis")
    if not isinstance(raw_ai_weeks, list):
        raw_ai_weeks = []
    ai_weeks: dict[Any, dict[str, Any]] = {}
    for week in raw_ai_weeks:
        if not isinstance(week, dict):
            continue
        week_start = week.get("week_start")
        try:
            ai_weeks[week_start] = week
        except TypeError:
            continue
    context_weeks = deterministic_context.get("weekly_analysis")
    if not isinstance(context_weeks, list):
        raise SessionFactContractError(
            "deterministic weekly_analysis: expected a list"
        )
    enforced_weeks: List[Dict[str, Any]] = []
    for week_index, context_week in enumerate(context_weeks):
        if not isinstance(context_week, dict):
            raise SessionFactContractError(
                f"deterministic weekly_analysis[{week_index}]: expected an object"
            )
        context_week_start = context_week.get("week_start")
        try:
            ai_week = ai_weeks.get(context_week_start, {})
        except TypeError as exc:
            raise SessionFactContractError(
                f"deterministic weekly_analysis[{week_index}].week_start: "
                "expected a scalar"
            ) from exc
        week = deepcopy(ai_week) if isinstance(ai_week, dict) else {}
        for key in WEEKLY_TOTAL_KEYS:
            week.pop(key, None)

        ai_sessions = week.get("sessions")
        week["week_label"] = context_week.get("week_label")
        week["week_start"] = context_week.get("week_start")
        week.setdefault("key_observation", "")
        week.setdefault("weekly_assessment", "")
        week.setdefault("weekly_recommendation", "")
        raw_focuses = week.get("intensity_focuses")
        if not isinstance(raw_focuses, list):
            raw_focuses = []
        normalized_focuses = []
        for item in raw_focuses[:2]:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized_focuses.append(
                        {
                            "dimension": "intensity",
                            "headline": "強度重點",
                            "analysis": text,
                        }
                    )
                continue
            if not isinstance(item, dict):
                continue

            analysis = str(item.get("analysis") or item.get("text") or "").strip()
            if not analysis:
                continue
            normalized_focuses.append(
                {
                    "dimension": str(item.get("dimension") or "intensity"),
                    "headline": str(item.get("headline") or "強度重點").strip() or "強度重點",
                    "analysis": analysis,
                }
            )
        week["intensity_focuses"] = normalized_focuses
        raw_cross_training_focus = week.get("cross_training_focus")
        if isinstance(raw_cross_training_focus, dict):
            cross_analysis = str(raw_cross_training_focus.get("analysis") or "").strip()
            if cross_analysis:
                week["cross_training_focus"] = {
                    "activity_id": raw_cross_training_focus.get("activity_id"),
                    "headline": str(raw_cross_training_focus.get("headline") or "交叉訓練重點").strip()
                    or "交叉訓練重點",
                    "analysis": cross_analysis,
                }
            else:
                week["cross_training_focus"] = None
        else:
            week["cross_training_focus"] = None
        week["risk_flags"] = deepcopy(context_week.get("risk_flags") or [])
        week["sessions"] = reconcile_session_facts(
            context_week.get("sessions"),
            ai_sessions,
        )
        enforced_weeks.append(week)
    return enforced_weeks


def _enforce_next_week_plan(
    report: Dict[str, Any],
    deterministic_context: Dict[str, Any],
) -> Dict[str, Any]:
    ai_plan = deepcopy(report.get("next_week_plan") or {})
    seed = deterministic_context.get("next_week_plan_seed") or {}
    ai_days = {
        day.get("date"): day
        for day in ai_plan.get("days", [])
        if isinstance(day, dict)
    }
    days: List[Dict[str, Any]] = []
    for seed_day in seed.get("days", []):
        if not isinstance(seed_day, dict):
            continue
        ai_day = deepcopy(ai_days.get(seed_day.get("date"), {}))
        ai_day["date"] = seed_day.get("date")
        ai_day["day_of_week"] = seed_day.get("day_of_week")
        ai_day.setdefault("session_type", "rest")
        ai_day.setdefault("title", "恢復日")
        ai_day.setdefault("description", "")
        if str(ai_day["session_type"]).strip().lower() == "strength_training":
            ai_day["distance_km"] = None
        else:
            ai_day.setdefault("distance_km", 0)
        ai_day.setdefault("duration_min", 0)
        ai_day.setdefault("intensity", "rest")
        ai_day.setdefault("key_workout", False)
        ai_day.setdefault("weather_consideration", "")
        days.append(ai_day)

    if days:
        ai_plan["week_start"] = seed.get("week_start")
        ai_plan["days"] = days
        ai_plan["total_distance_km"] = _round_or_none(sum(day.get("distance_km") or 0 for day in days), 2) or 0.0
    return ai_plan


def _read_path_value(payload: Dict[str, Any], path: str) -> Any:
    current: Any = payload
    for segment in path.split("."):
        match = re.match(r"^([A-Za-z_]+)(?:\[(\d+)\])?$", segment)
        if not match:
            return None
        if not isinstance(current, dict):
            return None
        current = current.get(match.group(1))
        if match.group(2) is not None:
            if not isinstance(current, list):
                return None
            index = int(match.group(2))
            if index >= len(current):
                return None
            current = current[index]
    return current


def _enforce_evidence_source_paths(
    report: Dict[str, Any],
    references: SessionEvidenceIndex,
) -> None:
    for evidence in report.get("evidence_links") or []:
        if not isinstance(evidence, dict):
            continue
        for session in evidence.get("supporting_sessions") or []:
            if not isinstance(session, dict):
                continue
            session.pop("type", None)
            reference = references.resolve(session)
            if reference is None:
                continue
            references.project_supporting_session(session, reference)


def _split_weekly_session_source_path(source_path: Any) -> tuple[str, str] | None:
    match = re.match(r"^(weekly_analysis\[\d+\]\.sessions\[\d+\])(?:\.(.+))?$", str(source_path or ""))
    if not match:
        return None
    return match.group(1), match.group(2) or ""


def _enforce_evidence_metric_source_paths(
    report: Dict[str, Any],
    references: SessionEvidenceIndex,
    original_report: Dict[str, Any] | None = None,
) -> None:
    original_payload = original_report if isinstance(original_report, dict) else report
    for evidence in report.get("evidence_links") or []:
        if not isinstance(evidence, dict):
            continue
        for metric in evidence.get("supporting_metrics") or []:
            if not isinstance(metric, dict):
                continue

            source_path_parts = _split_weekly_session_source_path(metric.get("source_path"))
            if source_path_parts is None:
                continue

            original_session_path, field_suffix = source_path_parts
            reference = None

            activity_id = metric.get("activity_id")
            if activity_id is not None:
                reference = references.resolve({"activity_id": activity_id})

            if reference is None:
                original_session = deepcopy(_read_path_value(original_payload, original_session_path) or {})
                if isinstance(original_session, dict):
                    reference = references.resolve(original_session)

            if reference is None:
                continue

            metric["source_path"] = (
                f"{reference.source_path}.{field_suffix}"
                if field_suffix
                else reference.source_path
            )


def enforce_deterministic_report_fields(
    report: Dict[str, Any],
    deterministic_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Overlay deterministic source-of-truth fields after AI analysis."""

    result = deepcopy(report) if isinstance(report, dict) else {}
    original_report = deepcopy(result)
    meta = deepcopy(result.get("meta") or {})
    context_meta = deterministic_context.get("meta") or {}
    for key in ("analysis_period_weeks", "today"):
        if key in context_meta:
            meta[key] = context_meta[key]
    result["meta"] = meta

    result["weekly_analysis"] = _enforce_weekly_analysis(result, deterministic_context)

    if deterministic_context.get("hr_zone_distribution"):
        hr_zone_distribution = deepcopy(result.get("hr_zone_distribution") or {})
        for key in ("period_weeks", "zones", "is_polarized"):
            if key in deterministic_context["hr_zone_distribution"]:
                hr_zone_distribution[key] = deepcopy(deterministic_context["hr_zone_distribution"][key])
        result["hr_zone_distribution"] = hr_zone_distribution

    if deterministic_context.get("power_zone_distribution"):
        power_zone_distribution = deepcopy(result.get("power_zone_distribution") or {})
        for key in ("period_weeks", "zones"):
            if key in deterministic_context["power_zone_distribution"]:
                power_zone_distribution[key] = deepcopy(deterministic_context["power_zone_distribution"][key])
        result["power_zone_distribution"] = power_zone_distribution

    if deterministic_context.get("physio_metrics"):
        result["physio_metrics"] = overlay_deterministic(
            result.get("physio_metrics") or {},
            deterministic_context["physio_metrics"],
        )

    _enforce_running_mechanics(result, deterministic_context)

    if deterministic_context.get("cross_training"):
        result["cross_training"] = overlay_deterministic(
            result.get("cross_training") or {},
            deterministic_context["cross_training"],
        )

    load_context = deterministic_context.get("load_assessment") or {}
    if load_context:
        load_assessment = deepcopy(result.get("load_assessment") or {})
        for key in ("current_tss_weekly", "optimal_tss_range", "status"):
            if key in load_context:
                load_assessment[key] = deepcopy(load_context[key])
        result["load_assessment"] = load_assessment

    result["next_week_plan"] = _enforce_next_week_plan(result, deterministic_context)
    session_references = build_session_evidence_index(
        result.get("weekly_analysis")
    )
    _enforce_evidence_source_paths(result, session_references)
    _enforce_evidence_metric_source_paths(
        result,
        session_references,
        original_report=original_report,
    )
    if deterministic_context.get("twelve_week_summary"):
        result["twelve_week_summary"] = deepcopy(deterministic_context["twelve_week_summary"])
    return result


_overlay_deterministic = overlay_deterministic
