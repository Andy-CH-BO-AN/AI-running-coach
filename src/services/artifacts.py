from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

RAW_DATA_DIR = Path("data/raw")
PROCESSED_DATA_DIR = Path("data/processed")
OUTPUT_DIR = Path("output")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=4)


def write_processed_csv(path: Path, processed_data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.json_normalize(processed_data).to_csv(path, index=False, encoding="utf-8-sig")


def write_json_report(path: Path, response: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(response, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")


def raw_artifact_paths(timestamp: str, output_dir: Path = RAW_DATA_DIR) -> tuple[Path, Path]:
    raw_path = output_dir / f"garmin_raw_{timestamp}.json"
    user_path = output_dir / f"garmin_user_{timestamp}.json"
    return user_path, raw_path


def persist_raw_artifacts(
    timestamp: str,
    raw_activities: list[dict[str, Any]],
    user_data: dict[str, Any],
    output_dir: Path = RAW_DATA_DIR,
) -> tuple[Path, Path]:
    user_path, raw_path = raw_artifact_paths(timestamp, output_dir=output_dir)
    write_json(raw_path, raw_activities)
    write_json(user_path, user_data)
    return user_path, raw_path


def persist_pipeline_artifacts(
    timestamp: str,
    processed_data: list[dict[str, Any]],
    deterministic_context: dict[str, Any],
    response: dict[str, Any],
    *,
    processed_dir: Path = PROCESSED_DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> Path:
    write_processed_csv(processed_dir / f"processed_{timestamp}.csv", processed_data)
    write_json(processed_dir / f"coach_context_{timestamp}.json", deterministic_context)

    report_path = output_dir / f"ai_report_{timestamp}.json"
    write_json_report(report_path, response)
    return report_path
