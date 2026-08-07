from __future__ import annotations

import argparse
import sys

from src.pipeline.daily_run import DailyRunBlocked, execute_daily_run
from src.pipeline.goal_prompt import build_goal_prompt_overrides


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the cloud-scheduled AI Running Coach Daily Run.",
    )
    parser.add_argument(
        "--core-goal",
        help="Your race distance, race date, target result, and current training focus.",
    )
    parser.add_argument(
        "--core-goal-file",
        help="Read the core goal from a markdown/text file.",
    )
    parser.add_argument(
        "--training-preferences",
        help="Your weekly schedule, cross-training, injuries, and training limits.",
    )
    parser.add_argument(
        "--training-preferences-file",
        help="Read training preferences from a markdown/text file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    goal_overrides = build_goal_prompt_overrides(
        core_goal=args.core_goal,
        core_goal_file=args.core_goal_file,
        training_preferences=args.training_preferences,
        training_preferences_file=args.training_preferences_file,
    )
    try:
        result = execute_daily_run(goal_overrides=goal_overrides)
    except DailyRunBlocked as exc:
        print(
            f"Daily Run blocked ({exc.reason.value}): {exc.safe_message}",
            file=sys.stderr,
        )
        return 1

    report_path = str(result.report_path) if result.report_path is not None else "none"
    notification_status = (
        result.notification.status if result.notification is not None else "not_run"
    )
    print(
        f"Daily Run result: mode={result.mode.value}, "
        f"report={report_path}, notification={notification_status}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
