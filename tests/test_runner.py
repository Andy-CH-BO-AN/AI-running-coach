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


genai_stub.Client = _FakeClient
google_stub.genai = genai_stub


class _FakeNormalizedFrame:
    def __init__(self, rows):
        self.rows = rows

    def to_csv(self, path, index=False, encoding=None):
        Path(path).write_text("activity_id,performance_formatted\n", encoding="utf-8")


def _fake_json_normalize(rows):
    return _FakeNormalizedFrame(rows)


pandas_stub.json_normalize = _fake_json_normalize
sys.modules.setdefault("google", google_stub)
sys.modules.setdefault("google.genai", genai_stub)
sys.modules.setdefault("pandas", pandas_stub)

garminconnect_stub = types.ModuleType("garminconnect")
garminconnect_stub.Garmin = object
sys.modules.setdefault("garminconnect", garminconnect_stub)

from src.pipeline import runner


class RunnerTests(unittest.TestCase):
    def test_run_pipeline_persists_raw_artifacts_even_when_preprocessing_filters_all_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            raw_dir = base / "raw"

            with patch.object(runner, "RAW_DATA_DIR", raw_dir), patch.object(
                runner, "_build_timestamp", return_value="20260510"
            ), patch.object(
                runner,
                "get_garmin_activities",
                return_value={
                    "activities": [{"activity_id": 1, "type": "cycling", "distance": 0.5, "duration": 2.0}],
                    "user_data": {"max_heart_rate": 190},
                },
            ), patch.object(runner, "preprocess_data", return_value=[]):
                report = runner.run_pipeline()

            self.assertIsNone(report)
            self.assertTrue((raw_dir / "garmin_raw_20260510.json").exists())
            self.assertTrue((raw_dir / "garmin_user_20260510.json").exists())

    def test_run_pipeline_writes_processed_csv_and_markdown_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            raw_dir = base / "raw"
            processed_dir = base / "processed"
            output_dir = base / "output"
            processed_data = [{"activity_id": 1, "performance_formatted": "5:00 /km"}]

            with patch.object(runner, "RAW_DATA_DIR", raw_dir), patch.object(
                runner, "PROCESSED_DATA_DIR", processed_dir
            ), patch.object(runner, "OUTPUT_DIR", output_dir), patch.object(
                runner, "_build_timestamp", return_value="20260510"
            ), patch.object(
                runner,
                "get_garmin_activities",
                return_value={
                    "activities": [{"activity_id": 1, "type": "running", "distance": 10.0, "duration": 50.0}],
                    "user_data": {"max_heart_rate": 190},
                },
            ), patch.object(runner, "preprocess_data", return_value=processed_data), patch.object(
                runner, "coach", return_value="# report"
            ):
                report = runner.run_pipeline()

            self.assertEqual(report, str(output_dir / "ai_report_20260510.md"))
            self.assertTrue((processed_dir / "processed_20260510.csv").exists())
            self.assertTrue((output_dir / "ai_report_20260510.md").exists())

            raw_payload = json.loads((raw_dir / "garmin_user_20260510.json").read_text(encoding="utf-8"))
            self.assertEqual(raw_payload["max_heart_rate"], 190)


if __name__ == "__main__":
    unittest.main()
