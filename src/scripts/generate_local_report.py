from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from src.services.local_report_service import generate_local_report_from_artifacts


def _report_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise argparse.ArgumentTypeError("report_date must be exactly YYYYMMDD.")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("report_date must be a valid YYYYMMDD date.") from exc
    return value


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("activity_limit must be an integer.") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("activity_limit must be greater than or equal to 0.")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an AI coach report from existing local Garmin JSON artifacts.",
    )
    parser.add_argument("--raw-file", required=True, help="Path to garmin_raw_YYYYMMDD.json.")
    parser.add_argument("--user-file", required=True, help="Path to garmin_user_YYYYMMDD.json.")
    parser.add_argument("--report-date", required=True, type=_report_date, help="Report date as YYYYMMDD.")
    parser.add_argument(
        "--activity-limit",
        type=_non_negative_int,
        default=75,
        help="Number of raw activities to use. Default: 75",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing ai_report_YYYYMMDD.json.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> str:
    args = parse_args(argv)
    try:
        report_path = generate_local_report_from_artifacts(
            raw_file=Path(args.raw_file),
            user_file=Path(args.user_file),
            report_date=args.report_date,
            activity_limit=args.activity_limit,
            force=args.force,
        )
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(f"JSON Report: {report_path}")
    return report_path


if __name__ == "__main__":
    main()
