from unittest.mock import Mock

from src.pipeline.activity_payloads import ActivityPayloadProvider


def test_fetch_without_database_limits_payload_to_latest_activity_window():
    provider = ActivityPayloadProvider(
        garmin_fetcher=Mock(
            return_value={
                "activities": [
                    {"activity_id": 2, "date": "2026-05-11", "type": "running"},
                    {"activity_id": 1, "date": "2026-05-10", "type": "running"},
                    {"activity_id": 3, "date": "2026-05-12", "type": "running"},
                ],
                "user_data": {},
            }
        ),
        raw_artifact_persister=Mock(),
    )

    activities, _ = provider.fetch_without_database(
        activity_limit=2,
        timestamp="20260512",
    )

    assert [activity["activity_id"] for activity in activities] == [3, 2]
