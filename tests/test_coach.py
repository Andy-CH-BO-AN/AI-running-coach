import json
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

dotenv_available = "dotenv" in sys.modules
if not dotenv_available:
    try:
        dotenv_available = importlib.util.find_spec("dotenv") is not None
    except ValueError:
        dotenv_available = True

if not dotenv_available:
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
    def test_default_model_fallback_order_prefers_preview_gemini_3(self):
        self.assertEqual(
            coach.MODEL_FALLBACKS,
            (
                "gemini-3.5-flash",
                "gemini-3-flash-preview",
                "gemini-3.1-flash-lite",
                "gemini-2.5-flash",
            ),
        )

    def test_build_context_includes_goal_user_data_and_activity_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            goal_path = Path(temp_dir) / "goal.md"
            goal_path.write_text("sub-20 5k", encoding="utf-8")

            context = coach._build_context(
                data=[{"activity_id": 1}],
                user_data={"max_heart_rate": 190},
                goal_path=str(goal_path),
                deterministic_context={"meta": {"today": "2026-05-10"}},
            )

        self.assertIn("sub-20 5k", context)
        self.assertIn('"max_heart_rate": 190', context)
        self.assertIn("Deterministic Coach Context", context)
        self.assertIn('"today": "2026-05-10"', context)
        self.assertIn('"activity_id": 1', context)

    def test_coach_normalizes_json_wrapped_in_markdown_fences(self):
        generate_content = Mock(
            return_value=types.SimpleNamespace(text='```json\n{"headline": "wrapped report"}\n```')
        )
        fake_client = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate_content))

        with patch.object(coach, "client", fake_client), patch.object(
            coach, "MODEL_FALLBACKS", ("model-a",)
        ):
            report = coach.coach(data=[{"activity_id": 1}])

        self.assertEqual(report, {"headline": "wrapped report"})

    def test_coach_passes_deterministic_context_into_prompt(self):
        generate_content = Mock(return_value=types.SimpleNamespace(text='{"headline": "report"}'))
        fake_client = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate_content))

        with patch.object(coach, "client", fake_client), patch.object(
            coach, "MODEL_FALLBACKS", ("model-a",)
        ):
            coach.coach(
                data=[{"activity_id": 1}],
                deterministic_context={"meta": {"today": "2026-05-10"}},
            )

        prompt = generate_content.call_args.kwargs["contents"]
        self.assertIn("Deterministic Coach Context", prompt)
        self.assertIn('"today": "2026-05-10"', prompt)

    def test_run_local_analysis_reads_user_json_and_writes_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            json_path = base / "garmin_user_20260510.json"
            json_path.write_text(json.dumps({"max_heart_rate": 190}), encoding="utf-8")
            output_dir = base / "output"

            with patch.object(coach, "OUTPUT_DIR", output_dir), patch.object(
                coach, "coach", return_value={"headline": "report"}
            ), patch.object(coach, "_load_processed_records", return_value=[{"activity_id": 1}]):
                coach.run_local_analysis("processed.csv", str(json_path), goal_path=str(base / "missing_goal.md"))

            report_path = output_dir / "ai_report_20260510.json"
            reports = list(output_dir.glob("ai_report_*.json"))
            self.assertEqual(len(reports), 1)
            report_body = reports[0].read_text(encoding="utf-8")
            self.assertEqual(json.loads(report_body), {"headline": "report"})

    def test_coach_retries_retryable_error_three_times_then_succeeds(self):
        retryable_error = Exception(
            "503 UNAVAILABLE. This model is currently experiencing high demand. Please try again later."
        )
        generate_content = Mock(
            side_effect=[
                retryable_error,
                retryable_error,
                types.SimpleNamespace(text='{"headline": "recovered report"}'),
            ]
        )
        fake_client = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate_content))

        with patch.object(coach, "client", fake_client), patch.object(
            coach, "MODEL_FALLBACKS", ("model-a",)
        ), patch.object(coach.time, "sleep") as sleep_mock:
            report = coach.coach(data=[{"activity_id": 1}])

        self.assertEqual(report, {"headline": "recovered report"})
        self.assertEqual(generate_content.call_count, 3)
        self.assertEqual(sleep_mock.call_args_list, [call(1), call(2)])

    def test_coach_uses_gemini_retry_delay_when_available(self):
        retryable_error = Exception(
            "429 RESOURCE_EXHAUSTED. {'error': {'details': ["
            "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', "
            "'retryDelay': '5s'}]}}"
        )
        generate_content = Mock(
            side_effect=[
                retryable_error,
                types.SimpleNamespace(text='{"headline": "recovered report"}'),
            ]
        )
        fake_client = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate_content))

        with patch.object(coach, "client", fake_client), patch.object(
            coach, "MODEL_FALLBACKS", ("model-a",)
        ), patch.object(coach.time, "sleep") as sleep_mock:
            report = coach.coach(data=[{"activity_id": 1}])

        self.assertEqual(report, {"headline": "recovered report"})
        sleep_mock.assert_called_once_with(5.0)

    def test_coach_falls_back_after_retryable_error_exhausts_retries(self):
        call_counts = {"model-a": 0, "model-b": 0}

        def fake_generate_content(*, model, contents, **kwargs):
            call_counts[model] += 1
            if model == "model-a":
                raise Exception(
                    "503 UNAVAILABLE. This model is currently experiencing high demand. Please try again later."
                )
            return types.SimpleNamespace(text='{"headline": "fallback report"}')

        fake_client = types.SimpleNamespace(
            models=types.SimpleNamespace(generate_content=fake_generate_content)
        )

        with patch.object(coach, "client", fake_client), patch.object(
            coach, "MODEL_FALLBACKS", ("model-a", "model-b")
        ), patch.object(coach.time, "sleep"):
            report = coach.coach(data=[{"activity_id": 1}])

        self.assertEqual(report, {"headline": "fallback report"})
        self.assertEqual(call_counts["model-a"], 3)
        self.assertEqual(call_counts["model-b"], 1)

    def test_coach_does_not_retry_non_retryable_error(self):
        call_counts = {"model-a": 0, "model-b": 0}

        def fake_generate_content(*, model, contents, **kwargs):
            call_counts[model] += 1
            if model == "model-a":
                raise ValueError("400 INVALID_ARGUMENT")
            return types.SimpleNamespace(text='{"headline": "fallback report"}')

        fake_client = types.SimpleNamespace(
            models=types.SimpleNamespace(generate_content=fake_generate_content)
        )

        with patch.object(coach, "client", fake_client), patch.object(
            coach, "MODEL_FALLBACKS", ("model-a", "model-b")
        ), patch.object(coach.time, "sleep") as sleep_mock:
            report = coach.coach(data=[{"activity_id": 1}])

        self.assertEqual(report, {"headline": "fallback report"})
        self.assertEqual(call_counts["model-a"], 1)
        self.assertEqual(call_counts["model-b"], 1)
        sleep_mock.assert_not_called()

    def test_build_genai_client_uses_vertexai_when_flag_enabled(self):
        fake_client = object()

        with patch.dict(
            os.environ,
            {
                "GEMINI_KEY": "gcp-key",
                "GOOGLE_GENAI_USE_VERTEXAI": "true",
                "GOOGLE_CLOUD_PROJECT": "demo-project",
                "GOOGLE_CLOUD_LOCATION": "global",
            },
            clear=True,
        ), patch.object(coach.genai, "Client", return_value=fake_client) as client_mock:
            built_client = coach._build_genai_client()

        self.assertIs(built_client, fake_client)
        client_mock.assert_called_once_with(
            api_key="gcp-key",
            http_options={"api_version": "v1"},
            vertexai=True,
        )

    def test_build_genai_client_prefers_google_api_key_over_legacy_gemini_key(self):
        fake_client = object()

        with patch.dict(
            os.environ,
            {
                "GOOGLE_API_KEY": "new-gcp-key",
                "GEMINI_KEY": "legacy-key",
            },
            clear=True,
        ), patch.object(coach.genai, "Client", return_value=fake_client) as client_mock:
            built_client = coach._build_genai_client()

        self.assertIs(built_client, fake_client)
        client_mock.assert_called_once_with(
            api_key="new-gcp-key",
            http_options={"api_version": "v1"},
        )

    def test_build_genai_client_omits_project_location_for_vertexai_api_key(self):
        fake_client = object()

        with patch.dict(
            os.environ,
            {
                "GOOGLE_API_KEY": "gcp-key",
                "GOOGLE_GENAI_USE_VERTEXAI": "true",
                "GOOGLE_CLOUD_PROJECT": "demo-project",
                "GOOGLE_CLOUD_LOCATION": "global",
            },
            clear=True,
        ), patch.object(coach.genai, "Client", return_value=fake_client) as client_mock:
            built_client = coach._build_genai_client()

        self.assertIs(built_client, fake_client)
        client_mock.assert_called_once_with(
            api_key="gcp-key",
            http_options={"api_version": "v1"},
            vertexai=True,
        )

    def test_coach_switches_to_vertexai_after_payload_mismatch(self):
        mismatch_error = Exception(
            "400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': "
            "\"Invalid JSON payload received. Unknown name \\\"responseMimeType\\\" "
            "at 'generation_config': Cannot find field.\"}}"
        )
        developer_generate = Mock(side_effect=[mismatch_error])
        vertex_generate = Mock(return_value=types.SimpleNamespace(text='{"headline": "vertex report"}'))
        developer_client = types.SimpleNamespace(
            models=types.SimpleNamespace(generate_content=developer_generate),
            vertexai=False,
        )
        vertex_client = types.SimpleNamespace(
            models=types.SimpleNamespace(generate_content=vertex_generate),
            vertexai=True,
        )

        with patch.object(coach, "client", developer_client), patch.object(
            coach, "MODEL_FALLBACKS", ("model-a",)
        ), patch.object(coach, "_build_genai_client", return_value=vertex_client) as build_client:
            report = coach.coach(data=[{"activity_id": 1}])

        self.assertEqual(report, {"headline": "vertex report"})
        build_client.assert_called_once_with(vertexai=True)
        developer_generate.assert_called_once()
        vertex_generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
