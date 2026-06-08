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

try:
    import dotenv  # noqa: F401
except ImportError:
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

from src.pipeline import activity_payloads, runner
from src.pipeline.activity_payloads import ActivityPayloadProvider
from src.pipeline.goal_prompt import GoalPromptOverrides
from src.services import report_generator


class RunnerTests(unittest.TestCase):
    def test_fetch_garmin_updates_fetches_from_latest_db_date(self):
        fetch = Mock(return_value={"activities": [], "user_data": {}})
        provider = ActivityPayloadProvider(garmin_fetcher=fetch)
        provider._fetch_garmin_updates(
            latest_date=date(2026, 5, 10),
            fetch_limit=999,
            fallback_max_heart_rate=191,
        )

        fetch.assert_called_once_with(
            999,
            progress=True,
            since_date=date(2026, 5, 10),
            fallback_max_heart_rate=191,
        )

    def test_sync_garmin_to_db_delegates_already_fetched_payload_import(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            raw_dir = base / "raw"
            session = Mock()
            garmin_data = {
                "activities": [{"activity_id": 1, "type": "cycling", "date": "2026-05-10"}],
                "user_data": {"max_heart_rate": 190},
            }

            provider = ActivityPayloadProvider(
                raw_data_dir=raw_dir,
                import_service=Mock(
                    return_value={
                        "activities": 1,
                        "splits": 0,
                        "swimming_lengths": 0,
                        "user_snapshot": True,
                        "user_snapshot_id": "snapshot-1",
                        "raw_import": {"activities": 1, "splits": 0, "swimming_lengths": 0},
                    },
                ),
            )
            counts = provider._sync_garmin_to_db(
                session=session,
                user_id="user-1",
                timestamp="20260510",
                garmin_data=garmin_data,
            )

            provider.import_service.assert_called_once_with(
                session=session,
                user_id="user-1",
                user_path=raw_dir / "garmin_user_20260510.json",
                raw_path=raw_dir / "garmin_raw_20260510.json",
            )
            session.commit.assert_not_called()
            self.assertEqual(counts["activities"], 1)
            self.assertTrue(counts["user_snapshot"])
            self.assertTrue((raw_dir / "garmin_raw_20260510.json").exists())
            self.assertTrue((raw_dir / "garmin_user_20260510.json").exists())

    def test_sync_garmin_to_db_runs_shadow_sync_and_parity_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            raw_dir = base / "raw"
            session = Mock()
            garmin_data = {
                "activities": [{"activity_id": 1, "type": "cycling", "date": "2026-05-10"}],
                "user_data": {"max_heart_rate": 190},
            }

            provider = ActivityPayloadProvider(
                raw_data_dir=raw_dir,
                import_service=Mock(
                    return_value={
                        "activities": 1,
                        "splits": 0,
                        "swimming_lengths": 0,
                        "user_snapshot": True,
                        "shadow_import": {"rows_copied": 10},
                        "shadow_parity": {"ok": True, "mismatches": []},
                    },
                ),
            )
            counts = provider._sync_garmin_to_db(
                session=session,
                user_id="user-1",
                timestamp="20260510",
                garmin_data=garmin_data,
            )

            provider.import_service.assert_called_once()
            self.assertIn("shadow_import", counts)
            self.assertEqual(counts["shadow_parity"]["ok"], True)

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

        provider = ActivityPayloadProvider(session_factory=lambda: FakeSessionContext())
        with patch.object(
            activity_payloads, "get_or_create_default_user", return_value=types.SimpleNamespace(id="user-1")
        ), patch.object(provider, "_get_latest_activity_date", return_value=date(2026, 5, 10)), patch.object(
            activity_payloads, "get_recent_max_heart_rate", return_value=191
        ), patch.object(provider, "_fetch_garmin_updates", return_value=garmin_payload), patch.object(
            provider, "_sync_garmin_to_db", side_effect=SQLAlchemyError("bind params hidden by runner")
        ), patch.object(provider, "_load_existing_db_payloads", return_value=existing_payload), patch.object(
            provider, "_fetch_without_db"
        ) as fallback:
            raw_activities, user_data = provider.load_or_fetch(
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

        provider = ActivityPayloadProvider(session_factory=lambda: FakeSessionContext())
        with patch.object(
            activity_payloads, "get_or_create_default_user", return_value=types.SimpleNamespace(id="user-1")
        ), patch.object(provider, "_get_latest_activity_date", return_value=date(2026, 5, 10)), patch.object(
            activity_payloads, "get_recent_max_heart_rate", return_value=191
        ), patch.object(provider, "_fetch_garmin_updates", return_value=garmin_payload), patch.object(
            provider, "_sync_garmin_to_db", side_effect=SQLAlchemyError("bind params hidden by runner")
        ), patch.object(provider, "_load_existing_db_payloads", side_effect=SQLAlchemyError("read failed")), patch.object(
            provider, "_fetch_without_db"
        ) as fallback:
            raw_activities, user_data = provider.load_or_fetch(
                activity_limit=75,
                fetch_limit=999,
                timestamp="20260510",
            )

        fallback.assert_not_called()
        self.assertEqual(raw_activities, garmin_payload["activities"])
        self.assertEqual(user_data, garmin_payload["user_data"])

    def test_load_or_fetch_falls_back_to_direct_fetch_when_db_fails_before_fetch(self):
        class FakeSessionContext:
            def __enter__(self):
                return Mock()

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        direct_payload = (
            [{"activity_id": 1, "type": "running"}],
            {"max_heart_rate": 190},
        )
        provider = ActivityPayloadProvider(session_factory=lambda: FakeSessionContext())

        with patch.object(
            activity_payloads,
            "get_or_create_default_user",
            side_effect=SQLAlchemyError("db unavailable"),
        ), patch.object(provider, "_fetch_without_db", return_value=direct_payload) as fallback:
            raw_activities, user_data = provider.load_or_fetch(
                activity_limit=75,
                fetch_limit=999,
                timestamp="20260510",
            )

        fallback.assert_called_once_with(activity_limit=75, timestamp="20260510")
        self.assertEqual(raw_activities, direct_payload[0])
        self.assertEqual(user_data, direct_payload[1])

    def test_runner_load_or_fetch_delegates_to_activity_payload_provider(self):
        provider = Mock()
        provider.load_or_fetch.return_value = ([{"activity_id": 1}], {"max_heart_rate": 190})

        with patch.object(runner, "RAW_DATA_DIR", Path("custom/raw")), patch.object(
            runner,
            "ActivityPayloadProvider",
            return_value=provider,
        ) as provider_class:
            raw_activities, user_data = runner._load_or_fetch_activity_payloads(
                activity_limit=75,
                fetch_limit=999,
                timestamp="20260510",
            )

        provider_class.assert_called_once_with(raw_data_dir=Path("custom/raw"))
        provider.load_or_fetch.assert_called_once_with(
            activity_limit=75,
            fetch_limit=999,
            timestamp="20260510",
        )
        self.assertEqual(raw_activities, [{"activity_id": 1}])
        self.assertEqual(user_data, {"max_heart_rate": 190})

    def test_apply_resting_heart_rate_history_fills_missing_from_latest_db_value(self):
        session = Mock()
        provider = ActivityPayloadProvider()
        with patch.object(activity_payloads, "get_latest_resting_heart_rate", return_value=51.0):
            user_data = provider._apply_resting_heart_rate_history(
                session=session,
                user_id="user-1",
                user_data={"max_heart_rate": 190, "resting_heart_rate": None},
            )

        self.assertEqual(user_data["resting_heart_rate"], 51.0)
        self.assertEqual(user_data["resting_heart_rate_source"], "db_latest_profile_history")

    def test_apply_resting_heart_rate_history_keeps_current_day_value_when_present(self):
        session = Mock()
        provider = ActivityPayloadProvider()
        with patch.object(activity_payloads, "get_latest_resting_heart_rate", return_value=51.0):
            user_data = provider._apply_resting_heart_rate_history(
                session=session,
                user_id="user-1",
                user_data={"max_heart_rate": 190, "resting_heart_rate": 49},
            )

        self.assertEqual(user_data["resting_heart_rate"], 49)
        self.assertNotIn("resting_heart_rate_source", user_data)

    def test_apply_resting_heart_rate_history_uses_db_value_when_smaller_than_current(self):
        session = Mock()
        provider = ActivityPayloadProvider()
        with patch.object(activity_payloads, "get_latest_resting_heart_rate", return_value=48.0):
            user_data = provider._apply_resting_heart_rate_history(
                session=session,
                user_id="user-1",
                user_data={"max_heart_rate": 190, "resting_heart_rate": 51},
            )

        self.assertEqual(user_data["resting_heart_rate"], 48.0)
        self.assertEqual(user_data["resting_heart_rate_source"], "db_latest_profile_history")

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

    def test_run_pipeline_stops_before_processing_when_no_activities_loaded(self):
        with patch.object(runner, "_build_timestamp", return_value="20260510"), patch.object(
            runner,
            "_load_or_fetch_activity_payloads",
            return_value=([], {"max_heart_rate": 190}),
        ) as load_payloads, patch.object(runner, "preprocess_data") as preprocess_mock, patch.object(
            runner, "_persist_pipeline_artifacts"
        ) as persist_mock:
            report = runner.run_pipeline()

        self.assertIsNone(report)
        load_payloads.assert_called_once_with(
            activity_limit=75,
            fetch_limit=75,
            timestamp="20260510",
        )
        preprocess_mock.assert_not_called()
        persist_mock.assert_not_called()

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

    def test_run_pipeline_writes_processed_csv_and_json_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            processed_dir = base / "processed"
            output_dir = base / "output"
            raw_activities = [{"activity_id": 1, "type": "running", "distance": 10.0, "duration": 50.0}]
            processed_data = [{"activity_id": 1, "type": "running", "date": "2026-05-10", "distance_km": 10, "performance_formatted": "5:00 /km"}]
            report_payload = {"headline": "report"}

            with patch.object(runner, "PROCESSED_DATA_DIR", processed_dir
            ), patch.object(runner, "OUTPUT_DIR", output_dir), patch.object(
                runner, "_build_timestamp", return_value="20260510"
            ), patch.object(
                runner,
                "_load_or_fetch_activity_payloads",
                return_value=(raw_activities, {"max_heart_rate": 190}),
            ), patch.object(runner, "preprocess_data", return_value=processed_data), patch.object(
                report_generator, "coach", return_value=report_payload
            ) as coach_mock:
                report = runner.run_pipeline()

            self.assertEqual(report, str(output_dir / "ai_report_20260510.json"))
            self.assertTrue((processed_dir / "processed_20260510.csv").exists())
            self.assertTrue((processed_dir / "coach_context_20260510.json").exists())
            self.assertTrue((output_dir / "ai_report_20260510.json").exists())
            _, coach_kwargs = coach_mock.call_args
            self.assertEqual(coach_kwargs["deterministic_context"]["meta"]["today"], "2026-05-10")
            self.assertEqual(
                coach_kwargs["deterministic_context"]["weekly_analysis"][0]["week_start"],
                "2026-05-04",
            )
            report_body = json.loads((output_dir / "ai_report_20260510.json").read_text(encoding="utf-8"))
            self.assertEqual(report_body["headline"], "report")
            self.assertEqual(report_body["meta"]["today"], "2026-05-10")
            self.assertEqual(report_body["weekly_analysis"][0]["week_start"], "2026-05-04")
            self.assertEqual(report_body["weekly_analysis"][0]["sessions"][0]["activity_id"], 1)

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
                runner, "_persist_pipeline_artifacts", return_value=Path("output/report.json")
            ), patch.object(
                report_generator, "coach", return_value={"headline": "report"}
            ) as coach_mock:
                report = runner.run_pipeline(goal_overrides=overrides)

        self.assertEqual(report, "output/report.json")
        _, kwargs = coach_mock.call_args
        self.assertIn("* 目標成績：5K 20:00", kwargs["goal_text"])
        self.assertIn("* default preference", kwargs["goal_text"])
        self.assertEqual(kwargs["goal_path"], str(goal_path))
        self.assertIn("deterministic_context", kwargs)

    def test_generate_coach_report_renders_goal_and_applies_deterministic_overlay(self):
        processed_data = [{"activity_id": 1, "performance_formatted": "5:00 /km"}]
        user_data = {"max_heart_rate": 190}
        deterministic_context = {"meta": {"today": "2026-05-10"}}
        overrides = GoalPromptOverrides(core_goal="目標成績：5K 20:00")
        ai_response = {"headline": "report"}
        enforced_response = {"headline": "enforced report"}

        with tempfile.TemporaryDirectory() as temp_dir:
            goal_path = Path(temp_dir) / "goal.md"
            goal_path.write_text(
                "# Training Goal\n\n"
                "## 🎯 核心目標\n"
                "* old goal\n",
                encoding="utf-8",
            )

            with patch.object(runner, "GOAL_PROMPT_PATH", goal_path), patch.object(
                report_generator, "coach", return_value=ai_response
            ) as coach_mock, patch.object(
                report_generator,
                "enforce_deterministic_report_fields",
                return_value=enforced_response,
            ) as enforce_mock:
                report = runner._generate_coach_report(
                    processed_data=processed_data,
                    user_data=user_data,
                    deterministic_context=deterministic_context,
                    goal_overrides=overrides,
                )

        self.assertEqual(report, enforced_response)
        _, coach_kwargs = coach_mock.call_args
        self.assertEqual(coach_kwargs["data"], processed_data)
        self.assertEqual(coach_kwargs["user_data"], user_data)
        self.assertEqual(coach_kwargs["deterministic_context"], deterministic_context)
        self.assertEqual(coach_kwargs["goal_path"], str(goal_path))
        self.assertIn("* 目標成績：5K 20:00", coach_kwargs["goal_text"])
        enforce_mock.assert_called_once_with(ai_response, deterministic_context)

    def test_public_generate_coach_report_accepts_goal_prompt_path(self):
        processed_data = [{"activity_id": 1, "performance_formatted": "5:00 /km"}]
        user_data = {"max_heart_rate": 190}
        deterministic_context = {"meta": {"today": "2026-05-10"}}
        overrides = GoalPromptOverrides(training_preferences="每週最多 5 天訓練")

        with tempfile.TemporaryDirectory() as temp_dir:
            goal_path = Path(temp_dir) / "goal.md"
            goal_path.write_text(
                "# Training Goal\n\n"
                "## ⚙️ 訓練偏好與限制\n"
                "* default preference\n",
                encoding="utf-8",
            )

            with patch.object(
                report_generator,
                "coach",
                return_value={"headline": "report"},
            ) as coach_mock, patch.object(
                report_generator,
                "enforce_deterministic_report_fields",
                return_value={"headline": "enforced"},
            ):
                report = report_generator.generate_coach_report(
                    processed_data=processed_data,
                    user_data=user_data,
                    deterministic_context=deterministic_context,
                    goal_overrides=overrides,
                    goal_prompt_path=goal_path,
                )

        self.assertEqual(report, {"headline": "enforced"})
        _, coach_kwargs = coach_mock.call_args
        self.assertEqual(coach_kwargs["goal_path"], str(goal_path))
        self.assertIn("* 每週最多 5 天訓練", coach_kwargs["goal_text"])

    def test_fetch_without_db_persists_raw_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "raw"

            provider = ActivityPayloadProvider(
                raw_data_dir=raw_dir,
                garmin_fetcher=Mock(
                    return_value={
                        "activities": [
                            {"activity_id": 1, "type": "running", "distance": 10.0, "duration": 50.0}
                        ],
                        "user_data": {"max_heart_rate": 190},
                    },
                ),
            )
            raw_activities, user_data = provider._fetch_without_db(activity_limit=75, timestamp="20260510")

            self.assertEqual(len(raw_activities), 1)
            self.assertEqual(user_data["max_heart_rate"], 190)

            raw_payload = json.loads((raw_dir / "garmin_user_20260510.json").read_text(encoding="utf-8"))
            self.assertEqual(raw_payload["max_heart_rate"], 190)


if __name__ == "__main__":
    unittest.main()
