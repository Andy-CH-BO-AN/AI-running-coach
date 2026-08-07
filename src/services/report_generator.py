from pathlib import Path
from typing import Any, Dict, List, Optional

from src.pipeline.goal_prompt import GoalPromptOverrides, render_goal_prompt
from src.preprocessing.coach_context import enforce_deterministic_report_fields

DEFAULT_GOAL_PROMPT_PATH = Path("prompts/goal.md")


def coach(
    data: List[Dict[str, Any]],
    user_data: Optional[Dict[str, Any]] = None,
    deterministic_context: Optional[Dict[str, Any]] = None,
    goal_path: str = "",
    goal_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Load the Gemini-backed coach only when report generation actually runs."""
    from src.agents.coach import coach as generate_with_coach

    return generate_with_coach(
        data=data,
        user_data=user_data,
        deterministic_context=deterministic_context,
        goal_path=goal_path,
        goal_text=goal_text,
    )


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
