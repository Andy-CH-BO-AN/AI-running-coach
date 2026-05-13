from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoalPromptOverrides:
    core_goal: str | None = None
    training_preferences: str | None = None


SECTION_HEADINGS = {
    "core_goal": "## 🎯 核心目標",
    "training_preferences": "## ⚙️ 訓練偏好與限制",
}


def _read_optional_text(text: str | None, file_path: str | None) -> str | None:
    if text and file_path:
        raise ValueError("Use either inline text or a file path for the same goal section, not both.")
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    return text.strip() if text else None


def build_goal_prompt_overrides(
    *,
    core_goal: str | None = None,
    core_goal_file: str | None = None,
    training_preferences: str | None = None,
    training_preferences_file: str | None = None,
) -> GoalPromptOverrides:
    return GoalPromptOverrides(
        core_goal=_read_optional_text(core_goal, core_goal_file),
        training_preferences=_read_optional_text(training_preferences, training_preferences_file),
    )


def _format_section_body(body: str) -> str:
    lines = body.strip().splitlines()
    if not lines:
        return ""
    return "\n".join(line if line.startswith(("*", "-", "1.", "#")) else f"* {line}" for line in lines)


def _replace_section(markdown: str, heading: str, body: str) -> str:
    replacement = f"{heading}\n{_format_section_body(body)}"
    pattern = re.compile(
        rf"^{re.escape(heading)}\n.*?(?=^## |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    updated, count = pattern.subn(replacement.rstrip() + "\n\n", markdown, count=1)
    if count:
        return updated.rstrip() + "\n"
    return markdown.rstrip() + f"\n\n{replacement}\n"


def render_goal_prompt(
    goal_path: str | Path,
    overrides: GoalPromptOverrides | None = None,
) -> str | None:
    overrides = overrides or GoalPromptOverrides()
    if not overrides.core_goal and not overrides.training_preferences:
        return None

    markdown = Path(goal_path).read_text(encoding="utf-8")
    if overrides.core_goal:
        markdown = _replace_section(markdown, SECTION_HEADINGS["core_goal"], overrides.core_goal)
    if overrides.training_preferences:
        markdown = _replace_section(
            markdown,
            SECTION_HEADINGS["training_preferences"],
            overrides.training_preferences,
        )
    return markdown
