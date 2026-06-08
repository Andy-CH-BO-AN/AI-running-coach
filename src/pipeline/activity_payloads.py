from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.db.models import Activity
from src.db.repositories import (
    get_latest_resting_heart_rate,
    get_latest_user_profile,
    get_or_create_default_user,
    get_recent_activities,
    get_recent_max_heart_rate,
)
from src.db.session import SessionLocal
from src.ingestion.garmin_client import get_garmin_activities
from src.services.artifacts import persist_raw_artifacts
from src.services.garmin_import_service import import_fetched_garmin_payload


class ActivityPayloadProvider:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        garmin_fetcher: Callable[..., Dict[str, Any]] = get_garmin_activities,
        raw_artifact_persister: Callable[..., tuple[Path, Path]] = persist_raw_artifacts,
        import_service: Callable[..., Dict[str, Any]] = import_fetched_garmin_payload,
        raw_data_dir: Path = Path("data/raw"),
    ) -> None:
        self.session_factory = session_factory
        self.garmin_fetcher = garmin_fetcher
        self.raw_artifact_persister = raw_artifact_persister
        self.import_service = import_service
        self.raw_data_dir = raw_data_dir

    def _persist_raw_artifacts(
        self,
        *,
        timestamp: str,
        raw_activities: List[Dict[str, Any]],
        user_data: Dict[str, Any],
    ) -> tuple[Path, Path]:
        return self.raw_artifact_persister(
            timestamp=timestamp,
            raw_activities=raw_activities,
            user_data=user_data,
            output_dir=self.raw_data_dir,
        )

    def _get_latest_activity_date(self, session: Any, user_id: Any) -> Optional[date]:
        return session.scalar(
            select(func.max(Activity.activity_date)).where(Activity.user_id == user_id)
        )

    def _load_recent_raw_activities(self, session: Any, user_id: Any, limit: int) -> List[Dict[str, Any]]:
        return [
            dict(activity.raw_json)
            for activity in get_recent_activities(session, user_id, limit=limit)
        ]

    def _load_latest_user_data(self, session: Any, user_id: Any) -> Dict[str, Any]:
        snapshot = get_latest_user_profile(session, user_id)
        return self._apply_resting_heart_rate_history(
            session=session,
            user_id=user_id,
            user_data=dict(snapshot.raw_profile) if snapshot else {},
        )

    def _apply_resting_heart_rate_history(
        self,
        session: Any,
        user_id: Any,
        user_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        user_data = dict(user_data or {})
        latest_resting_hr = get_latest_resting_heart_rate(session, user_id)
        current_resting_hr = user_data.get("resting_heart_rate")
        try:
            current_resting_hr = (
                float(current_resting_hr)
                if current_resting_hr not in (None, "")
                else None
            )
        except (TypeError, ValueError):
            current_resting_hr = None

        if latest_resting_hr is None:
            return user_data

        resolved_resting_hr = (
            latest_resting_hr
            if current_resting_hr is None
            else min(current_resting_hr, latest_resting_hr)
        )
        if current_resting_hr != resolved_resting_hr:
            user_data["resting_heart_rate"] = resolved_resting_hr
            user_data["resting_heart_rate_source"] = "db_latest_profile_history"
        return user_data

    def _fetch_garmin_updates(
        self,
        latest_date: Optional[date],
        fetch_limit: int,
        fallback_max_heart_rate: float | None = None,
    ) -> Dict[str, Any]:
        if latest_date:
            print(
                f"🗄️ Latest activity in DB: {latest_date.isoformat()}; "
                "fetching Garmin updates from that day."
            )
        else:
            print("🗄️ No activities in DB yet; fetching Garmin history.")

        return self.garmin_fetcher(
            fetch_limit,
            progress=True,
            since_date=latest_date,
            fallback_max_heart_rate=fallback_max_heart_rate,
        )

    def _sync_garmin_to_db(
        self,
        session: Any,
        user_id: Any,
        timestamp: str,
        garmin_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw_activities = garmin_data.get("activities", [])
        user_data = garmin_data.get("user_data", {})

        if not raw_activities and not user_data:
            print("⚠️ No Garmin payload returned for DB sync.")
            return {
                "activities": 0,
                "splits": 0,
                "swimming_lengths": 0,
                "user_snapshot": False,
            }

        user_path, raw_path = self._persist_raw_artifacts(
            timestamp=timestamp,
            raw_activities=raw_activities,
            user_data=user_data,
        )

        counts = self.import_service(
            session=session,
            user_id=user_id,
            user_path=user_path if user_data else None,
            raw_path=raw_path if raw_activities else None,
        )
        print(
            "💾 DB sync completed: "
            f"{counts['activities']} activities, {counts['splits']} splits, "
            f"{counts['swimming_lengths']} swimming lengths."
        )

        parity = counts.get("shadow_parity")
        if counts.get("shadow_import") is not None:
            if parity and parity["ok"]:
                print("☁️ Shadow DB parity check passed.", flush=True)
            elif parity:
                print(
                    f"⚠️ Shadow DB parity mismatch: {len(parity['mismatches'])} table(s).",
                    flush=True,
                )

        return counts

    def _fetch_without_db(
        self,
        activity_limit: int,
        timestamp: str,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        print("⚠️ DB unavailable; falling back to direct Garmin fetch for structured JSON output.")
        garmin_data = self.garmin_fetcher(activity_limit, progress=True)
        raw_activities = garmin_data.get("activities", [])
        user_data = garmin_data.get("user_data", {})
        if raw_activities or user_data:
            self._persist_raw_artifacts(
                timestamp=timestamp,
                raw_activities=raw_activities,
                user_data=user_data,
            )
        return raw_activities, user_data

    def _load_existing_db_payloads(
        self,
        activity_limit: int,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        with self.session_factory() as session:
            user = get_or_create_default_user(session)
            raw_activities = self._load_recent_raw_activities(session, user.id, limit=activity_limit)
            user_data = self._load_latest_user_data(session, user.id)
            return raw_activities, user_data

    def load_or_fetch(
        self,
        activity_limit: int,
        fetch_limit: int,
        timestamp: str,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        fetched_raw_activities: List[Dict[str, Any]] = []
        fetched_user_data: Dict[str, Any] = {}
        try:
            with self.session_factory() as session:
                user = get_or_create_default_user(session)
                latest_date = self._get_latest_activity_date(session, user.id)
                fallback_max_heart_rate = get_recent_max_heart_rate(session, user.id)
                garmin_data = self._fetch_garmin_updates(
                    latest_date=latest_date,
                    fetch_limit=fetch_limit,
                    fallback_max_heart_rate=fallback_max_heart_rate,
                )
                fetched_raw_activities = garmin_data.get("activities", [])
                fetched_user_data = garmin_data.get("user_data", {})
                self._sync_garmin_to_db(
                    session=session,
                    user_id=user.id,
                    timestamp=timestamp,
                    garmin_data=garmin_data,
                )
                raw_activities = self._load_recent_raw_activities(session, user.id, limit=activity_limit)
                user_data = self._load_latest_user_data(session, user.id)
                print(f"📚 Loaded {len(raw_activities)} recent activities from DB for AI Coach.")
                return raw_activities, user_data
        except SQLAlchemyError as exc:
            print(f"⚠️ Database sync failed: {type(exc).__name__}")
            if fetched_raw_activities or fetched_user_data:
                try:
                    raw_activities, user_data = self._load_existing_db_payloads(activity_limit)
                    if raw_activities:
                        print(
                            f"📚 Loaded {len(raw_activities)} existing DB activities "
                            "after sync failure."
                        )
                        return raw_activities, user_data
                except SQLAlchemyError as read_exc:
                    print(f"⚠️ Existing DB read failed: {type(read_exc).__name__}")
                print(
                    "⚠️ Using already-fetched Garmin payload for structured JSON output; "
                    "not calling Garmin again."
                )
                return fetched_raw_activities, fetched_user_data
            return self._fetch_without_db(activity_limit=activity_limit, timestamp=timestamp)
