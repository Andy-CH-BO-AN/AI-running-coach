from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.db.mirror import sync_shadow_database, validate_shadow_parity
from src.db.models import Activity
from src.db.repositories import get_latest_resting_heart_rate, get_latest_user_profile, get_or_create_default_user, get_recent_activities
from src.db.repositories import get_recent_max_heart_rate
from src.db.session import SessionLocal
from src.ingestion.garmin_client import get_garmin_activities
from src.pipeline.goal_prompt import GoalPromptOverrides
from src.preprocessing.coach_context import build_deterministic_coach_context
from src.preprocessing.data_processor import preprocess_data
from src.services.artifacts import (
    persist_pipeline_artifacts,
    persist_raw_artifacts,
    write_json,
    write_json_report,
    write_processed_csv,
)
from src.services.db_importer import import_artifact_bundle
from src.services.report_generator import generate_coach_report

RAW_DATA_DIR = Path("data/raw")
PROCESSED_DATA_DIR = Path("data/processed")
OUTPUT_DIR = Path("output")
GOAL_PROMPT_PATH = Path("prompts/goal.md")


def _build_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def _write_json(path: Path, payload: Any) -> None:
    write_json(path, payload)


def _write_processed_csv(path: Path, processed_data: List[Dict[str, Any]]) -> None:
    write_processed_csv(path, processed_data)


def _write_json_report(path: Path, response: Dict[str, Any]) -> None:
    write_json_report(path, response)


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


def _persist_raw_artifacts(
    timestamp: str,
    raw_activities: List[Dict[str, Any]],
    user_data: Dict[str, Any],
) -> tuple[Path, Path]:
    return persist_raw_artifacts(
        timestamp=timestamp,
        raw_activities=raw_activities,
        user_data=user_data,
        output_dir=RAW_DATA_DIR,
    )


def _get_latest_activity_date(session: Any, user_id: Any) -> Optional[date]:
    return session.scalar(
        select(func.max(Activity.activity_date)).where(Activity.user_id == user_id)
    )


def _load_recent_raw_activities(session: Any, user_id: Any, limit: int) -> List[Dict[str, Any]]:
    return [dict(activity.raw_json) for activity in get_recent_activities(session, user_id, limit=limit)]


def _load_latest_user_data(session: Any, user_id: Any) -> Dict[str, Any]:
    snapshot = get_latest_user_profile(session, user_id)
    return _apply_resting_heart_rate_history(
        session=session,
        user_id=user_id,
        user_data=dict(snapshot.raw_profile) if snapshot else {},
    )


def _apply_resting_heart_rate_history(
    session: Any,
    user_id: Any,
    user_data: Dict[str, Any],
) -> Dict[str, Any]:
    user_data = dict(user_data or {})
    latest_resting_hr = get_latest_resting_heart_rate(session, user_id)
    current_resting_hr = user_data.get("resting_heart_rate")
    try:
        current_resting_hr = float(current_resting_hr) if current_resting_hr not in (None, "") else None
    except (TypeError, ValueError):
        current_resting_hr = None

    if latest_resting_hr is None:
        return user_data

    resolved_resting_hr = latest_resting_hr if current_resting_hr is None else min(current_resting_hr, latest_resting_hr)
    if current_resting_hr != resolved_resting_hr:
        user_data["resting_heart_rate"] = resolved_resting_hr
        user_data["resting_heart_rate_source"] = "db_latest_profile_history"
    return user_data


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
    import_results = import_artifact_bundle(
        session,
        user_id,
        user_files=[user_path] if user_data else None,
        raw_file=raw_path if raw_activities else None,
    )
    snapshot_saved = bool(import_results.get("user_snapshot_ids"))
    counts = dict(import_results.get("raw_import") or {"activities": 0, "splits": 0, "swimming_lengths": 0})

    session.commit()
    counts["user_snapshot"] = snapshot_saved
    print(
        "💾 DB sync completed: "
        f"{counts['activities']} activities, {counts['splits']} splits, "
        f"{counts['swimming_lengths']} swimming lengths."
    )

    shadow_import = sync_shadow_database()
    if shadow_import is not None:
        counts["shadow_import"] = shadow_import
        parity = validate_shadow_parity()
        counts["shadow_parity"] = parity
        if parity and parity["ok"]:
            print("☁️ Shadow DB parity check passed.", flush=True)
        elif parity:
            print(f"⚠️ Shadow DB parity mismatch: {len(parity['mismatches'])} table(s).", flush=True)

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


def _build_pipeline_context(
    processed_data: List[Dict[str, Any]],
    user_data: Dict[str, Any],
    raw_activities: List[Dict[str, Any]],
    timestamp: str,
) -> Dict[str, Any]:
    return build_deterministic_coach_context(
        processed_data=processed_data,
        user_data=user_data,
        raw_activities=raw_activities,
        today=timestamp,
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
    deterministic_context = _build_pipeline_context(
        processed_data=processed_data,
        user_data=user_data,
        raw_activities=raw_activities,
        timestamp=timestamp,
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
