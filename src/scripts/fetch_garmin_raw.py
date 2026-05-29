from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.db.mirror import sync_shadow_database, validate_shadow_parity
from src.db.repositories import get_or_create_default_user
from src.db.session import SessionLocal
from src.services.db_importer import import_artifact_bundle

RAW_DATA_DIR = Path("data/raw")


def _build_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=4)


def _get_garmin_activities(
    limit: int,
    progress: bool = True,
) -> dict[str, Any]:
    from src.ingestion.garmin_client import get_garmin_activities

    return get_garmin_activities(limit, progress=progress)


def fetch_garmin_raw_files(
    limit: int = 999,
    timestamp: str | None = None,
    output_dir: Path = RAW_DATA_DIR,
) -> tuple[Path, Path]:
    print(
        "Starting raw-only Garmin fetch. If Garmin prints two 429 login messages, "
        "wait 3-8 minutes before assuming it is stuck.",
        flush=True,
    )
    garmin_data = _get_garmin_activities(limit, progress=True)
    raw_activities = garmin_data.get("activities", [])
    user_data = garmin_data.get("user_data", {})

    if not raw_activities:
        raise RuntimeError("No Garmin activities found. Check credentials, Garmin login, or activity filters.")

    stamp = timestamp or _build_timestamp()
    raw_path = output_dir / f"garmin_raw_{stamp}.json"
    user_path = output_dir / f"garmin_user_{stamp}.json"

    print(f"Writing {len(raw_activities)} activities to {raw_path}", flush=True)
    _write_json(raw_path, raw_activities)
    print(f"Writing Garmin user profile to {user_path}", flush=True)
    _write_json(user_path, user_data)
    return user_path, raw_path


def import_raw_files(user_path: Path, raw_path: Path) -> dict[str, Any]:
    print("Importing fetched raw files into PostgreSQL", flush=True)
    with SessionLocal() as session:
        user = get_or_create_default_user(session)
        results = import_artifact_bundle(
            session,
            user.id,
            user_files=[user_path],
            raw_file=raw_path,
        )
        session.commit()

    shadow_import = sync_shadow_database()
    if shadow_import is not None:
        results["shadow_import"] = shadow_import
        results["shadow_parity"] = validate_shadow_parity()

    user_snapshot_ids = results.pop("user_snapshot_ids", [])
    if user_snapshot_ids:
        results["user_snapshot_id"] = user_snapshot_ids[0]
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Garmin activities into local raw JSON files only.")
    parser.add_argument("--limit", type=int, default=999, help="Number of Garmin activities to fetch. Default: 999")
    parser.add_argument("--timestamp", help="Optional YYYYMMDD timestamp for output filenames.")
    parser.add_argument("--output-dir", default=str(RAW_DATA_DIR), help="Directory for garmin_raw/user JSON files.")
    parser.add_argument("--import-db", action="store_true", help="Import the fetched raw files into PostgreSQL.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    user_path, raw_path = fetch_garmin_raw_files(
        limit=args.limit,
        timestamp=args.timestamp,
        output_dir=Path(args.output_dir),
    )

    print(f"user_file: {user_path}")
    print(f"raw_file: {raw_path}")

    if args.import_db:
        results = import_raw_files(user_path=user_path, raw_path=raw_path)
        for key, value in results.items():
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
