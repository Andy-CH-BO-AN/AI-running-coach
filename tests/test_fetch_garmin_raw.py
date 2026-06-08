import json
from pathlib import Path
from unittest.mock import patch

from src.scripts.fetch_garmin_raw import fetch_garmin_raw_files, import_raw_files
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

    fetch.assert_called_once_with(999, progress=True)
    assert user_path == tmp_path / "garmin_user_20260510.json"
    assert raw_path == tmp_path / "garmin_raw_20260510.json"
    assert json.loads(Path(user_path).read_text(encoding="utf-8")) == {"vo2max_running": 53}
    assert json.loads(Path(raw_path).read_text(encoding="utf-8"))[0]["activity_id"] == 123


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
