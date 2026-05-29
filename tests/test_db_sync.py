import pytest

from src.db import sync


def test_sync_database_targets_rejects_same_source_and_target():
    with pytest.raises(ValueError, match="must be different"):
        sync.sync_database_targets("local", "local")


def test_compare_database_targets_reports_snapshot_mismatch(monkeypatch):
    snapshots = {
        "local": {
            "target": "local",
            "tables": [
                {
                    "table": "activities",
                    "row_count": 10,
                    "content_digest": "digest-local",
                    "marker_column": "updated_at",
                    "marker_value": "2026-05-29T12:00:00+00:00",
                }
            ],
        },
        "cloud": {
            "target": "cloud",
            "tables": [
                {
                    "table": "activities",
                    "row_count": 10,
                    "content_digest": "digest-cloud",
                    "marker_column": "updated_at",
                    "marker_value": "2026-05-29T12:00:00+00:00",
                }
            ],
        },
    }

    monkeypatch.setattr(sync, "collect_database_snapshot", lambda target, table_names=None: snapshots[target])

    result = sync.compare_database_targets("local", "cloud")

    assert result["ok"] is False
    assert result["mismatches"][0]["table"] == "activities"


def test_find_logical_key_conflicts_detects_same_business_key_with_different_primary_keys():
    conflicts = sync._find_logical_key_conflicts(
        source_rows=[
            {"id": "local-user-id", "external_source": "local", "external_user_id": "default"},
        ],
        target_rows=[
            {"id": "cloud-user-id", "external_source": "local", "external_user_id": "default"},
        ],
        logical_key_columns=("external_source", "external_user_id"),
        primary_key_columns=("id",),
    )

    assert conflicts == [
        {
            "logical_key": ("local", "default"),
            "source_primary_key": ("local-user-id",),
            "target_primary_key": ("cloud-user-id",),
        }
    ]
