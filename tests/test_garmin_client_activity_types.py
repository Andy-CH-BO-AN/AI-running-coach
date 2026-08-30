import os
import sys
import types
import unittest

garminconnect_stub = types.ModuleType("garminconnect")
garminconnect_stub.Garmin = object
sys.modules.setdefault("garminconnect", garminconnect_stub)

try:
    import dotenv  # noqa: F401
except ImportError:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules.setdefault("dotenv", dotenv_stub)

from datetime import date
from unittest.mock import patch

from src.ingestion.garmin_client import (
    GarminIngestionError,
    TARGET_ACTIVITY_TYPES,
    format_garmin_value,
    get_all_treadmill_running_activities,
    get_activity_splits,
    get_garmin_activities,
    get_user_biometric_data,
)
from src.preprocessing.activity_window import normalize_activity_window
from src.preprocessing.coach_context import build_deterministic_coach_context


class GarminClientActivityTypeTests(unittest.TestCase):
    def test_format_garmin_value_formats_marathon_with_per_km_pace(self):
        formatted_value, pace = format_garmin_value(3 * 3600 + 30 * 60, 6)

        self.assertEqual(formatted_value, "210:00")
        self.assertEqual(pace, "4:58 /km")

    def test_get_user_biometric_data_leaves_marathon_pr_absent_when_not_provided(self):
        class FakeGarminClient:
            def get_rhr_day(self, _date):
                return {}

            def get_user_profile(self):
                return {}

            def get_personal_record(self):
                return [{"typeId": 3, "value": 1200}]

        biometrics = get_user_biometric_data(FakeGarminClient())

        self.assertEqual(biometrics["pr_running"]["5km"], "20:00 (4:00 /km)")
        self.assertNotIn("marathon", biometrics["pr_running"])

    def test_default_target_types_include_strength_training(self):
        self.assertEqual(
            TARGET_ACTIVITY_TYPES,
            {
                "running": "running",
                "treadmill_running": "running",
                "lap_swimming": "swimming",
                "cycling": "cycling",
                "strength_training": "strength_training",
            },
        )

    def test_treadmill_running_summary_uses_canonical_running_details_and_splits(self):
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
                return [{
                    "activityId": 101,
                    "activityType": {"typeKey": "treadmill_running"},
                    "startTimeLocal": "2026-05-10 08:00:00",
                    "distance": 5000,
                    "duration": 1500,
                    "averageHR": 152,
                }]

            def get_activity(self, _activity_id):
                return {
                    "activity_info": {
                        "activityTrainingLoad": 64.5,
                        "averageRunningCadenceInStepsPerMinute": 176,
                        "maxDoubleCadence": 190,
                        "avgStrideLength": 125,
                        "avgPower": 238,
                        "maxPower": 402,
                        "avgVerticalOscillation": 7.8,
                        "avgGroundContactTime": 214,
                        "avgVerticalRatio": 6.2,
                    }
                }

            def get_activity_hr_in_timezones(self, _activity_id):
                return []

            def get_activity_power_in_timezones(self, _activity_id):
                return []

            def get_activity_splits(self, _activity_id):
                return {
                    "lapDTOs": [{
                        "distance": 1000,
                        "duration": 300,
                        "averageHR": 154,
                        "averageRunCadence": 178,
                        "maxRunCadence": 192,
                        "strideLength": 126,
                        "groundContactTime": 212,
                        "verticalOscillation": 7.7,
                        "verticalRatio": 6.1,
                        "averagePower": 240,
                        "maxPower": 410,
                    }]
                }

        with patch.dict(
            os.environ,
            {"GARMIN_ACCOUNT": "user@example.com", "GARMIN_PASSWORD": "secret"},
        ), patch("src.ingestion.garmin_client.Garmin", FakeGarminClient):
            payload = get_garmin_activities(n=1)

        activity = payload["activities"][0]
        self.assertEqual(activity["type"], "running")
        self.assertEqual(activity["average_pace"], 5.0)
        self.assertEqual(activity["raw_data"]["cadence"], 176)
        self.assertEqual(activity["raw_data"]["stride_length"], 125)
        self.assertEqual(activity["raw_data"]["power_avg"], 238)
        self.assertEqual(activity["raw_data"]["power_max"], 402)
        self.assertEqual(activity["raw_data"]["vertical_oscillation"], 7.8)
        self.assertEqual(activity["raw_data"]["ground_contact_time"], 214)
        self.assertEqual(activity["raw_data"]["vertical_ratio"], 6.2)
        self.assertEqual(activity["splits"][0]["pace"], 5.0)
        self.assertEqual(activity["splits"][0]["avg_cadence"], 178)
        self.assertEqual(activity["splits"][0]["stride_length"], 126)
        self.assertEqual(activity["splits"][0]["power_avg"], 240)
        self.assertEqual(activity["splits"][0]["power_max"], 410)

    def test_treadmill_running_and_normal_running_share_weekly_running_context(self):
        treadmill = {
            "activity_id": 101,
            "type": "running",
            "date": "2026-05-10",
            "distance": 5.0,
            "duration": 25.0,
            "average_pace": 5.0,
            "average_heart_rate": 152,
            "splits": [{
                "split_index": 1,
                "distance": 1.0,
                "duration": 5.0,
                "pace": 5.0,
                "avg_cadence": 178,
                "stride_length": 126,
                "ground_contact_time": 212,
                "vertical_oscillation": 7.7,
                "vertical_ratio": 6.1,
                "power_avg": 240,
                "power_max": 410,
            }],
            "raw_data": {
                "training_stress_score": 64.5,
                "cadence": 176,
                "stride_length": 125,
                "power_avg": 238,
                "power_max": 402,
                "vertical_oscillation": 7.8,
                "ground_contact_time": 214,
                "vertical_ratio": 6.2,
            },
        }
        outdoor = {
            "activity_id": 102,
            "type": "running",
            "date": "2026-05-10",
            "distance": 10.0,
            "duration": 52.0,
            "average_pace": 5.2,
            "raw_data": {"training_stress_score": 90},
            "splits": [],
        }

        context = build_deterministic_coach_context(
            normalize_activity_window([treadmill, outdoor]),
            today="2026-05-10",
        )
        current_week = context["weekly_analysis"][0]

        self.assertEqual(current_week["derived_total_distance_km"], 15.0)
        self.assertEqual(current_week["derived_training_load"], 154.5)
        self.assertEqual(current_week["session_counts"]["total"], 2)
        self.assertEqual(
            current_week["session_counts"]["by_source_activity_type"],
            {"running": 2},
        )
        self.assertEqual(context["running_mechanics"]["cadence_avg"]["value"], 178.0)

    def test_all_treadmill_running_backfill_scans_all_pages_and_returns_running(self):
        class FakeGarminClient:
            starts = []

            def __init__(self, *args, **kwargs):
                FakeGarminClient.starts = []

            def login(self):
                pass

            def get_activities(self, start, _limit):
                FakeGarminClient.starts.append(start)
                if start == 0:
                    return [{
                        "activityId": "103",
                        "activityType": {"typeKey": "treadmill_running"},
                        "startTimeLocal": "2026-05-09 08:00:00",
                        "distance": 3000,
                        "duration": 900,
                    }]
                return []

            def get_activity(self, _activity_id):
                return {"activity_info": {"avgPower": 200}}

            def get_activity_hr_in_timezones(self, _activity_id):
                return []

            def get_activity_power_in_timezones(self, _activity_id):
                return []

            def get_activity_splits(self, _activity_id):
                return {"lapDTOs": []}

        with patch.dict(
            os.environ,
            {"GARMIN_ACCOUNT": "user@example.com", "GARMIN_PASSWORD": "secret"},
        ), patch("src.ingestion.garmin_client.Garmin", FakeGarminClient):
            payload = get_all_treadmill_running_activities()

        self.assertEqual(FakeGarminClient.starts, [0, 50])
        self.assertEqual(payload["activities"][0]["activity_id"], 103)
        self.assertEqual(payload["activities"][0]["type"], "running")
        self.assertEqual(payload["activities"][0]["average_pace"], 5.0)
        self.assertEqual(payload["activities"][0]["raw_data"]["power_avg"], 200)

    def test_all_treadmill_running_backfill_fails_before_import_on_detail_error(self):
        class FakeGarminClient:
            def __init__(self, *args, **kwargs):
                pass

            def login(self):
                pass

            def get_activities(self, _start, _limit):
                return [{
                    "activityId": 104,
                    "activityType": {"typeKey": "treadmill_running"},
                    "startTimeLocal": "2026-05-08 08:00:00",
                    "distance": 3000,
                    "duration": 900,
                }]

            def get_activity(self, _activity_id):
                raise RuntimeError("429 rate limited")

        with patch.dict(
            os.environ,
            {"GARMIN_ACCOUNT": "user@example.com", "GARMIN_PASSWORD": "secret"},
        ), patch("src.ingestion.garmin_client.Garmin", FakeGarminClient):
            with self.assertRaises(GarminIngestionError):
                get_all_treadmill_running_activities()

    def test_swimming_splits_preserve_order_and_only_mark_strict_rest(self):
        class FakeGarminClient:
            def get_activity_splits(self, _activity_id):
                return {
                    "lapDTOs": [
                        {
                            "distance": 100,
                            "duration": 120,
                            "elapsedDuration": 121,
                            "movingDuration": 119,
                            "numberOfActiveLengths": 2,
                            "swimStroke": "FREESTYLE",
                        },
                        {
                            "distance": 0,
                            "duration": 30,
                            "elapsedDuration": 30,
                            "movingDuration": 0,
                            "numberOfActiveLengths": 0,
                        },
                        {
                            "distance": 0,
                            "duration": 15,
                            "elapsedDuration": 15,
                            "movingDuration": 0,
                            # Missing active-length evidence: do not guess rest.
                        },
                        {
                            "distance": 25,
                            "duration": 0.5,
                            "elapsedDuration": 0.5,
                            "movingDuration": 0.5,
                            "numberOfActiveLengths": 1,
                            "swimStroke": "BREASTSTROKE",
                        },
                    ]
                }

        splits = get_activity_splits(FakeGarminClient(), 123, "swimming")

        self.assertEqual([split["split_index"] for split in splits], [1, 2, 3, 4])
        self.assertEqual([split["interval_type"] for split in splits], [None, "rest", None, None])
        self.assertAlmostEqual(splits[0]["elapsed_duration"], 121 / 60)
        self.assertAlmostEqual(splits[0]["moving_duration"], 119 / 60)
        self.assertEqual(splits[0]["active_lengths"], 2)
        self.assertEqual(splits[0]["swim_stroke"], "FREESTYLE")
        self.assertEqual(splits[1]["distance"], 0)
        self.assertEqual(splits[1]["duration"], 0.5)

    def test_non_swimming_splits_keep_existing_distance_duration_filter(self):
        class FakeGarminClient:
            def get_activity_splits(self, _activity_id):
                return {
                    "lapDTOs": [
                        {"distance": 0, "duration": 30},
                        {"distance": 100, "duration": 0.5},
                        {"distance": 100, "duration": 60},
                    ]
                }

        for activity_type in ("running", "cycling"):
            with self.subTest(activity_type=activity_type):
                splits = get_activity_splits(FakeGarminClient(), 123, activity_type)
                self.assertEqual([split["split_index"] for split in splits], [3])

    def test_swimming_activity_preserves_explicit_duration_fields_only_for_swimming(self):
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
                common_times = {
                    "elapsedDuration": 1816.95,
                    "movingDuration": 1782.561,
                    "restDuration": 26.547,
                }
                return [
                    {
                        "activityId": 2,
                        "activityType": {"typeKey": "lap_swimming"},
                        "startTimeLocal": "2026-05-10 08:00:00",
                        "distance": 1250,
                        "duration": 1809.107,
                        **common_times,
                    },
                    {
                        "activityId": 1,
                        "activityType": {"typeKey": "running"},
                        "startTimeLocal": "2026-05-10 07:00:00",
                        "distance": 5000,
                        "duration": 1500,
                        **common_times,
                    },
                ]

            def get_activity_splits(self, _activity_id):
                return {"lapDTOs": []}

            def get_activity(self, _activity_id):
                return {}

        with patch.dict(os.environ, {"GARMIN_ACCOUNT": "user@example.com", "GARMIN_PASSWORD": "secret"}), patch(
            "src.ingestion.garmin_client.Garmin", FakeGarminClient
        ):
            payload = get_garmin_activities(n=2)

        activities = {item["type"]: item for item in payload["activities"]}
        swimming = activities["swimming"]
        self.assertAlmostEqual(swimming["elapsed_duration"], 1816.95 / 60)
        self.assertAlmostEqual(swimming["moving_duration"], 1782.561 / 60)
        self.assertAlmostEqual(swimming["rest_duration"], 26.547 / 60)
        self.assertNotIn("elapsed_duration", activities["running"])
        self.assertNotIn("moving_duration", activities["running"])
        self.assertNotIn("rest_duration", activities["running"])

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
            "src.ingestion.garmin_client.Garmin", FakeGarminClient
        ):
            payload = get_garmin_activities(n=999, since_date=date(2026, 5, 10))

        self.assertEqual([item["activity_id"] for item in payload["activities"]], [2, 1])
        self.assertIsNone(payload["activities"][0]["average_pace"])
        self.assertEqual(payload["activities"][0]["raw_data"]["average_speed_kmh"], 20.0)

    def test_short_cycling_activities_are_skipped_before_detail_fetch(self):
        class FakeGarminClient:
            detail_calls = []

            def __init__(self, *args, **kwargs):
                FakeGarminClient.detail_calls = []

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
                        "activityId": 10,
                        "activityType": {"typeKey": "cycling"},
                        "startTimeLocal": "2026-05-10 08:00:00",
                        "distance": 3000,
                        "duration": 600,
                    },
                    {
                        "activityId": 11,
                        "activityType": {"typeKey": "cycling"},
                        "startTimeLocal": "2026-05-10 09:00:00",
                        "distance": 3001,
                        "duration": 600,
                    },
                ]

            def get_activity_splits(self, activity_id):
                self.detail_calls.append(("splits", activity_id))
                return {"lapDTOs": []}

            def get_activity(self, activity_id):
                self.detail_calls.append(("activity", activity_id))
                return {}

            def get_activity_hr_in_timezones(self, activity_id):
                self.detail_calls.append(("hr", activity_id))
                return []

            def get_activity_power_in_timezones(self, activity_id):
                self.detail_calls.append(("power", activity_id))
                return []

        with patch.dict(os.environ, {"GARMIN_ACCOUNT": "user@example.com", "GARMIN_PASSWORD": "secret"}), patch(
            "src.ingestion.garmin_client.Garmin", FakeGarminClient
        ):
            payload = get_garmin_activities(n=2)

        self.assertEqual([item["activity_id"] for item in payload["activities"]], [11])
        self.assertEqual(payload["activities"][0]["distance"], 3.001)
        detail_activity_ids = [
            activity_id for _, activity_id in FakeGarminClient.detail_calls
        ]
        self.assertNotIn(10, detail_activity_ids)
        self.assertIn(11, detail_activity_ids)

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
            "src.ingestion.garmin_client.Garmin", FakeGarminClient
        ):
            payload = get_garmin_activities(n=1, fallback_max_heart_rate=190)

        self.assertEqual(payload["user_data"]["max_heart_rate"], 190)

    def test_activity_limit_selects_newest_records_from_unsorted_api_page(self):
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
                        "activityId": activity_id,
                        "activityType": {"typeKey": "running"},
                        "startTimeLocal": f"2026-05-10 {activity_id:02d}:00:00",
                        "distance": 10000,
                        "duration": 3000,
                    }
                    for activity_id in [1, 12, 3, 11, 4, 10, 5, 9, 6, 8, 7, 2]
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
            "src.ingestion.garmin_client.Garmin", FakeGarminClient
        ):
            payload = get_garmin_activities(n=10)

        assert [item["activity_id"] for item in payload["activities"]] == list(range(12, 2, -1))
        assert all(item["started_at"] for item in payload["activities"])

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
            "src.ingestion.garmin_client.Garmin", FakeGarminClient
        ):
            payload = get_garmin_activities(n=0)

        self.assertEqual(payload["activities"], [])
        self.assertEqual(payload["user_data"]["available_training_days"], [])


if __name__ == "__main__":
    unittest.main()
