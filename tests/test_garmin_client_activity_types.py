import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

garminconnect_stub = types.ModuleType("garminconnect")
garminconnect_stub.Garmin = object
sys.modules.setdefault("garminconnect", garminconnect_stub)

dotenv_stub = types.ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda *args, **kwargs: None
sys.modules.setdefault("dotenv", dotenv_stub)

from datetime import date
from unittest.mock import patch

from ingestion.garmin_client import TARGET_ACTIVITY_TYPES, get_garmin_activities


class GarminClientActivityTypeTests(unittest.TestCase):
    def test_default_target_types_include_running_swimming_and_cycling(self):
        self.assertEqual(
            TARGET_ACTIVITY_TYPES,
            {"running": "running", "lap_swimming": "swimming", "cycling": "cycling"},
        )

    def test_since_date_fetch_includes_same_day_and_stops_before_older_day(self):
        class FakeGarminClient:
            def __init__(self, *args, **kwargs):
                pass

            def login(self):
                pass

            def get_rhr_day(self, _date):
                return {}

            def get_user_profile(self):
                return {}

            def get_personal_record(self):
                return []

            def get_activities(self, _start, _limit):
                return [
                    {
                        "activityId": 1,
                        "activityType": {"typeKey": "running"},
                        "startTimeLocal": "2026-05-10 07:00:00",
                        "distance": 10000,
                        "duration": 3000,
                    },
                    {
                        "activityId": 2,
                        "activityType": {"typeKey": "cycling"},
                        "startTimeLocal": "2026-05-10 16:00:00",
                        "distance": 20000,
                        "duration": 3600,
                    },
                    {
                        "activityId": 3,
                        "activityType": {"typeKey": "running"},
                        "startTimeLocal": "2026-05-09 07:00:00",
                        "distance": 10000,
                        "duration": 3000,
                    },
                ]

            def get_activity_splits(self, _activity_id):
                return {"lapDTOs": []}

            def get_activity(self, _activity_id):
                return {}

            def get_activity_hr_in_timezones(self, _activity_id):
                return []

            def get_activity_power_in_timezones(self, _activity_id):
                return []

        with patch.dict(os.environ, {"GARMIN_ACCOUNT": "user@example.com", "GARMIN_PASSWORD": "secret"}), patch(
            "ingestion.garmin_client.Garmin", FakeGarminClient
        ):
            payload = get_garmin_activities(n=999, since_date=date(2026, 5, 10))

        self.assertEqual([item["activity_id"] for item in payload["activities"]], [1, 2])
        self.assertIsNone(payload["activities"][1]["average_pace"])
        self.assertEqual(payload["activities"][1]["raw_data"]["average_speed_kmh"], 20.0)

    def test_fallback_max_heart_rate_seeds_user_data_when_profile_is_missing(self):
        class FakeGarminClient:
            def __init__(self, *args, **kwargs):
                pass

            def login(self):
                pass

            def get_rhr_day(self, _date):
                return {}

            def get_user_profile(self):
                return {}

            def get_personal_record(self):
                return []

            def get_activities(self, _start, _limit):
                return [
                    {
                        "activityId": 1,
                        "activityType": {"typeKey": "running"},
                        "startTimeLocal": "2026-05-10 07:00:00",
                        "distance": 10000,
                        "duration": 3000,
                        "maxHR": 187,
                    }
                ]

            def get_activity_splits(self, _activity_id):
                return {"lapDTOs": []}

            def get_activity(self, _activity_id):
                return {}

            def get_activity_hr_in_timezones(self, _activity_id):
                return []

            def get_activity_power_in_timezones(self, _activity_id):
                return []

        with patch.dict(os.environ, {"GARMIN_ACCOUNT": "user@example.com", "GARMIN_PASSWORD": "secret"}), patch(
            "ingestion.garmin_client.Garmin", FakeGarminClient
        ):
            payload = get_garmin_activities(n=1, fallback_max_heart_rate=190)

        self.assertEqual(payload["user_data"]["max_heart_rate"], 190)

    def test_zero_activity_limit_does_not_fetch_activity_pages(self):
        class FakeGarminClient:
            def __init__(self, *args, **kwargs):
                self.get_activities_called = False

            def login(self):
                pass

            def get_rhr_day(self, _date):
                return {}

            def get_user_profile(self):
                return {}

            def get_personal_record(self):
                return []

            def get_activities(self, _start, _limit):
                self.get_activities_called = True
                raise AssertionError("get_activities should not be called when n=0")

        with patch.dict(os.environ, {"GARMIN_ACCOUNT": "user@example.com", "GARMIN_PASSWORD": "secret"}), patch(
            "ingestion.garmin_client.Garmin", FakeGarminClient
        ):
            payload = get_garmin_activities(n=0)

        self.assertEqual(payload["activities"], [])
        self.assertEqual(payload["user_data"]["available_training_days"], [])


if __name__ == "__main__":
    unittest.main()
