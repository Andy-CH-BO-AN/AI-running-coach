import os
import sys
import unittest
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Stub external dependencies so the unit tests only exercise parsing logic.
garminconnect_stub = types.ModuleType('garminconnect')
garminconnect_stub.Garmin = object
sys.modules.setdefault('garminconnect', garminconnect_stub)

dotenv_stub = types.ModuleType('dotenv')
dotenv_stub.load_dotenv = lambda *args, **kwargs: None
sys.modules.setdefault('dotenv', dotenv_stub)

from ingestion.garmin_client import get_activity_details


class FakeGarminClient:
    def __init__(self, payload):
        self.payload = payload

    def get_activity(self, activity_id):
        return self.payload


class GarminClientDetailTests(unittest.TestCase):
    def test_running_activity_extracts_zones_from_nested_split_summaries(self):
        payload = {
            'summaryDTO': {
                'activity_info': {
                    'activityTrainingLoad': 138.8670196533203,
                    'minTemperature': 24.0,
                    'maxTemperature': 26.0,
                    'elevationGain': 4.0,
                    'elevationLoss': 4.0,
                    'averageRunningCadenceInStepsPerMinute': 78.25,
                    'maxDoubleCadence': 231.0,
                    'avgStrideLength': 147.99,
                    'avgPower': 169.0,
                    'maxPower': 625.0,
                    'avgVerticalOscillation': 8.25,
                    'avgGroundContactTime': 184.7,
                    'avgVerticalRatio': 5.8,
                    'splitSummaries': [
                        {
                            'hrTimeInZone_1': 273.906,
                            'hrTimeInZone_2': 243.777,
                            'hrTimeInZone_3': 33.996,
                            'hrTimeInZone_4': 0.0,
                            'hrTimeInZone_5': 0.0,
                            'powerTimeInZone_1': 12.075,
                            'powerTimeInZone_2': 10.999,
                            'powerTimeInZone_3': 6.002,
                            'powerTimeInZone_4': 5.998,
                            'powerTimeInZone_5': 191.564,
                        }
                    ],
                }
            }
        }

        details = get_activity_details(FakeGarminClient(payload), 123, 'running')

        self.assertEqual(details['hr_zone_1'], 273.906)
        self.assertEqual(details['hrTimeInZone_1'], 273.906)
        self.assertEqual(details['power_zone_5'], 191.564)
        self.assertEqual(details['powerTimeInZone_5'], 191.564)
        self.assertEqual(details['cadence'], 78.25)
        self.assertEqual(details['max_cadence'], 231.0)

    def test_swimming_activity_extracts_hr_zones_from_activity_info(self):
        payload = {
            'activity_info': {
                'activityTrainingLoad': 91.48,
                'minTemperature': None,
                'maxTemperature': None,
                'elevationGain': None,
                'elevationLoss': None,
                'averageSwimCadenceInStrokesPerMinute': 20.0,
                'averageSWOLF': 47.0,
                'totalNumberOfStrokes': 583,
                'hrTimeInZone_1': 925.493,
                'hrTimeInZone_2': 584.993,
                'hrTimeInZone_3': 0.0,
                'hrTimeInZone_4': 0.0,
                'hrTimeInZone_5': 0.0,
            }
        }

        details = get_activity_details(FakeGarminClient(payload), 123, 'swimming')

        self.assertEqual(details['hr_zone_1'], 925.493)
        self.assertEqual(details['hrTimeInZone_2'], 584.993)
        self.assertEqual(details['avg_swolf'], 47.0)
        self.assertEqual(details['total_strokes'], 583)
        self.assertEqual(details['avg_stroke_cadence'], 20.0)

    def test_cycling_activity_extracts_power_and_hr_zones(self):
        payload = {
            'activity_info': {
                'activityTrainingLoad': 1.21,
                'minTemperature': 24.0,
                'maxTemperature': 25.0,
                'elevationGain': 5.0,
                'elevationLoss': 2.0,
                'averageBikeCadence': 88.0,
                'avgPower': 165.0,
                'maxPower': 240.0,
                'hrTimeInZone_1': 0.0,
                'hrTimeInZone_2': 0.0,
                'hrTimeInZone_3': 12.5,
                'hrTimeInZone_4': 0.0,
                'hrTimeInZone_5': 0.0,
                'powerTimeInZone_1': 10.0,
                'powerTimeInZone_2': 11.0,
                'powerTimeInZone_3': 12.0,
                'powerTimeInZone_4': 13.0,
                'powerTimeInZone_5': 14.0,
            }
        }

        details = get_activity_details(FakeGarminClient(payload), 123, 'cycling')

        self.assertEqual(details['hr_zone_3'], 12.5)
        self.assertEqual(details['power_zone_4'], 13.0)
        self.assertEqual(details['powerTimeInZone_5'], 14.0)
        self.assertEqual(details['cadence'], 88.0)
        self.assertEqual(details['power_avg'], 165.0)


if __name__ == '__main__':
    unittest.main()
