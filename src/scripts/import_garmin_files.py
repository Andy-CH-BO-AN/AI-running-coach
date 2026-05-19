from __future__ import annotations

import argparse
import glob
from pathlib import Path

from src.db.repositories import get_or_create_default_user
from src.db.session import SessionLocal
from src.services.db_importer import (
    import_garmin_raw_file,
    import_garmin_user_file,
    import_processed_csv_file,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import local Garmin artifacts into PostgreSQL.")
    parser.add_argument("--user-file", help="Path to data/raw/garmin_user_YYYYMMDD.json")
    parser.add_argument("--user-glob", help="Glob for multiple Garmin user files, e.g. data/raw/garmin_user_2026051*.json")
    parser.add_argument("--raw-file", help="Path to data/raw/garmin_raw_YYYYMMDD.json")
    parser.add_argument("--processed-file", help="Optional path to data/processed/processed_YYYYMMDD.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.user_file and not args.user_glob and not args.raw_file and not args.processed_file:
        raise SystemExit("Provide at least one of --user-file, --user-glob, --raw-file, or --processed-file.")

    with SessionLocal() as session:
        user = get_or_create_default_user(session)
        results = {}

        user_files = []
        if args.user_file:
            user_files.append(Path(args.user_file))
        if args.user_glob:
            user_files.extend(Path(path) for path in sorted(glob.glob(args.user_glob)))
        if args.user_glob and not user_files:
            raise SystemExit(f"No files matched --user-glob: {args.user_glob}")
        if user_files:
            snapshot_ids = []
            for user_file in user_files:
                snapshot = import_garmin_user_file(session, user.id, user_file)
                snapshot_ids.append(str(snapshot.id))
            results["user_snapshot_ids"] = snapshot_ids
        if args.raw_file:
            results["raw_import"] = import_garmin_raw_file(session, user.id, args.raw_file)
        if args.processed_file:
            results["processed_import"] = import_processed_csv_file(session, user.id, args.processed_file)

        session.commit()

    for key, value in results.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
