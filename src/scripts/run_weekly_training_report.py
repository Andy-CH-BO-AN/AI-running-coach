from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy.exc import SQLAlchemyError

from src.pipeline.weekly_report import execute_weekly_training_report
from src.pipeline.goal_prompt import build_goal_prompt_overrides


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the persisted previous-complete-week training report.",
    )
    parser.add_argument(
        "--as-of",
        help="Override today's date (YYYY-MM-DD), primarily for a deliberate backfill.",
    )
    parser.add_argument(
        "--retry-only",
        action="store_true",
        help="Retry persisted weekly LINE payloads without generating a report.",
    )
    parser.add_argument(
        "--core-goal",
        help="Your race distance, race date, target result, and current training focus.",
    )
    parser.add_argument(
        "--training-preferences",
        help="Your weekly schedule, cross-training, injuries, and training limits.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    goal_overrides = build_goal_prompt_overrides(
        core_goal=args.core_goal,
        training_preferences=args.training_preferences,
    )
    try:
        today = date.fromisoformat(args.as_of) if args.as_of else None
        result = execute_weekly_training_report(
            today=today,
            retry_only=args.retry_only,
            goal_overrides=goal_overrides,
        )
    except (ValueError, RuntimeError, SQLAlchemyError) as exc:
        print(f"Weekly report blocked: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        f"Weekly report result: status={result.status}, "
        f"sent={result.sent}, failed={result.failed}."
    )
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
