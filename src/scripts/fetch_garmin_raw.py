from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from src.services.artifacts import (
    RAW_DATA_DIR,
    raw_artifact_paths,
    strength_backfill_artifact_paths,
    treadmill_backfill_artifact_paths,
    write_json,
)
from src.services.garmin_import_service import (
    import_fetched_raw_artifacts,
    import_strength_backfill,
    import_treadmill_backfill,
)
from src.services.training_calendar import resolve_training_calendar_date


def _build_timestamp() -> str:
    return resolve_training_calendar_date().strftime("%Y%m%d")


def _write_json(path: Path, payload: Any) -> None:
    write_json(path, payload)


def _get_garmin_activities(
    limit: int,
    progress: bool = True,
) -> dict[str, Any]:
    from src.ingestion.garmin_client import get_garmin_activities

    return get_garmin_activities(limit, progress=progress)


def _get_all_strength_training_activities(progress: bool = True) -> dict[str, Any]:
    from src.ingestion.garmin_client import get_all_strength_training_activities

    return get_all_strength_training_activities(progress=progress)


def _get_all_treadmill_running_activities(progress: bool = True) -> dict[str, Any]:
    from src.ingestion.garmin_client import get_all_treadmill_running_activities

    return get_all_treadmill_running_activities(progress=progress)


def fetch_garmin_raw_files(
    limit: int = 999,
    timestamp: str | None = None,
    output_dir: Path = RAW_DATA_DIR,
    activity_type: str | None = None,
    all_history: bool = False,
    force: bool = False,
) -> tuple[Path, Path]:
    stamp = timestamp or _build_timestamp()
    if all_history and activity_type == "strength_training":
        artifact_paths = strength_backfill_artifact_paths
    elif all_history and activity_type == "treadmill_running":
        artifact_paths = treadmill_backfill_artifact_paths
    else:
        artifact_paths = raw_artifact_paths
    user_path, raw_path = artifact_paths(stamp, output_dir=output_dir)
    existing_paths = [path for path in (user_path, raw_path) if path.exists()]
    if existing_paths and not force:
        names = ", ".join(str(path) for path in existing_paths)
        raise FileExistsError(f"Artifact already exists: {names}. Use --force to overwrite.")

    print(
        "Starting raw-only Garmin fetch. If Garmin prints two 429 login messages, "
        "wait 3-8 minutes before assuming it is stuck.",
        flush=True,
    )
    if all_history:
        if activity_type == "strength_training":
            garmin_data = _get_all_strength_training_activities(progress=True)
        elif activity_type == "treadmill_running":
            garmin_data = _get_all_treadmill_running_activities(progress=True)
        else:
            raise ValueError(
                "--all requires --activity-type strength_training or treadmill_running"
            )
    elif activity_type in {"strength_training", "treadmill_running"}:
        from src.ingestion.garmin_client import get_garmin_activities

        garmin_data = get_garmin_activities(
            limit,
            progress=True,
            activity_types={
                activity_type: (
                    "strength_training"
                    if activity_type == "strength_training"
                    else "running"
                )
            },
        )
    else:
        garmin_data = _get_garmin_activities(limit, progress=True)
    raw_activities = garmin_data.get("activities", [])
    user_data = garmin_data.get("user_data", {})

    if not raw_activities:
        raise RuntimeError("No Garmin activities found. Check credentials, Garmin login, or activity filters.")

    print(f"Writing {len(raw_activities)} activities to {raw_path}", flush=True)
    _write_json(raw_path, raw_activities)
    print(f"Writing Garmin user profile to {user_path}", flush=True)
    _write_json(user_path, user_data)
    return user_path, raw_path


def import_raw_files(
    user_path: Path | None,
    raw_path: Path,
    *,
    strength_backfill: bool = False,
    treadmill_backfill: bool = False,
) -> dict[str, Any]:
    print("Importing fetched raw files into PostgreSQL", flush=True)
    if strength_backfill:
        return import_strength_backfill(user_path=user_path, raw_path=raw_path)
    if treadmill_backfill:
        return import_treadmill_backfill(raw_path=raw_path)
    return import_fetched_raw_artifacts(user_path=user_path, raw_path=raw_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Garmin activities into local raw JSON files only.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--limit", type=int, help="Number of Garmin activities to fetch. Default: 999")
    selection.add_argument(
        "--all",
        action="store_true",
        help="Scan every page; supported for strength_training and treadmill_running.",
    )
    parser.add_argument(
        "--activity-type",
        choices=("strength_training", "treadmill_running"),
        help="Restrict fetching to a supported Garmin activity type.",
    )
    parser.add_argument("--timestamp", help="Optional YYYYMMDD timestamp for output filenames.")
    parser.add_argument("--output-dir", default=str(RAW_DATA_DIR), help="Directory for garmin_raw/user JSON files.")
    parser.add_argument("--force", action="store_true", help="Allow overwriting an existing artifact pair.")
    parser.add_argument("--import-db", action="store_true", help="Import the fetched raw files into PostgreSQL.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.all and args.activity_type not in {"strength_training", "treadmill_running"}:
        raise SystemExit(
            "--all requires --activity-type strength_training or treadmill_running"
        )
    user_path, raw_path = fetch_garmin_raw_files(
        limit=args.limit if args.limit is not None else 999,
        timestamp=args.timestamp,
        output_dir=Path(args.output_dir),
        activity_type=args.activity_type,
        all_history=args.all,
        force=args.force,
    )

    print(f"user_file: {user_path}")
    print(f"raw_file: {raw_path}")

    if args.import_db:
        results = import_raw_files(
            user_path=user_path,
            raw_path=raw_path,
            strength_backfill=args.all and args.activity_type == "strength_training",
            treadmill_backfill=args.all and args.activity_type == "treadmill_running",
        )
        for key, value in results.items():
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
