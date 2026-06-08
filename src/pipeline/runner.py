from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.pipeline.activity_payloads import ActivityPayloadProvider
from src.pipeline.goal_prompt import GoalPromptOverrides
from src.preprocessing.coach_context import build_deterministic_coach_context
from src.preprocessing.data_processor import preprocess_data
from src.services.artifacts import persist_pipeline_artifacts
from src.services.report_generator import generate_coach_report

RAW_DATA_DIR = Path("data/raw")
PROCESSED_DATA_DIR = Path("data/processed")
OUTPUT_DIR = Path("output")
GOAL_PROMPT_PATH = Path("prompts/goal.md")


def _build_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def _persist_pipeline_artifacts(
    timestamp: str,
    processed_data: List[Dict[str, Any]],
    deterministic_context: Dict[str, Any],
    response: Dict[str, Any],
) -> Path:
    return persist_pipeline_artifacts(
        timestamp=timestamp,
        processed_data=processed_data,
        deterministic_context=deterministic_context,
        response=response,
        processed_dir=PROCESSED_DATA_DIR,
        output_dir=OUTPUT_DIR,
    )


def _load_or_fetch_activity_payloads(
    activity_limit: int,
    fetch_limit: int,
    timestamp: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return ActivityPayloadProvider(raw_data_dir=RAW_DATA_DIR).load_or_fetch(
        activity_limit=activity_limit,
        fetch_limit=fetch_limit,
        timestamp=timestamp,
    )


def _generate_coach_report(
    processed_data: List[Dict[str, Any]],
    user_data: Dict[str, Any],
    deterministic_context: Dict[str, Any],
    goal_overrides: GoalPromptOverrides | None = None,
) -> Dict[str, Any]:
    return generate_coach_report(
        processed_data=processed_data,
        user_data=user_data,
        deterministic_context=deterministic_context,
        goal_overrides=goal_overrides,
        goal_prompt_path=GOAL_PROMPT_PATH,
    )


def run_pipeline(
    activity_limit: int = 75,
    fetch_limit: int | None = None,
    goal_overrides: GoalPromptOverrides | None = None,
) -> Optional[str]:
    print("🚀 Starting Garmin AI Coach Pipeline...")

    timestamp = _build_timestamp()
    raw_activities, user_data = _load_or_fetch_activity_payloads(
        activity_limit=activity_limit,
        fetch_limit=activity_limit if fetch_limit is None else fetch_limit,
        timestamp=timestamp,
    )

    if not raw_activities:
        print("❌ No activities found.")
        return None

    print("🧹 Preprocessing data...")
    processed_data = preprocess_data(raw_activities)
    if not processed_data:
        print("⚠️ No data left after preprocessing.")
        return None

    print("🧮 Building deterministic coach context...")
    deterministic_context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=user_data,
        raw_activities=raw_activities,
        today=timestamp,
    )

    print("🤖 Analyzing data with AI Coach...")
    response = _generate_coach_report(
        processed_data=processed_data,
        user_data=user_data,
        deterministic_context=deterministic_context,
        goal_overrides=goal_overrides,
    )

    print("💾 Generating structured JSON report...")
    report_path = _persist_pipeline_artifacts(
        timestamp=timestamp,
        processed_data=processed_data,
        deterministic_context=deterministic_context,
        response=response,
    )

    print("✨ Pipeline completed!")
    print(f"📄 JSON Report: {report_path}")
    return str(report_path)
