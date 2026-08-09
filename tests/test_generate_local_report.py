from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.scripts import generate_local_report
from src.services import local_report_service


class GenerateLocalReportTests(unittest.TestCase):
    def _write_artifacts(self, base: Path) -> tuple[Path, Path]:
        raw_file = base / "garmin_raw_20260510.json"
        user_file = base / "garmin_user_20260510.json"
        raw_file.write_text(
            json.dumps(
                [
                    {
                        "activity_id": 1,
                        "type": "running",
                        "date": "2026-05-10",
                        "distance": 10.0,
                        "duration": 50.0,
                    },
                    {
                        "activity_id": 2,
                        "type": "running",
                        "date": "2026-05-09",
                        "distance": 5.0,
                        "duration": 25.0,
                    },
                ]
            ),
            encoding="utf-8",
        )
        user_file.write_text(json.dumps({"max_heart_rate": 190}), encoding="utf-8")
        return raw_file, user_file

    def test_service_generates_dashboard_artifacts_from_local_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            raw_file, user_file = self._write_artifacts(base)
            processed_dir = base / "processed"
            output_dir = base / "output"

            with patch.object(
                local_report_service,
                "generate_coach_report",
                return_value={"headline": "local report"},
            ) as generate_mock:
                report_path = local_report_service.generate_local_report_from_artifacts(
                    raw_file=raw_file,
                    user_file=user_file,
                    report_date="20260510",
                    activity_limit=1,
                    processed_dir=processed_dir,
                    output_dir=output_dir,
                )

            self.assertEqual(report_path, str(output_dir / "ai_report_20260510.json"))
            self.assertTrue((processed_dir / "processed_20260510.csv").exists())
            self.assertTrue((processed_dir / "coach_context_20260510.json").exists())
            self.assertTrue((output_dir / "ai_report_20260510.json").exists())
            _, kwargs = generate_mock.call_args
            self.assertEqual(len(kwargs["processed_data"]), 1)
            self.assertEqual(kwargs["deterministic_context"]["meta"]["today"], "2026-05-10")

    def test_service_refuses_existing_report_before_llm_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            raw_file, user_file = self._write_artifacts(base)
            output_dir = base / "output"
            output_dir.mkdir()
            (output_dir / "ai_report_20260510.json").write_text("{}", encoding="utf-8")

            with patch.object(local_report_service, "generate_coach_report") as generate_mock:
                with self.assertRaises(FileExistsError):
                    local_report_service.generate_local_report_from_artifacts(
                        raw_file=raw_file,
                        user_file=user_file,
                        report_date="20260510",
                        processed_dir=base / "processed",
                        output_dir=output_dir,
                    )

        generate_mock.assert_not_called()

    def test_service_raises_when_preprocessing_leaves_no_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            raw_file, user_file = self._write_artifacts(base)

            with patch.object(local_report_service, "generate_coach_report") as generate_mock:
                with self.assertRaisesRegex(ValueError, "No data left after preprocessing."):
                    local_report_service.generate_local_report_from_artifacts(
                        raw_file=raw_file,
                        user_file=user_file,
                        report_date="20260510",
                        activity_limit=0,
                        processed_dir=base / "processed",
                        output_dir=base / "output",
                    )

        generate_mock.assert_not_called()

    def test_cli_main_flow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            raw_file, user_file = self._write_artifacts(base)

            with patch.object(
                generate_local_report,
                "generate_local_report_from_artifacts",
                return_value="output/ai_report_20260510.json",
            ) as service_mock:
                report_path = generate_local_report.main(
                    [
                        "--raw-file",
                        str(raw_file),
                        "--user-file",
                        str(user_file),
                        "--report-date",
                        "20260510",
                        "--activity-limit",
                        "12",
                        "--force",
                    ]
                )

        self.assertEqual(report_path, "output/ai_report_20260510.json")
        _, kwargs = service_mock.call_args
        self.assertEqual(kwargs["activity_limit"], 12)
        self.assertTrue(kwargs["force"])

    def test_cli_rejects_invalid_report_date(self):
        with self.assertRaises(SystemExit):
            generate_local_report.parse_args(
                [
                    "--raw-file",
                    "raw.json",
                    "--user-file",
                    "user.json",
                    "--report-date",
                    "2026-05-10",
                ]
            )

    def test_cli_rejects_negative_activity_limit(self):
        with self.assertRaises(SystemExit):
            generate_local_report.parse_args(
                [
                    "--raw-file",
                    "raw.json",
                    "--user-file",
                    "user.json",
                    "--report-date",
                    "20260510",
                    "--activity-limit",
                    "-1",
                ]
            )

    def test_cli_and_service_import_without_garmin_or_db_dependencies(self):
        script = r"""
import importlib.abc
import json
import sys
from pathlib import Path

forbidden_prefixes = (
    "src.ingestion",
    "src.db",
    "src.services.garmin_import_service",
)

class RejectForbiddenDependency(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(
            fullname == prefix or fullname.startswith(prefix + ".")
            for prefix in forbidden_prefixes
        ):
            raise ImportError(f"forbidden local-report dependency requested: {fullname}")
        return None

sys.meta_path.insert(0, RejectForbiddenDependency())

from src.services import local_report_service  # noqa: F401
from src.services import report_generator
from src.scripts import generate_local_report  # noqa: F401

base = Path(sys.argv[1])
raw_file = base / "garmin_raw_20260510.json"
user_file = base / "garmin_user_20260510.json"
processed_dir = base / "processed"
output_dir = base / "output"
raw_file.write_text(
    json.dumps(
        [
            {
                "activity_id": 1,
                "type": "running",
                "date": "2026-05-10",
                "distance": 10.0,
                "duration": 50.0,
            }
        ]
    ),
    encoding="utf-8",
)
user_file.write_text(json.dumps({"max_heart_rate": 190}), encoding="utf-8")

report_generator.coach = lambda **kwargs: {"headline": "local-only report"}

def generate_in_temp(**kwargs):
    return local_report_service.generate_local_report_from_artifacts(
        **kwargs,
        processed_dir=processed_dir,
        output_dir=output_dir,
    )

generate_local_report.generate_local_report_from_artifacts = generate_in_temp
report_path = generate_local_report.main(
    [
        "--raw-file",
        str(raw_file),
        "--user-file",
        str(user_file),
        "--report-date",
        "20260510",
        "--activity-limit",
        "1",
    ]
)
payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
assert payload["headline"] == "local-only report"
assert (processed_dir / "processed_20260510.csv").exists()
assert (processed_dir / "coach_context_20260510.json").exists()

print("local-only flow passed")
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [sys.executable, "-c", script, temp_dir],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("local-only flow passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
