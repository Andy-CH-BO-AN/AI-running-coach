from __future__ import annotations

import argparse
import glob
from pathlib import Path

from src.db.mirror import sync_shadow_database, validate_shadow_parity
from src.db.repositories import get_or_create_default_user
from src.db.session import SessionLocal
from src.services.db_importer import import_artifact_bundle


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
        user_files = []
        if args.user_file:
            user_files.append(Path(args.user_file))
        if args.user_glob:
            user_files.extend(Path(path) for path in sorted(glob.glob(args.user_glob)))
        if args.user_glob and not user_files:
            raise SystemExit(f"No files matched --user-glob: {args.user_glob}")
        results = import_artifact_bundle(
            session,
            user.id,
            user_files=user_files or None,
            raw_file=args.raw_file,
            processed_file=args.processed_file,
        )

        session.commit()

    shadow_import = sync_shadow_database()
    if shadow_import is not None:
        results["shadow_import"] = shadow_import
        results["shadow_parity"] = validate_shadow_parity()

    for key, value in results.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
