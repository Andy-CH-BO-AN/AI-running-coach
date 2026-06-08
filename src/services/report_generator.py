from pathlib import Path
from typing import Any, Dict, List

from src.agents.coach import coach
from src.pipeline.goal_prompt import GoalPromptOverrides, render_goal_prompt
from src.preprocessing.coach_context import enforce_deterministic_report_fields

DEFAULT_GOAL_PROMPT_PATH = Path("prompts/goal.md")


def generate_coach_report(
    processed_data: List[Dict[str, Any]],
    user_data: Dict[str, Any],
    deterministic_context: Dict[str, Any],
    goal_overrides: GoalPromptOverrides | None = None,
    goal_prompt_path: str | Path = DEFAULT_GOAL_PROMPT_PATH,
) -> Dict[str, Any]:
    goal_path = Path(goal_prompt_path)
    goal_text = render_goal_prompt(goal_path, goal_overrides)
    response = coach(
        data=processed_data,
        user_data=user_data,
        deterministic_context=deterministic_context,
        goal_path=str(goal_path),
        goal_text=goal_text,
    )
    return enforce_deterministic_report_fields(response, deterministic_context)
