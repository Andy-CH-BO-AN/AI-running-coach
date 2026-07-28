from datetime import datetime
import os
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
    activity_limit: int | None = None,
    fetch_limit: int | None = None,
    goal_overrides: GoalPromptOverrides | None = None,
) -> Optional[str]:
    print("🚀 Starting Garmin AI Coach Pipeline...")

    if activity_limit is None:
        activity_limit = int(os.getenv("GARMIN_ACTIVITY_LIMIT", "75"))
    if os.getenv("DATABASE_AVAILABLE", "true").lower() == "false":
        print(
            "⚠️ Running in degraded mode: DB persistence is disabled; "
            f"Garmin activity limit={activity_limit}."
        )

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

    # ── LINE 通知
    _run_line_notification(timestamp)

    return str(report_path)


def _run_line_notification(timestamp: str) -> None:
    """執行 LINE 群組通知（pipeline 最後一步）。

    使用 persist_pipeline_artifacts 寫出的實際 coach_context 路徑，
    不自行掃描資料夾或猜測檔名。

    未預期錯誤向上拋出，避免把非 DB 程式錯誤誤判成 degraded mode。
    """
    from src.notifications.notifier import run_line_notification
    from src.services.artifacts import pipeline_artifact_paths

    coach_context_path = pipeline_artifact_paths(
        timestamp,
        processed_dir=PROCESSED_DATA_DIR,
        output_dir=OUTPUT_DIR,
    )["coach_context"]

    result = run_line_notification(str(coach_context_path))
    print(f"📱 LINE notification: {result}")
