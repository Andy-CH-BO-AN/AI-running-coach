from datetime import date

from src.notifications.formatter import format_activity_message
from src.preprocessing.activity_window import normalize_activity_window
from src.preprocessing.coach_context import build_deterministic_coach_context
from src.preprocessing.coach_context_session_facts import reconcile_session_facts
from src.preprocessing.weekly_report import build_completed_week_summary
from tests.test_dashboard_adapter import run_adapter_case


def _strength_activity(*, training_load_marker=...):
    raw_data = {
        "strength": {
            "total_sets": 2,
            "active_sets": 2,
            "total_reps": 12,
            "total_volume_kg": 1200.0,
            "sets": [
                {
                    "set_index": 0,
                    "set_type": "active",
                    "exercise_names": ["Squat"],
                    "category": None,
                    "reps": 6,
                    "weight_kg": 100.0,
                    "duration_sec": None,
                },
                {
                    "set_index": 1,
                    "set_type": "active",
                    "exercise_names": ["Squat"],
                    "category": None,
                    "reps": 6,
                    "weight_kg": 100.0,
                    "duration_sec": None,
                },
            ],
        },
        "strength_sets_available": True,
    }
    if training_load_marker is not ...:
        raw_data["training_stress_score"] = training_load_marker
    return {
        "activity_id": 1201,
        "type": "strength_training",
        "date": "2026-08-20",
        "distance": None,
        "duration": 45,
        "average_heart_rate": 121,
        "splits": [],
        "raw_data": raw_data,
    }


def _context(activity):
    return build_deterministic_coach_context(
        normalize_activity_window([activity]),
        user_data={},
        today="2026-08-24",
    )


def _strength_session(context):
    week = next(
        week
        for week in context["weekly_analysis"]
        if week["week_start"] == "2026-08-17"
    )
    return week, week["sessions"][0]


def test_unknown_strength_training_load_stays_null_across_context_line_and_weekly_summary(tmp_path):
    context = _context(_strength_activity())
    week, session = _strength_session(context)

    assert session["training_load"] is None
    assert "training_load" in session["data_quality"]["missing_fields"]
    assert week["derived_training_load"] is None
    assert reconcile_session_facts([session], [])[0]["training_load"] is None

    message = format_activity_message(session, week)
    assert "訓練負荷：" not in message

    weekly = build_completed_week_summary(context, today=date(2026, 8, 24))
    assert weekly.summary_json["training_load"]["garmin_weekly_load"] is None
    strength_sport = next(
        sport
        for sport in weekly.summary_json["sports"]
        if sport["source_activity_type"] == "strength_training"
    )
    assert strength_sport["training_load"] is None

    dashboard = run_adapter_case(tmp_path, context)
    assert dashboard["latest"]["training_load"] is None


def test_explicit_zero_strength_training_load_remains_measured_zero():
    context = _context(_strength_activity(training_load_marker=0))
    week, session = _strength_session(context)

    assert session["training_load"] == 0
    assert "training_load" not in session["data_quality"]["missing_fields"]
    assert week["derived_training_load"] == 0
    assert "訓練負荷：0" in format_activity_message(session, week)
