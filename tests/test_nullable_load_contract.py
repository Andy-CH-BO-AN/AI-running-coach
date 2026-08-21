from pathlib import Path

from src.preprocessing.coach_context_enforcement import (
    UNKNOWN_LOAD_LABEL,
    UNKNOWN_LOAD_RECOMMENDATION,
    enforce_deterministic_report_fields,
)


def _load_context(current_tss_weekly, status):
    return {
        "meta": {},
        "weekly_analysis": [],
        "load_assessment": {
            "current_tss_weekly": current_tss_weekly,
            "optimal_tss_range": {"min": None, "max": None},
            "status": status,
        },
        "next_week_plan_seed": {"days": []},
    }


def test_unknown_load_overrides_misleading_ai_copy():
    report = {
        "load_assessment": {
            "current_tss_weekly": 0,
            "optimal_tss_range": {"min": 80, "max": 120},
            "status": "undertraining",
            "label": "本週負荷偏低",
            "recommendation": "下週增加 10% TSS。",
        }
    }

    enforced = enforce_deterministic_report_fields(
        report,
        _load_context(None, "unknown"),
    )
    load = enforced["load_assessment"]

    assert load["current_tss_weekly"] is None
    assert load["status"] == "unknown"
    assert load["label"] == UNKNOWN_LOAD_LABEL
    assert load["recommendation"] == UNKNOWN_LOAD_RECOMMENDATION
    assert "偏低" not in load["label"]
    assert "0 TSS" not in load["recommendation"]


def test_explicit_zero_load_remains_measured_zero():
    report = {
        "load_assessment": {
            "current_tss_weekly": 0,
            "optimal_tss_range": {"min": 80, "max": 120},
            "status": "undertraining",
            "label": "本週負荷偏低",
            "recommendation": "依其他恢復指標決定是否增加訓練量。",
        }
    }

    enforced = enforce_deterministic_report_fields(
        report,
        _load_context(0, "undertraining"),
    )
    load = enforced["load_assessment"]

    assert load["current_tss_weekly"] == 0
    assert load["status"] == "undertraining"
    assert load["label"] == "本週負荷偏低"
    assert load["recommendation"] == "依其他恢復指標決定是否增加訓練量。"


def test_coach_prompt_declares_nullable_load_contract():
    prompt = Path("prompts/coach.md").read_text(encoding="utf-8")

    assert '"training_load": "number | null"' in prompt
    assert '"current_tss_weekly": "number | null"' in prompt
    assert '"status": "undertraining | optimal | overreaching | overtraining | unknown"' in prompt
    assert "不得以 0 代替未知值" in prompt


def test_all_coaching_prompts_declare_nullable_metric_contracts():
    activity_prompt = Path("prompts/activity_coach.md").read_text(encoding="utf-8")
    weekly_prompt = Path("prompts/weekly_coach.md").read_text(encoding="utf-8")
    coach_prompt = Path("prompts/coach.md").read_text(encoding="utf-8")

    assert "training_load" in activity_prompt and "絕不是實測 0" in activity_prompt
    assert "任一納入活動的負荷未知時，週總負荷也未知" in weekly_prompt
    assert '"avg_hr": "number | null"' in coach_prompt
    assert '"training_effect_aerobic": "number | null"' in coach_prompt
    assert '"stride_length_m": "number | null"' in coach_prompt
    assert '"estimated_temp_c": "number | null"' in coach_prompt
    assert '"humidity_pct": "number | null"' in coach_prompt
    assert '"hr_impact": "string | null"' in coach_prompt
    assert "swim/bike/strength_training" in coach_prompt
