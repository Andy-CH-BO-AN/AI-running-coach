import tempfile
import unittest
from pathlib import Path

from src.pipeline.goal_prompt import build_goal_prompt_overrides, render_goal_prompt


class GoalPromptTests(unittest.TestCase):
    def test_render_goal_prompt_returns_none_without_overrides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            goal_path = Path(temp_dir) / "goal.md"
            goal_path.write_text("default goal", encoding="utf-8")

            self.assertIsNone(render_goal_prompt(goal_path))

    def test_render_goal_prompt_replaces_only_requested_sections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            goal_path = Path(temp_dir) / "goal.md"
            goal_path.write_text(
                "# Training Goal\n\n"
                "## 🎯 核心目標\n"
                "* old race\n\n"
                "## ⚙️ 訓練偏好與限制\n"
                "* keep this\n",
                encoding="utf-8",
            )
            overrides = build_goal_prompt_overrides(core_goal="賽事名稱：測試賽\n目標成績：10K 45:00")

            rendered = render_goal_prompt(goal_path, overrides)

        self.assertIn("* 賽事名稱：測試賽", rendered)
        self.assertIn("* 目標成績：10K 45:00", rendered)
        self.assertNotIn("* old race", rendered)
        self.assertIn("* keep this", rendered)

    def test_build_goal_prompt_overrides_can_read_section_from_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            core_goal_path = Path(temp_dir) / "core.md"
            core_goal_path.write_text("* 賽事日期：2026-10-01\n", encoding="utf-8")

            overrides = build_goal_prompt_overrides(core_goal_file=str(core_goal_path))

        self.assertEqual(overrides.core_goal, "* 賽事日期：2026-10-01")

    def test_build_goal_prompt_overrides_rejects_text_and_file_for_same_section(self):
        with self.assertRaises(ValueError):
            build_goal_prompt_overrides(core_goal="inline", core_goal_file="goal.md")


if __name__ == "__main__":
    unittest.main()
