from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.garmin_client import (
    GarminIngestionError,
    get_all_treadmill_running_activities,
)
from src.services.garmin_import_service import (
    import_treadmill_backfill,
    treadmill_backfill_baseline_ids,
)


def _treadmill_summary(activity_id: int = 101) -> dict:
    return {
        "activityId": activity_id,
        "activityType": {"typeKey": "treadmill_running"},
        "startTimeLocal": "2026-05-10 08:00:00",
        "distance": 5000,
        "duration": 1500,
        "averageHR": 152,
    }


def test_treadmill_backfill_baseline_seeds_every_historical_activity():
    activities = [
        {"activity_id": "101", "type": "running", "date": "2026-05-10"},
        {"activity_id": 102, "type": "running", "date": "2026-08-30"},
    ]

    assert treadmill_backfill_baseline_ids(activities) == [101, 102]


def test_treadmill_backfill_imports_and_seeds_history_in_one_session(tmp_path):
    raw_path = tmp_path / "garmin_raw_20260830_treadmill_backfill.json"
    raw_path.write_text(
        json.dumps(
            [
                {"activity_id": 101, "type": "running", "date": "2026-05-10"},
                {"activity_id": 102, "type": "running", "date": "2026-08-30"},
            ]
        ),
        encoding="utf-8",
    )
    session = MagicMock()
    session_context = MagicMock()
    session_context.__enter__.return_value = session

    with (
        patch(
            "src.services.garmin_import_service.SessionLocal",
            return_value=session_context,
        ),
        patch(
            "src.services.garmin_import_service.get_or_create_default_user",
            return_value=SimpleNamespace(id="user-1"),
        ),
        patch(
            "src.services.garmin_import_service.import_artifact_bundle",
            return_value={"raw_import": {"activities": 2, "splits": 0}},
        ) as import_bundle,
        patch(
            "src.services.garmin_import_service.seed_baseline_notifications",
            return_value=2,
        ) as seed_baseline,
    ):
        result = import_treadmill_backfill(
            raw_path=raw_path,
            include_mirror_sync=False,
        )

    import_bundle.assert_called_once_with(
        session,
        "user-1",
        raw_file=raw_path,
    )
    seed_baseline.assert_called_once_with(session, [101, 102], commit=False)
    session.commit.assert_called_once_with()
    assert result["notification_baseline_seeded"] == 2
    assert result["notification_candidates_unseeded"] == 0


def test_treadmill_backfill_tolerates_missing_optional_404_endpoints():
    class Client:
        def __init__(self, *_args):
            pass

        def login(self):
            pass

        def get_activities(self, start, _limit):
            return [_treadmill_summary()] if start == 0 else []

        def get_activity(self, _activity_id):
            return {
                "activity_info": {
                    "activityTrainingLoad": 64.5,
                    "avgPower": 238,
                    "averageRunCadence": 176,
                }
            }

        def get_activity_hr_in_timezones(self, _activity_id):
            raise RuntimeError("HTTP 404 Not Found")

        def get_activity_power_in_timezones(self, _activity_id):
            raise RuntimeError("HTTP 404 Not Found")

        def get_activity_splits(self, _activity_id):
            raise RuntimeError("HTTP 404 Not Found")

    with (
        patch.dict(
            "os.environ",
            {"GARMIN_ACCOUNT": "test", "GARMIN_PASSWORD": "test"},
        ),
        patch("src.ingestion.garmin_client.Garmin", Client),
    ):
        payload = get_all_treadmill_running_activities()

    activity = payload["activities"][0]
    assert activity["type"] == "running"
    assert activity["average_pace"] == 5.0
    assert activity["splits"] == []
    assert activity["raw_data"]["training_stress_score"] == 64.5
    assert activity["raw_data"]["power_avg"] == 238
    assert activity["raw_data"]["cadence"] == 176


def test_treadmill_backfill_still_fails_closed_on_non_404_optional_error():
    class Client:
        def __init__(self, *_args):
            pass

        def login(self):
            pass

        def get_activities(self, start, _limit):
            return [_treadmill_summary()] if start == 0 else []

        def get_activity(self, _activity_id):
            return {"activity_info": {"avgPower": 238}}

        def get_activity_hr_in_timezones(self, _activity_id):
            return []

        def get_activity_power_in_timezones(self, _activity_id):
            raise RuntimeError("429 rate limited")

        def get_activity_splits(self, _activity_id):
            return {"lapDTOs": []}

    with (
        patch.dict(
            "os.environ",
            {"GARMIN_ACCOUNT": "test", "GARMIN_PASSWORD": "test"},
        ),
        patch("src.ingestion.garmin_client.Garmin", Client),
        pytest.raises(GarminIngestionError),
    ):
        get_all_treadmill_running_activities()
