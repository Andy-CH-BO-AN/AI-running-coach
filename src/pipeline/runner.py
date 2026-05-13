import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.agents.coach import coach
from src.db.models import Activity
from src.db.repositories import get_latest_user_profile, get_or_create_default_user, get_recent_activities
from src.db.repositories import get_recent_max_heart_rate
from src.db.session import SessionLocal
from src.ingestion.garmin_client import get_garmin_activities
from src.pipeline.goal_prompt import GoalPromptOverrides, render_goal_prompt
from src.preprocessing.data_processor import preprocess_data
from src.services.db_importer import import_garmin_raw_file, import_garmin_user_file

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


def _write_json_report(path: Path, response: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(response, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")


def _persist_pipeline_artifacts(
    timestamp: str,
    processed_data: List[Dict[str, Any]],
    response: Dict[str, Any],
) -> Path:
    _write_processed_csv(PROCESSED_DATA_DIR / f"processed_{timestamp}.csv", processed_data)

    report_path = OUTPUT_DIR / f"ai_report_{timestamp}.json"
    _write_json_report(report_path, response)
    return report_path


def _persist_raw_artifacts(
    timestamp: str,
    raw_activities: List[Dict[str, Any]],
    user_data: Dict[str, Any],
) -> tuple[Path, Path]:
    raw_path = RAW_DATA_DIR / f"garmin_raw_{timestamp}.json"
    user_path = RAW_DATA_DIR / f"garmin_user_{timestamp}.json"
    _write_json(raw_path, raw_activities)
    _write_json(user_path, user_data)
    return user_path, raw_path


def _get_latest_activity_date(session: Any, user_id: Any) -> Optional[date]:
    return session.scalar(
        select(func.max(Activity.activity_date)).where(Activity.user_id == user_id)
    )


def _load_recent_raw_activities(session: Any, user_id: Any, limit: int) -> List[Dict[str, Any]]:
    return [dict(activity.raw_json) for activity in get_recent_activities(session, user_id, limit=limit)]


def _load_latest_user_data(session: Any, user_id: Any) -> Dict[str, Any]:
    snapshot = get_latest_user_profile(session, user_id)
    return dict(snapshot.raw_profile) if snapshot else {}


def _fetch_garmin_updates(
    latest_date: Optional[date],
    fetch_limit: int,
    fallback_max_heart_rate: float | None = None,
) -> Dict[str, Any]:
    if latest_date:
        print(f"🗄️ Latest activity in DB: {latest_date.isoformat()}; fetching Garmin updates from that day.")
    else:
        print("🗄️ No activities in DB yet; fetching Garmin history.")

    return get_garmin_activities(
        fetch_limit,
        progress=True,
        since_date=latest_date,
        fallback_max_heart_rate=fallback_max_heart_rate,
    )


def _sync_garmin_to_db(
    session: Any,
    user_id: Any,
    timestamp: str,
    garmin_data: Dict[str, Any],
) -> Dict[str, Any]:
    raw_activities = garmin_data.get("activities", [])
    user_data = garmin_data.get("user_data", {})

    if not raw_activities and not user_data:
        print("⚠️ No Garmin payload returned for DB sync.")
        return {"activities": 0, "splits": 0, "swimming_lengths": 0, "user_snapshot": False}

    user_path, raw_path = _persist_raw_artifacts(
        timestamp=timestamp,
        raw_activities=raw_activities,
        user_data=user_data,
    )

    snapshot_saved = False
    if user_data:
        import_garmin_user_file(session, user_id, user_path)
        snapshot_saved = True

    counts = {"activities": 0, "splits": 0, "swimming_lengths": 0}
    if raw_activities:
        counts = import_garmin_raw_file(session, user_id, raw_path)

    session.commit()
    counts["user_snapshot"] = snapshot_saved
    print(
        "💾 DB sync completed: "
        f"{counts['activities']} activities, {counts['splits']} splits, "
        f"{counts['swimming_lengths']} swimming lengths."
    )
    return counts


def _fetch_without_db(activity_limit: int, timestamp: str) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    print("⚠️ DB unavailable; falling back to direct Garmin fetch for structured JSON output.")
    garmin_data = get_garmin_activities(activity_limit, progress=True)
    raw_activities = garmin_data.get("activities", [])
    user_data = garmin_data.get("user_data", {})
    if raw_activities or user_data:
        _persist_raw_artifacts(timestamp=timestamp, raw_activities=raw_activities, user_data=user_data)
    return raw_activities, user_data


def _load_existing_db_payloads(activity_limit: int) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    with SessionLocal() as session:
        user = get_or_create_default_user(session)
        raw_activities = _load_recent_raw_activities(session, user.id, limit=activity_limit)
        user_data = _load_latest_user_data(session, user.id)
        return raw_activities, user_data


def _load_or_fetch_activity_payloads(
    activity_limit: int,
    fetch_limit: int,
    timestamp: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetched_raw_activities: List[Dict[str, Any]] = []
    fetched_user_data: Dict[str, Any] = {}
    try:
        with SessionLocal() as session:
            user = get_or_create_default_user(session)
            latest_date = _get_latest_activity_date(session, user.id)
            fallback_max_heart_rate = get_recent_max_heart_rate(session, user.id)
            garmin_data = _fetch_garmin_updates(
                latest_date=latest_date,
                fetch_limit=fetch_limit,
                fallback_max_heart_rate=fallback_max_heart_rate,
            )
            fetched_raw_activities = garmin_data.get("activities", [])
            fetched_user_data = garmin_data.get("user_data", {})
            _sync_garmin_to_db(
                session=session,
                user_id=user.id,
                timestamp=timestamp,
                garmin_data=garmin_data,
            )
            raw_activities = _load_recent_raw_activities(session, user.id, limit=activity_limit)
            user_data = _load_latest_user_data(session, user.id)
            print(f"📚 Loaded {len(raw_activities)} recent activities from DB for AI Coach.")
            return raw_activities, user_data
    except SQLAlchemyError as exc:
        print(f"⚠️ Database sync failed: {type(exc).__name__}")
        if fetched_raw_activities or fetched_user_data:
            try:
                raw_activities, user_data = _load_existing_db_payloads(activity_limit)
                if raw_activities:
                    print(f"📚 Loaded {len(raw_activities)} existing DB activities after sync failure.")
                    return raw_activities, user_data
            except SQLAlchemyError as read_exc:
                print(f"⚠️ Existing DB read failed: {type(read_exc).__name__}")
            print("⚠️ Using already-fetched Garmin payload for structured JSON output; not calling Garmin again.")
            return fetched_raw_activities, fetched_user_data
        return _fetch_without_db(activity_limit=activity_limit, timestamp=timestamp)


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

    print("🤖 Analyzing data with AI Coach...")
    goal_text = render_goal_prompt(GOAL_PROMPT_PATH, goal_overrides)
    response = coach(
        data=processed_data,
        user_data=user_data,
        goal_path=str(GOAL_PROMPT_PATH),
        goal_text=goal_text,
    )

    print("💾 Generating structured JSON report...")
    report_path = _persist_pipeline_artifacts(
        timestamp=timestamp,
        processed_data=processed_data,
        response=response,
    )

    print("✨ Pipeline completed!")
    print(f"📄 JSON Report: {report_path}")
    return str(report_path)
