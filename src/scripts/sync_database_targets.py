from __future__ import annotations

import argparse
import json

from src.db.sync import compare_database_targets, sync_database_targets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync PostgreSQL data between local and cloud targets.")
    parser.add_argument("--source", choices=("local", "cloud"), default="local", help="Source database target.")
    parser.add_argument("--target", choices=("local", "cloud"), default="cloud", help="Target database target.")
    parser.add_argument("--batch-size", type=int, default=500, help="Upsert batch size. Default: 500")
    parser.add_argument("--validate-only", action="store_true", help="Skip sync and only compare source/target parity.")
    parser.add_argument("--skip-validate", action="store_true", help="Skip parity validation after sync.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.source == args.target:
        raise SystemExit("--source and --target must be different.")

    if not args.validate_only:
        sync_result = sync_database_targets(
            source_target=args.source,
            target_target=args.target,
            batch_size=args.batch_size,
        )
        print(json.dumps(sync_result, ensure_ascii=False, indent=2))

    if args.skip_validate:
        return 0

    parity = compare_database_targets(args.source, args.target)
    print(json.dumps(parity, ensure_ascii=False, indent=2))
    return 0 if parity["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
