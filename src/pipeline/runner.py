import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.agents.coach import coach
from src.ingestion.garmin_client import get_garmin_activities
from src.preprocessing.data_processor import preprocess_data

RAW_DATA_DIR = Path("data/raw")
PROCESSED_DATA_DIR = Path("data/processed")
OUTPUT_DIR = Path("output")
GOAL_PROMPT_PATH = Path("prompts/goal.md")


def _build_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=4)


def _write_processed_csv(path: Path, processed_data: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.json_normalize(processed_data).to_csv(path, index=False, encoding="utf-8-sig")


def _write_markdown_report(path: Path, response: str, activity_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        file_obj.write("# 🏃‍♂️ Garmin AI Coach Training Report\n\n")
        file_obj.write(f"- **分析日期:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file_obj.write(f"- **分析活動數量:** {activity_count}\n\n")
        file_obj.write("---\n\n")
        file_obj.write(response)
        file_obj.write("\n\n---\n*Happy Running!*")


def _persist_pipeline_artifacts(
    timestamp: str,
    processed_data: List[Dict[str, Any]],
    response: str,
) -> Path:
    _write_processed_csv(PROCESSED_DATA_DIR / f"processed_{timestamp}.csv", processed_data)

    report_path = OUTPUT_DIR / f"ai_report_{timestamp}.md"
    _write_markdown_report(report_path, response, len(processed_data))
    return report_path


def _persist_raw_artifacts(
    timestamp: str,
    raw_activities: List[Dict[str, Any]],
    user_data: Dict[str, Any],
) -> None:
    _write_json(RAW_DATA_DIR / f"garmin_raw_{timestamp}.json", raw_activities)
    _write_json(RAW_DATA_DIR / f"garmin_user_{timestamp}.json", user_data)


def run_pipeline(activity_limit: int = 75) -> Optional[str]:
    print("🚀 Starting Garmin AI Coach Pipeline...")

    garmin_data = get_garmin_activities(activity_limit)
    raw_activities = garmin_data.get("activities", [])
    user_data = garmin_data.get("user_data", {})

    if not raw_activities:
        print("❌ No activities found.")
        return None

    timestamp = _build_timestamp()
    _persist_raw_artifacts(timestamp=timestamp, raw_activities=raw_activities, user_data=user_data)

    print("🧹 Preprocessing data...")
    processed_data = preprocess_data(raw_activities)
    if not processed_data:
        print("⚠️ No data left after preprocessing.")
        return None

    print("🤖 Analyzing data with AI Coach...")
    response = coach(data=processed_data, user_data=user_data, goal_path=str(GOAL_PROMPT_PATH))

    print("💾 Generating Markdown report...")
    report_path = _persist_pipeline_artifacts(
        timestamp=timestamp,
        processed_data=processed_data,
        response=response,
    )

    print("✨ Pipeline completed!")
    print(f"📄 Markdown Report: {report_path}")
    return str(report_path)
