import json
from pathlib import Path
from unittest.mock import patch

from src.scripts.fetch_garmin_raw import fetch_garmin_raw_files


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
