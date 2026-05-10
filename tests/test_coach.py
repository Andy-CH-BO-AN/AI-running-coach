import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

dotenv_stub = types.ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda *args, **kwargs: None
sys.modules.setdefault("dotenv", dotenv_stub)

google_stub = types.ModuleType("google")
genai_stub = types.ModuleType("google.genai")
pandas_stub = types.ModuleType("pandas")


class _FakeModels:
    def generate_content(self, **kwargs):
        return types.SimpleNamespace(text="stub report")


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.models = _FakeModels()


class _FakeDataFrame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient="records"):
        return self.rows


def _fake_read_csv(path):
    return _FakeDataFrame([{"activity_id": 1, "distance_km": 10.0}])


genai_stub.Client = _FakeClient
google_stub.genai = genai_stub
pandas_stub.read_csv = _fake_read_csv
sys.modules.setdefault("google", google_stub)
sys.modules.setdefault("google.genai", genai_stub)
sys.modules.setdefault("pandas", pandas_stub)

from src.agents import coach


class CoachTests(unittest.TestCase):
    def test_build_context_includes_goal_user_data_and_activity_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            goal_path = Path(temp_dir) / "goal.md"
            goal_path.write_text("sub-20 5k", encoding="utf-8")

            context = coach._build_context(
                data=[{"activity_id": 1}],
                user_data={"max_heart_rate": 190},
                goal_path=str(goal_path),
            )

        self.assertIn("sub-20 5k", context)
        self.assertIn('"max_heart_rate": 190', context)
        self.assertIn('"activity_id": 1', context)

    def test_run_local_analysis_reads_user_json_and_writes_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            json_path = base / "garmin_user_20260510.json"
            json_path.write_text(json.dumps({"max_heart_rate": 190}), encoding="utf-8")
            output_dir = base / "output"

            with patch.object(coach, "OUTPUT_DIR", output_dir), patch.object(
                coach, "coach", return_value="# report"
            ), patch.object(coach, "_load_processed_records", return_value=[{"activity_id": 1}]):
                coach.run_local_analysis("processed.csv", str(json_path), goal_path=str(base / "missing_goal.md"))

            report_path = output_dir / "ai_report_20260510.md"
            reports = list(output_dir.glob("ai_report_*.md"))
            self.assertEqual(len(reports), 1)
            report_body = reports[0].read_text(encoding="utf-8")
            self.assertIn("# report", report_body)


if __name__ == "__main__":
    unittest.main()
