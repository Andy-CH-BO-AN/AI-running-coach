import json

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import func, select

from src.db.models import Activity, ActivitySplit, SwimmingLength, UserProfileSnapshot
from src.db.repositories import get_or_create_default_user
from src.services.db_importer import import_garmin_raw_file, import_garmin_user_file
from tests.db_test_utils import isolated_db_session


@pytest.fixture()
def db_session():
    yield from isolated_db_session()


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_importing_same_garmin_raw_file_twice_does_not_duplicate_activities(db_session, tmp_path):
    raw_path = tmp_path / "garmin_raw_20260510.json"
    _write_json(
        raw_path,
        [
            {
                "activity_id": 987,
                "type": "swimming",
                "date": "2026-05-10",
                "distance": 1.25,
                "duration": 30.0,
                "average_heart_rate": 145,
                "splits": [
                    {
                        "split_index": 1,
                        "distance": 0.3,
                        "duration": 7.2,
                        "pace": 2.4,
                        "lengths": [
                            {
                                "length_index": 1,
                                "distance": 25.0,
                                "duration": 35.8,
                                "swim_stroke": "BREASTSTROKE",
                                "strokes": 10,
                                "swolf": 46,
                                "avg_hr": 128,
                            }
                        ],
                    }
                ],
                "raw_data": {"avg_swolf": 47.0, "training_stress_score": 91.4},
            }
        ],
    )
    user = get_or_create_default_user(db_session)

    import_garmin_raw_file(db_session, user.id, raw_path)
    import_garmin_raw_file(db_session, user.id, raw_path)

    assert db_session.scalar(select(func.count()).select_from(Activity)) == 1
    assert db_session.scalar(select(func.count()).select_from(ActivitySplit)) == 1
    assert db_session.scalar(select(func.count()).select_from(SwimmingLength)) == 1
    activity = db_session.scalars(select(Activity)).one()
    assert activity.raw_json["raw_data"]["avg_swolf"] == 47.0


def test_import_garmin_user_file_preserves_raw_profile(db_session, tmp_path):
    user_path = tmp_path / "garmin_user_20260510.json"
    profile = {
        "max_heart_rate": 207,
        "resting_heart_rate": 47,
        "vo2max_running": 53,
        "pr_running": {"5km": "19:57 (3:59 /km)"},
    }
    _write_json(user_path, profile)
    user = get_or_create_default_user(db_session)

    import_garmin_user_file(db_session, user.id, user_path)

    snapshot = db_session.scalars(select(UserProfileSnapshot)).one()
    assert float(snapshot.vo2max_running) == 53.0
    assert snapshot.raw_profile == profile
    assert snapshot.captured_at.isoformat().startswith("2026-05-10")


def test_import_garmin_raw_file_skips_short_cycling_records(db_session, tmp_path):
    raw_path = tmp_path / "garmin_raw_20260510.json"
    _write_json(
        raw_path,
        [
            {
                "activity_id": 601,
                "type": "cycling",
                "date": "2026-05-10",
                "distance": "2.8",
                "duration": 12.0,
            },
            {
                "activity_id": 602,
                "type": "cycling",
                "date": "2026-05-11",
                "distance": 3.01,
                "duration": 12.0,
            },
        ],
    )
    user = get_or_create_default_user(db_session)

    counts = import_garmin_raw_file(db_session, user.id, raw_path)

    assert counts["activities"] == 1
    assert counts["skipped_short_cycling"] == 1
    activity = db_session.scalars(select(Activity)).one()
    assert activity.garmin_activity_id == 602
