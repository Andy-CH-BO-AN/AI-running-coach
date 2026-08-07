import argparse

from src.db.settings import get_database_mode
from src.pipeline.goal_prompt import build_goal_prompt_overrides
from src.pipeline.runner import run_pipeline


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Garmin sync and generate an AI training report.")
    parser.add_argument(
        "--activity-limit",
        type=int,
        default=75,
        help="How many recent activities the AI coach should analyze.",
    )
    parser.add_argument(
        "--fetch-limit",
        type=int,
        help="Maximum Garmin activities to fetch while syncing new data. Defaults to --activity-limit; use 999 for backfill.",
    )
    parser.add_argument(
        "--core-goal",
        help="Your race distance, race date, target result, and current training focus.",
    )
    parser.add_argument(
        "--core-goal-file",
        help="Read your race distance, target result, and training focus from a markdown/text file.",
    )
    parser.add_argument(
        "--training-preferences",
        help="Your weekly training frequency, rest days, cross-training, injuries, and scheduling limits.",
    )
    parser.add_argument(
        "--training-preferences-file",
        help="Read your weekly schedule, rest days, cross-training, and training limits from a markdown/text file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> str | None:
    args = parse_args(argv)
    if get_database_mode() == "cloud":
        raise SystemExit(
            "Cloud scheduled runs must use: python -m src.scripts.run_daily_pipeline"
        )

    goal_overrides = build_goal_prompt_overrides(
        core_goal=args.core_goal,
        core_goal_file=args.core_goal_file,
        training_preferences=args.training_preferences,
        training_preferences_file=args.training_preferences_file,
    )
    return run_pipeline(
        activity_limit=args.activity_limit,
        fetch_limit=args.fetch_limit,
        goal_overrides=goal_overrides,
    )


if __name__ == '__main__':
    main()
