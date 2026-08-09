import unittest

from src.preprocessing.data_processor import (
    calculate_cycling_efficiency,
    calculate_hrr,
    calculate_running_efficiency,
    calculate_swimming_efficiency,
    classify_runner_type,
)


class QADataProcessorTests(unittest.TestCase):
    def test_running_efficiency_keeps_raw_metrics_and_removes_grade_fields(self):
        result = calculate_running_efficiency(7.5, 250)

        self.assertIsNotNone(result)
        self.assertEqual(result["vertical_oscillation"], 7.5)
        self.assertEqual(result["ground_contact_time"], 250.0)
        self.assertNotIn("oscillation_grade", result)
        self.assertNotIn("contact_grade", result)

    def test_running_efficiency_accepts_partial_values(self):
        oscillation_only = calculate_running_efficiency(10, None)
        contact_only = calculate_running_efficiency(None, 250)

        self.assertEqual(oscillation_only, {"vertical_oscillation": 10.0})
        self.assertEqual(contact_only, {"ground_contact_time": 250.0})

    def test_cycling_efficiency_returns_power_ratio_only(self):
        result = calculate_cycling_efficiency(200, 500)

        self.assertEqual(result, {"power_ratio": 2.5})
        self.assertNotIn("power_consistency", result)

    def test_swimming_efficiency_accepts_fast_swimmers_and_rejects_invalid_values(self):
        self.assertEqual(calculate_swimming_efficiency(45), {"avg_swolf": 45.0})
        self.assertEqual(calculate_swimming_efficiency(49), {"avg_swolf": 49.0})
        self.assertIsNone(calculate_swimming_efficiency(250))
        self.assertIsNone(calculate_swimming_efficiency(-10))

    def test_regression_helpers_still_work(self):
        self.assertEqual(classify_runner_type(185), "frequency_runner")
        self.assertEqual(classify_runner_type(170), "power_runner")
        self.assertIsNone(classify_runner_type(None))
        self.assertEqual(calculate_hrr(60, 200), 140.0)
        self.assertIsNone(calculate_hrr(200, 100))


if __name__ == "__main__":
    unittest.main()
