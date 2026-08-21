import sys
import types
from unittest.mock import patch


garminconnect_stub = types.ModuleType("garminconnect")
garminconnect_stub.Garmin = object
sys.modules.setdefault("garminconnect", garminconnect_stub)

try:
    import dotenv  # noqa: F401
except ImportError:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules.setdefault("dotenv", dotenv_stub)

from src.ingestion.garmin_client import get_activity_details


class FailingExerciseSetsClient:
    def get_activity(self, _activity_id):
        return {"summaryDTO": {"totalSets": 3, "totalReps": 18}}

    def get_activity_exercise_sets(self, _activity_id):
        raise RuntimeError("temporary Garmin failure")


class EmptyExerciseSetsClient:
    def get_activity(self, _activity_id):
        return {"summaryDTO": {"totalSets": 3, "totalReps": 18}}

    def get_activity_exercise_sets(self, _activity_id):
        return None


def test_strength_details_mark_retry_failure_without_inventing_sets():
    with patch("src.ingestion.garmin_client.time.sleep"), patch(
        "src.ingestion.garmin_client.random.uniform", return_value=0
    ):
        details = get_activity_details(FailingExerciseSetsClient(), 123, "strength_training")

    assert details["strength_sets_fetch_failed"] is True
    assert details["strength"]["total_sets"] == 3
    assert details["strength"]["total_reps"] == 18
    assert details["strength"]["sets"] == []
    assert details["strength_raw_exercise_sets"] == []


def test_strength_details_distinguish_successful_empty_response_from_retry_failure():
    details = get_activity_details(EmptyExerciseSetsClient(), 123, "strength_training")

    assert details["strength_sets_fetch_failed"] is False
    assert details["strength"]["sets"] == []
