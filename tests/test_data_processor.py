import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from preprocessing.data_processor import (
    calculate_cycling_efficiency,
    calculate_swimming_efficiency,
    format_pace,
    preprocess_data,
)


class DataProcessorTests(unittest.TestCase):
    def test_preprocess_running_activity_builds_advanced_metrics_and_efficiency(self):
        raw_activities = [
            {
                "activity_id": 1,
                "type": "running",
                "date": "2026-05-10",
                "distance": 10.0,
                "duration": 50.0,
                "average_heart_rate": 150,
                "max_heart_rate": 175,
                "splits": [{"split_index": 1}],
                "raw_data": {
                    "cadence": 182,
                    "max_cadence": 192,
                    "vertical_oscillation": 7.8,
                    "ground_contact_time": 230.4,
                    "stride_length": 1.2,
                    "elevation_gain": 50,
                    "elevation_loss": 48,
                    "power_avg": 250,
                    "power_max": 410,
                    "aerobic_training_effect": 3.2,
                    "anaerobic_training_effect": 0.8,
                    "training_stress_score": 78.5,
                    "hr_zone_1": 10,
                    "power_zone_5": 60,
                },
            }
        ]

        processed = preprocess_data(raw_activities)

        self.assertEqual(len(processed), 1)
        activity = processed[0]
        self.assertEqual(activity["performance_formatted"], "5:00 /km")
        self.assertEqual(activity["runner_type"], "frequency_runner")
        self.assertEqual(activity["running_efficiency"]["vertical_oscillation"], 7.8)
        self.assertEqual(activity["advanced_metrics"]["training_load"], 78.5)
        self.assertEqual(activity["advanced_metrics"]["hr_zones"]["hr_zone_1"], 10)
        self.assertEqual(activity["advanced_metrics"]["power_zones"]["power_zone_5"], 60)

    def test_preprocess_swimming_activity_preserves_zone_maps_and_swolf_efficiency(self):
        raw_activities = [
            {
                "activity_id": 2,
                "type": "swimming",
                "date": "2026-05-10",
                "distance": 2.0,
                "duration": 40.0,
                "raw_data": {
                    "total_strokes": 400,
                    "avg_swolf": 45,
                    "pool_length": 25,
                    "avg_stroke_type": "freestyle",
                    "hr_zone_2": 120,
                },
            }
        ]

        processed = preprocess_data(raw_activities)

        self.assertEqual(len(processed), 1)
        activity = processed[0]
        self.assertEqual(activity["performance_formatted"], "2:00 /100m")
        self.assertEqual(activity["swimming_efficiency"]["avg_swolf"], 45.0)
        self.assertEqual(activity["advanced_metrics"]["stroke_style"], "freestyle")
        self.assertEqual(activity["advanced_metrics"]["hr_zones"]["hr_zone_2"], 120)

    def test_preprocess_filters_short_cycling_activities(self):
        raw_activities = [
            {"activity_id": 3, "type": "cycling", "distance": 0.5, "duration": 2.0, "raw_data": {}},
            {
                "activity_id": 4,
                "type": "cycling",
                "distance": 20.0,
                "duration": 40.0,
                "raw_data": {"power_avg": 200, "power_max": 320, "cadence": 88},
            },
        ]

        processed = preprocess_data(raw_activities)

        self.assertEqual(len(processed), 1)
        activity = processed[0]
        self.assertEqual(activity["activity_id"], 4)
        self.assertEqual(activity["performance_formatted"], "30.0 km/h")
        self.assertEqual(activity["cycling_efficiency"]["power_ratio"], 1.6)

    def test_format_pace_for_cycling_and_missing_values(self):
        self.assertEqual(format_pace(31.2, "cycling"), "31.2 km/h")
        self.assertEqual(format_pace(None, "running"), "N/A")

    def test_preprocess_formats_running_split_paces_for_output(self):
        raw_activities = [
            {
                "activity_id": 5,
                "type": "running",
                "date": "2026-05-10",
                "distance": 1.0,
                "duration": 5.0,
                "splits": [{"split_index": 1, "distance": 1.0, "duration": 4.59, "pace": 4.59}],
                "raw_data": {},
            }
        ]

        processed = preprocess_data(raw_activities)

        self.assertEqual(processed[0]["splits"][0]["pace"], "4:35 /km")
        self.assertEqual(raw_activities[0]["splits"][0]["pace"], 4.59)

    def test_preprocess_formats_swimming_split_paces_per_100m(self):
        raw_activities = [
            {
                "activity_id": 6,
                "type": "swimming",
                "date": "2026-05-10",
                "distance": 0.1,
                "duration": 2.74,
                "splits": [{"split_index": 1, "distance": 0.1, "duration": 2.74, "pace": 2.74}],
                "raw_data": {},
            }
        ]

        processed = preprocess_data(raw_activities)

        self.assertEqual(processed[0]["splits"][0]["pace"], "2:44 /100m")

    def test_preprocess_leaves_cycling_split_speed_numeric(self):
        raw_activities = [
            {
                "activity_id": 7,
                "type": "cycling",
                "date": "2026-05-10",
                "distance": 10.0,
                "duration": 30.0,
                "splits": [{"split_index": 1, "distance": 10.0, "duration": 30.0, "pace": None, "speed_kmh": 20.0}],
                "raw_data": {},
            }
        ]

        processed = preprocess_data(raw_activities)

        self.assertIsNone(processed[0]["splits"][0]["pace"])
        self.assertEqual(processed[0]["splits"][0]["speed_kmh"], 20.0)

    def test_efficiency_validators_reject_invalid_input(self):
        self.assertIsNone(calculate_cycling_efficiency(0, 300))
        self.assertIsNone(calculate_swimming_efficiency(250))


if __name__ == "__main__":
    unittest.main()
