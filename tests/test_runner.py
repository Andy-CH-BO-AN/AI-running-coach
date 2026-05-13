import json
import os
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy.exc import SQLAlchemyError

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
pandas_module = sys.modules.setdefault("pandas", pandas_stub)
pandas_module.json_normalize = _fake_json_normalize

garminconnect_stub = types.ModuleType("garminconnect")
garminconnect_stub.Garmin = object
sys.modules.setdefault("garminconnect", garminconnect_stub)

from src.pipeline import runner
from src.pipeline.goal_prompt import GoalPromptOverrides


class RunnerTests(unittest.TestCase):
    def test_fetch_garmin_updates_fetches_from_latest_db_date(self):
        with patch.object(
            runner,
            "get_garmin_activities",
            return_value={"activities": [], "user_data": {}},
        ) as fetch:
            runner._fetch_garmin_updates(latest_date=date(2026, 5, 10), fetch_limit=999)

        fetch.assert_called_once_with(
            999,
            progress=True,
            since_date=date(2026, 5, 10),
        )

    def test_sync_garmin_to_db_imports_already_fetched_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            raw_dir = base / "raw"
            session = Mock()
            garmin_data = {
                "activities": [{"activity_id": 1, "type": "cycling", "date": "2026-05-10"}],
                "user_data": {"max_heart_rate": 190},
            }

            with patch.object(runner, "RAW_DATA_DIR", raw_dir), patch.object(
                runner, "import_garmin_user_file"
            ) as import_user, patch.object(
                runner, "import_garmin_raw_file", return_value={"activities": 1, "splits": 0, "swimming_lengths": 0}
            ) as import_raw:
                counts = runner._sync_garmin_to_db(
                    session=session,
                    user_id="user-1",
                    timestamp="20260510",
                    garmin_data=garmin_data,
                )

            import_user.assert_called_once()
            import_raw.assert_called_once()
            session.commit.assert_called_once()
            self.assertEqual(counts["activities"], 1)
            self.assertTrue((raw_dir / "garmin_raw_20260510.json").exists())
            self.assertTrue((raw_dir / "garmin_user_20260510.json").exists())

    def test_load_or_fetch_reads_existing_db_payloads_when_db_import_fails_after_fetch(self):
        class FakeSessionContext:
            def __enter__(self):
                return Mock()

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        garmin_payload = {
            "activities": [{"activity_id": 1, "type": "running", "distance": 10.0, "duration": 50.0}],
            "user_data": {"max_heart_rate": 190},
        }
        existing_payload = (
            [{"activity_id": index, "type": "running"} for index in range(75)],
            {"max_heart_rate": 190},
        )

        with patch.object(runner, "SessionLocal", return_value=FakeSessionContext()), patch.object(
            runner, "get_or_create_default_user", return_value=types.SimpleNamespace(id="user-1")
        ), patch.object(runner, "_get_latest_activity_date", return_value=date(2026, 5, 10)), patch.object(
            runner, "_fetch_garmin_updates", return_value=garmin_payload
        ), patch.object(
            runner, "_sync_garmin_to_db", side_effect=SQLAlchemyError("bind params hidden by runner")
        ), patch.object(
            runner, "_load_existing_db_payloads", return_value=existing_payload
        ), patch.object(
            runner, "_fetch_without_db"
        ) as fallback:
            raw_activities, user_data = runner._load_or_fetch_activity_payloads(
                activity_limit=75,
                fetch_limit=999,
                timestamp="20260510",
            )

        fallback.assert_not_called()
        self.assertEqual(len(raw_activities), 75)
        self.assertEqual(user_data, existing_payload[1])

    def test_load_or_fetch_reuses_fetched_payload_when_db_read_also_fails(self):
        class FakeSessionContext:
            def __enter__(self):
                return Mock()

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        garmin_payload = {
            "activities": [{"activity_id": 1, "type": "running", "distance": 10.0, "duration": 50.0}],
            "user_data": {"max_heart_rate": 190},
        }

        with patch.object(runner, "SessionLocal", return_value=FakeSessionContext()), patch.object(
            runner, "get_or_create_default_user", return_value=types.SimpleNamespace(id="user-1")
        ), patch.object(runner, "_get_latest_activity_date", return_value=date(2026, 5, 10)), patch.object(
            runner, "_fetch_garmin_updates", return_value=garmin_payload
        ), patch.object(
            runner, "_sync_garmin_to_db", side_effect=SQLAlchemyError("bind params hidden by runner")
        ), patch.object(
            runner, "_load_existing_db_payloads", side_effect=SQLAlchemyError("read failed")
        ), patch.object(
            runner, "_fetch_without_db"
        ) as fallback:
            raw_activities, user_data = runner._load_or_fetch_activity_payloads(
                activity_limit=75,
                fetch_limit=999,
                timestamp="20260510",
            )

        fallback.assert_not_called()
        self.assertEqual(raw_activities, garmin_payload["activities"])
        self.assertEqual(user_data, garmin_payload["user_data"])

    def test_run_pipeline_uses_db_loaded_activities_and_filters_all_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_activities = [{"activity_id": 1, "type": "cycling", "distance": 0.5, "duration": 2.0}]

            with patch.object(runner, "_build_timestamp", return_value="20260510"), patch.object(
                runner,
                "_load_or_fetch_activity_payloads",
                return_value=(raw_activities, {"max_heart_rate": 190}),
            ) as load_payloads, patch.object(runner, "preprocess_data", return_value=[]):
                report = runner.run_pipeline()

            self.assertIsNone(report)
            load_payloads.assert_called_once_with(
                activity_limit=75,
                fetch_limit=75,
                timestamp="20260510",
            )

    def test_run_pipeline_defaults_fetch_limit_to_activity_limit(self):
        raw_activities = [{"activity_id": 1, "type": "running", "distance": 10.0, "duration": 50.0}]

        with patch.object(runner, "_build_timestamp", return_value="20260510"), patch.object(
            runner,
            "_load_or_fetch_activity_payloads",
            return_value=(raw_activities, {"max_heart_rate": 190}),
        ) as load_payloads, patch.object(runner, "preprocess_data", return_value=[]):
            report = runner.run_pipeline(activity_limit=12)

        self.assertIsNone(report)
        load_payloads.assert_called_once_with(
            activity_limit=12,
            fetch_limit=12,
            timestamp="20260510",
        )

    def test_run_pipeline_preserves_explicit_fetch_limit_zero(self):
        raw_activities = [{"activity_id": 1, "type": "running", "distance": 10.0, "duration": 50.0}]

        with patch.object(runner, "_build_timestamp", return_value="20260510"), patch.object(
            runner,
            "_load_or_fetch_activity_payloads",
            return_value=(raw_activities, {"max_heart_rate": 190}),
        ) as load_payloads, patch.object(runner, "preprocess_data", return_value=[]):
            report = runner.run_pipeline(fetch_limit=0)

        self.assertIsNone(report)
        load_payloads.assert_called_once_with(
            activity_limit=75,
            fetch_limit=0,
            timestamp="20260510",
        )

    def test_run_pipeline_writes_processed_csv_and_markdown_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            processed_dir = base / "processed"
            output_dir = base / "output"
            raw_activities = [{"activity_id": 1, "type": "running", "distance": 10.0, "duration": 50.0}]
            processed_data = [{"activity_id": 1, "performance_formatted": "5:00 /km"}]

            with patch.object(runner, "PROCESSED_DATA_DIR", processed_dir
            ), patch.object(runner, "OUTPUT_DIR", output_dir), patch.object(
                runner, "_build_timestamp", return_value="20260510"
            ), patch.object(
                runner,
                "_load_or_fetch_activity_payloads",
                return_value=(raw_activities, {"max_heart_rate": 190}),
            ), patch.object(runner, "preprocess_data", return_value=processed_data), patch.object(
                runner, "coach", return_value="# report"
            ):
                report = runner.run_pipeline()

            self.assertEqual(report, str(output_dir / "ai_report_20260510.md"))
            self.assertTrue((processed_dir / "processed_20260510.csv").exists())
            self.assertTrue((output_dir / "ai_report_20260510.md").exists())

    def test_run_pipeline_passes_rendered_goal_overrides_to_coach(self):
        raw_activities = [{"activity_id": 1, "type": "running", "distance": 10.0, "duration": 50.0}]
        processed_data = [{"activity_id": 1, "performance_formatted": "5:00 /km"}]
        overrides = GoalPromptOverrides(core_goal="目標成績：5K 20:00")

        with tempfile.TemporaryDirectory() as temp_dir:
            goal_path = Path(temp_dir) / "goal.md"
            goal_path.write_text(
                "# Training Goal\n\n"
                "## 🎯 核心目標\n"
                "* old goal\n\n"
                "## ⚙️ 訓練偏好與限制\n"
                "* default preference\n",
                encoding="utf-8",
            )

            with patch.object(runner, "GOAL_PROMPT_PATH", goal_path), patch.object(
                runner, "_build_timestamp", return_value="20260510"
            ), patch.object(
                runner,
                "_load_or_fetch_activity_payloads",
                return_value=(raw_activities, {"max_heart_rate": 190}),
            ), patch.object(runner, "preprocess_data", return_value=processed_data), patch.object(
                runner, "_persist_pipeline_artifacts", return_value=Path("output/report.md")
            ), patch.object(
                runner, "coach", return_value="# report"
            ) as coach_mock:
                report = runner.run_pipeline(goal_overrides=overrides)

        self.assertEqual(report, "output/report.md")
        _, kwargs = coach_mock.call_args
        self.assertIn("* 目標成績：5K 20:00", kwargs["goal_text"])
        self.assertIn("* default preference", kwargs["goal_text"])
        self.assertEqual(kwargs["goal_path"], str(goal_path))

    def test_fetch_without_db_persists_raw_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "raw"

            with patch.object(runner, "RAW_DATA_DIR", raw_dir), patch.object(
                runner,
                "get_garmin_activities",
                return_value={
                    "activities": [{"activity_id": 1, "type": "running", "distance": 10.0, "duration": 50.0}],
                    "user_data": {"max_heart_rate": 190},
                },
            ):
                raw_activities, user_data = runner._fetch_without_db(activity_limit=75, timestamp="20260510")

            self.assertEqual(len(raw_activities), 1)
            self.assertEqual(user_data["max_heart_rate"], 190)

            raw_payload = json.loads((raw_dir / "garmin_user_20260510.json").read_text(encoding="utf-8"))
            self.assertEqual(raw_payload["max_heart_rate"], 190)


if __name__ == "__main__":
    unittest.main()
