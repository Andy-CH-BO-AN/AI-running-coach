from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.pipeline.goal_prompt import GoalPromptOverrides
from src.preprocessing.coach_context import build_deterministic_coach_context
from src.preprocessing.data_processor import preprocess_data
from src.services.artifacts import (
    OUTPUT_DIR,
    PROCESSED_DATA_DIR,
    persist_pipeline_artifacts,
    pipeline_artifact_paths,
    refuse_existing_report,
)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def _load_raw_activities(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"raw_file must contain a JSON list: {path}")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"raw_file must contain a list of JSON objects: {path}")
    return payload


def _load_user_data(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"user_file must contain a JSON object: {path}")
    return payload


def generate_coach_report(
    *,
    processed_data: list[dict[str, Any]],
    user_data: dict[str, Any],
    deterministic_context: dict[str, Any],
    goal_overrides: GoalPromptOverrides | None = None,
) -> dict[str, Any]:
    from src.services.report_generator import generate_coach_report as generate_report

    return generate_report(
        processed_data=processed_data,
        user_data=user_data,
        deterministic_context=deterministic_context,
        goal_overrides=goal_overrides,
    )


def generate_local_report_from_artifacts(
    *,
    raw_file: str | Path,
    user_file: str | Path,
    report_date: str,
    activity_limit: int = 75,
    force: bool = False,
    goal_overrides: GoalPromptOverrides | None = None,
    processed_dir: Path = PROCESSED_DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> str:
    if activity_limit < 0:
        raise ValueError("activity_limit must be greater than or equal to 0.")

    artifact_paths = pipeline_artifact_paths(
        report_date,
        processed_dir=processed_dir,
        output_dir=output_dir,
    )
    refuse_existing_report(artifact_paths["report"], force=force)

    raw_activities = _load_raw_activities(Path(raw_file))
    user_data = _load_user_data(Path(user_file))
    limited_raw_activities = raw_activities[:activity_limit]

    processed_data = preprocess_data(limited_raw_activities)
    if not processed_data:
        raise ValueError("No data left after preprocessing.")

    deterministic_context = build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=user_data,
        raw_activities=limited_raw_activities,
        today=report_date,
    )
    response = generate_coach_report(
        processed_data=processed_data,
        user_data=user_data,
        deterministic_context=deterministic_context,
        goal_overrides=goal_overrides,
    )
    report_path = persist_pipeline_artifacts(
        timestamp=report_date,
        processed_data=processed_data,
        deterministic_context=deterministic_context,
        response=response,
        processed_dir=processed_dir,
        output_dir=output_dir,
    )
    return str(report_path)
