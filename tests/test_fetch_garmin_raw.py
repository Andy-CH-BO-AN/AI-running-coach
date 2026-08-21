import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.scripts.fetch_garmin_raw import fetch_garmin_raw_files, import_raw_files, parse_args
from src.services.garmin_import_service import import_fetched_raw_artifacts


def test_fetch_garmin_raw_files_writes_user_and_activity_json(tmp_path):
    garmin_payload = {
        "activities": [
            {
                "activity_id": 123,
                "type": "running",
                "date": "2026-05-10",
                "distance": 10.0,
                "duration": 50.0,
            }
        ],
        "user_data": {"vo2max_running": 53},
    }

    with patch("src.scripts.fetch_garmin_raw._get_garmin_activities", return_value=garmin_payload) as fetch:
        user_path, raw_path = fetch_garmin_raw_files(limit=999, timestamp="20260510", output_dir=tmp_path)

    fetch.assert_called_once()
    called_limit = (
        fetch.call_args.args[0]
        if fetch.call_args.args
        else fetch.call_args.kwargs["limit"]
    )
    assert called_limit == 999
    assert user_path == tmp_path / "garmin_user_20260510.json"
    assert raw_path == tmp_path / "garmin_raw_20260510.json"
    assert json.loads(Path(user_path).read_text(encoding="utf-8")) == {"vo2max_running": 53}
    assert json.loads(Path(raw_path).read_text(encoding="utf-8"))[0]["activity_id"] == 123


def test_strength_backfill_uses_distinct_artifacts_without_overwriting_normal_fetch(tmp_path):
    normal_payload = {
        "activities": [{"activity_id": 123, "type": "running", "date": "2026-05-10"}],
        "user_data": {"vo2max_running": 53},
    }
    strength_payload = {
        "activities": [{"activity_id": 456, "type": "strength_training", "date": "2026-05-10"}],
        "user_data": {},
    }

    with patch("src.scripts.fetch_garmin_raw._get_garmin_activities", return_value=normal_payload):
        normal_user_path, normal_raw_path = fetch_garmin_raw_files(
            timestamp="20260510",
            output_dir=tmp_path,
        )
    with patch(
        "src.scripts.fetch_garmin_raw._get_all_strength_training_activities",
        return_value=strength_payload,
    ):
        backfill_user_path, backfill_raw_path = fetch_garmin_raw_files(
            timestamp="20260510",
            output_dir=tmp_path,
            activity_type="strength_training",
            all_history=True,
        )

    assert backfill_user_path == tmp_path / "garmin_user_20260510_strength_backfill.json"
    assert backfill_raw_path == tmp_path / "garmin_raw_20260510_strength_backfill.json"
    assert json.loads(normal_user_path.read_text(encoding="utf-8")) == {"vo2max_running": 53}
    assert json.loads(normal_raw_path.read_text(encoding="utf-8"))[0]["type"] == "running"
    assert json.loads(backfill_raw_path.read_text(encoding="utf-8"))[0]["type"] == "strength_training"


@pytest.mark.parametrize("timestamp", ["20260230", "2026-05-10", "../20260510"])
def test_fetch_rejects_invalid_artifact_timestamp_before_calling_garmin(tmp_path, timestamp):
    with patch("src.scripts.fetch_garmin_raw._get_garmin_activities") as fetch:
        with pytest.raises(ValueError, match="YYYYMMDD"):
            fetch_garmin_raw_files(timestamp=timestamp, output_dir=tmp_path)

    fetch.assert_not_called()


def test_fetch_refuses_existing_artifacts_without_force_and_uses_taipei_default_date(tmp_path):
    payload = {
        "activities": [{"activity_id": 123, "type": "running", "date": "2026-05-10"}],
        "user_data": {"vo2max_running": 53},
    }
    with patch("src.scripts.fetch_garmin_raw.resolve_training_calendar_date", return_value=date(2026, 5, 10)):
        with patch("src.scripts.fetch_garmin_raw._get_garmin_activities", return_value=payload):
            _, raw_path = fetch_garmin_raw_files(output_dir=tmp_path)

    with patch("src.scripts.fetch_garmin_raw._get_garmin_activities") as fetch:
        with pytest.raises(FileExistsError, match="--force"):
            fetch_garmin_raw_files(timestamp="20260510", output_dir=tmp_path)
    fetch.assert_not_called()

    replacement = {**payload, "activities": [{"activity_id": 456, "type": "running", "date": "2026-05-10"}]}
    with patch("src.scripts.fetch_garmin_raw._get_garmin_activities", return_value=replacement):
        _, forced_raw_path = fetch_garmin_raw_files(
            timestamp="20260510",
            output_dir=tmp_path,
            force=True,
        )

    assert raw_path == tmp_path / "garmin_raw_20260510.json"
    assert forced_raw_path == raw_path
    assert json.loads(raw_path.read_text(encoding="utf-8"))[0]["activity_id"] == 456


def test_import_raw_files_delegates_to_garmin_import_service(tmp_path):
    user_path = tmp_path / "garmin_user_20260510.json"
    raw_path = tmp_path / "garmin_raw_20260510.json"
    expected = {
        "raw_import": {"activities": 1, "splits": 0, "swimming_lengths": 0},
        "user_snapshot_id": "snapshot-1",
    }

    with patch("src.scripts.fetch_garmin_raw.import_fetched_raw_artifacts", return_value=expected) as import_payload:
        results = import_raw_files(user_path=user_path, raw_path=raw_path)

    import_payload.assert_called_once_with(user_path=user_path, raw_path=raw_path)
    assert results == expected


def test_import_fetched_raw_artifacts_preserves_fetch_script_result_keys(tmp_path):
    user_path = tmp_path / "garmin_user_20260510.json"
    raw_path = tmp_path / "garmin_raw_20260510.json"
    raw_counts = {"activities": 1, "splits": 2, "swimming_lengths": 3}

    with patch(
        "src.services.garmin_import_service.import_fetched_garmin_payload",
        return_value={
            "activities": 1,
            "splits": 2,
            "swimming_lengths": 3,
            "user_snapshot": True,
            "raw_import": raw_counts,
            "user_snapshot_id": "snapshot-1",
            "user_snapshot_ids": ["snapshot-1"],
            "shadow_import": {"rows_copied": 5},
        },
    ) as import_payload:
        results = import_fetched_raw_artifacts(user_path=user_path, raw_path=raw_path)

    import_payload.assert_called_once_with(user_path=user_path, raw_path=raw_path)
    assert results == {
        "raw_import": raw_counts,
        "user_snapshot_id": "snapshot-1",
        "shadow_import": {"rows_copied": 5},
    }


def test_strength_all_cli_contract_requires_the_strength_activity_type(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["fetch_garmin_raw", "--activity-type", "strength_training", "--all", "--import-db"],
    )
    args = parse_args()

    assert args.activity_type == "strength_training"
    assert args.all is True
    assert args.limit is None


def test_strength_cli_rejects_all_and_limit_together(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["fetch_garmin_raw", "--activity-type", "strength_training", "--all", "--limit", "10"],
    )

    with pytest.raises(SystemExit):
        parse_args()
