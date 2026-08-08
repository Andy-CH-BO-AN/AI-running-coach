import json
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from src.preprocessing.activity_window import (
    ActivityWindow,
    ActivityWindowError,
    canonical_activity_id,
    normalize_activity_window,
)
from src.preprocessing.data_processor import preprocess_data


def test_normalize_activity_window_owns_context_facts_and_preserves_order():
    raw_activities = [
        {
            "activity_id": 123,
            "type": "running",
            "date": "2026-08-01",
            "distance": 2,
            "average_heart_rate": 150,
            "splits": [
                {
                    "split_index": 1,
                    "distance": 1,
                    "duration": 5,
                    "pace": 5,
                    "avg_cadence": 176,
                    "stride_length": 112,
                    "ground_contact_time": 240,
                    "vertical_oscillation": 8,
                    "temperature": 26,
                },
                {
                    "split_index": 2,
                    "distance": 1,
                    "duration": 4,
                    "pace": 4,
                    "temperature": 28,
                },
            ],
            "raw_data": {
                "training_stress_score": 0,
                "aerobic_training_effect": 3.1,
                "anaerobic_training_effect": 0.4,
                "hr_zone_1": 0,
                "hr_zone_2": 540,
                "power_zone_5": 12,
                "temperature": 30,
                "humidity": 0,
                "cadence": 176,
                "max_cadence": 190,
                "stride_length": 112,
                "ground_contact_time": 240,
                "vertical_oscillation": 8,
                "elevation_gain": 20,
                "elevation_loss": 18,
                "power_avg": 250,
                "power_max": 400,
            },
        },
        {
            "activity_id": "swim-1",
            "type": "lap_swimming",
            "date": "2026-08-02",
            "distance": 0.1,
            "duration": 3,
            "elapsed_duration": 3.5,
            "moving_duration": 3,
            "splits": [
                {
                    "split_index": 1,
                    "distance": 0.1,
                    "duration": 3,
                    "elapsed_duration": 3,
                    "pace": 3,
                },
                {
                    "split_index": 2,
                    "interval_type": "rest",
                    "distance": 0,
                    "duration": 0,
                    "elapsed_duration": 0.5,
                    "moving_duration": 0,
                },
            ],
            "raw_data": {
                "avg_swolf": 45,
                "total_strokes": 80,
                "avg_stroke_cadence": 22,
                "pool_length": 25,
                "avg_stroke_type": "freestyle",
                "hr_zone_2": 180,
                "training_stress_score": 10,
            },
        },
        {
            "activity_id": 999,
            "type": "cycling",
            "distance": 3,
            "duration": 10,
        },
    ]

    window = normalize_activity_window(raw_activities)

    assert [activity.activity_id for activity in window.activities] == [123, "swim-1"]
    running, swimming = window.activities
    assert running.canonical_id == "number:123"
    assert running.activity_type == "running"
    assert running.duration_min == 9
    assert running.performance_value == 4.5
    assert running.performance_formatted == "4:30 /km"
    assert running.processed_performance_value is None
    assert running.processed_performance_formatted == "N/A"
    assert running.training_load == 0
    assert running.hr_zone_seconds[1] == 0
    assert running.hr_zone_seconds[2] == 540
    assert running.power_zone_seconds[5] == 12
    assert running.temperature_c == 28
    assert running.humidity_pct == 0
    assert running.stride_length_m == 1.12
    assert running.segments[0].pace_value == 5
    assert running.segments[0].pace_formatted == "5:00 /km"
    assert running.segments[0].stride_length_m == 1.12

    assert swimming.activity_type == "lap_swimming"
    assert swimming.elapsed_duration_min == 3.5
    assert swimming.moving_duration_min == 3
    assert swimming.rest_duration_min == 0.5
    assert swimming.performance_value == 3
    assert swimming.performance_formatted == "3:00 /100m"
    assert swimming.processed_performance_value is None
    assert swimming.processed_performance_formatted == "N/A"
    assert swimming.training_load == 10
    assert swimming.avg_swolf == 45
    assert swimming.avg_stroke_cadence_spm == 22
    assert swimming.hr_zone_seconds[2] == 180
    assert swimming.segments[1].moving_duration_min == 0


def test_processed_projection_is_fresh_json_safe_and_keeps_facade_contract():
    raw_activities = [
        {
            "activity_id": "run_001",
            "type": "running",
            "date": "2026-08-01",
            "distance": 1,
            "duration": 5,
            "splits": [
                {
                    "split_index": 1,
                    "distance": 1,
                    "duration": 5,
                    "pace": 5,
                    "lengths": [{"length_index": 1, "distance": 25}],
                }
            ],
            "raw_data": {"cadence": 180, "hr_zone_5": 0},
        }
    ]
    original = deepcopy(raw_activities)
    window = normalize_activity_window(raw_activities)

    first = window.processed_data()
    first[0]["splits"][0]["lengths"][0]["distance"] = 999
    second = window.processed_data()

    assert raw_activities == original
    assert first is not second
    assert second[0]["splits"][0]["pace"] == "5:00 /km"
    assert second[0]["splits"][0]["lengths"][0]["distance"] == 25
    assert second == preprocess_data(raw_activities)
    json.dumps(second)


def test_processed_projection_preserves_exact_lap_swimming_and_unknown_type_behavior():
    window = normalize_activity_window(
        [
            {
                "activity_id": "lap",
                "type": "lap_swimming",
                "distance": 0.1,
                "duration": 2,
                "splits": [{"split_index": 1, "pace": 2}],
                "raw_data": {"avg_swolf": 45},
            },
            {
                "activity_id": "other",
                "type": "rowing",
                "distance": 1,
                "duration": 5,
                "splits": [{"split_index": 1, "pace": 5}],
                "raw_data": {"cadence": 30},
            },
        ]
    )

    lap, other = window.processed_data()
    assert lap["performance_value"] is None
    assert lap["performance_formatted"] == "N/A"
    assert lap["splits"][0]["pace"] == "2:00 /km"
    assert "advanced_metrics" not in lap
    assert "swimming_efficiency" not in lap
    assert other["performance_value"] is None
    assert other["splits"][0]["pace"] == "5:00 /km"
    assert "advanced_metrics" not in other
    assert "runner_type" not in other

    assert window.activities[0].performance_formatted == "2:00 /100m"
    assert window.activities[0].processed_performance_formatted == "N/A"
    assert window.activities[0].avg_swolf == 45


def test_swimming_keeps_zones_but_not_running_only_training_effect():
    swimming = normalize_activity_window(
        [
            {
                "activity_id": "swim",
                "type": "swimming",
                "distance": 1,
                "duration": 20,
                "raw_data": {
                    "aerobic_training_effect": 3.2,
                    "anaerobic_training_effect": 0.7,
                    "hr_zone_2": 600,
                    "avg_swolf": 45,
                },
            }
        ]
    ).activities[0]

    assert swimming.performance_formatted == "2:00 /100m"
    assert swimming.training_effect_aerobic == 3.2
    assert swimming.training_effect_anaerobic == 0.7
    assert swimming.hr_zone_seconds[2] == 600
    assert swimming.avg_swolf == 45


def test_normalized_records_and_nested_maps_are_immutable():
    window = normalize_activity_window(
        [
            {
                "activity_id": 1,
                "type": "running",
                "distance": 1,
                "duration": 5,
                "raw_data": {"hr_zone_1": 30},
            }
        ]
    )

    with pytest.raises(FrozenInstanceError):
        window.activities[0].distance_km = 2
    with pytest.raises(TypeError):
        window.activities[0].hr_zone_seconds[1] = 99
    with pytest.raises(TypeError):
        window.by_id["number:2"] = window.activities[0]


@pytest.mark.parametrize(
    "activity_id",
    [None, "", "   ", True, 1.5, "1.5", float("inf")],
)
def test_invalid_activity_identity_reports_source_index(activity_id):
    with pytest.raises(ActivityWindowError, match="index 0"):
        normalize_activity_window([{"activity_id": activity_id}])


def test_numeric_equivalent_activity_ids_are_duplicates():
    with pytest.raises(
        ActivityWindowError,
        match=r"index 1.*equivalent to index 0",
    ):
        normalize_activity_window(
            [
                {"activity_id": 123, "type": "running"},
                {"activity_id": "123.0", "type": "running"},
            ]
        )

    assert canonical_activity_id(123.0) == canonical_activity_id("123")


def test_zero_and_missing_values_remain_distinct_in_normalized_records():
    window = normalize_activity_window(
        [
            {
                "activity_id": 0,
                "distance": 0,
                "duration": 0,
                "average_heart_rate": 0,
                "raw_data": {"humidity": 0, "hr_zone_1": 0},
            },
            {"activity_id": "missing"},
            {
                "activity_id": "segment-zero",
                "splits": [{"split_index": 1, "duration": 0}],
            },
        ]
    )

    zero, missing, segment_zero = window.activities
    assert zero.distance_km == 0
    assert zero.duration_min == 0
    assert zero.avg_hr_bpm == 0
    assert zero.humidity_pct == 0
    assert zero.hr_zone_seconds[1] == 0
    assert missing.distance_km is None
    assert missing.duration_min is None
    assert missing.avg_hr_bpm is None
    assert missing.humidity_pct is None
    assert missing.hr_zone_seconds[1] is None
    assert segment_zero.duration_min == 0


def test_invalid_optional_metrics_are_removed_from_canonical_facts_only():
    window = normalize_activity_window(
        [
            {
                "activity_id": "run-invalid",
                "type": "running",
                "distance": 1,
                "duration": 5,
                "splits": [
                    {
                        "split_index": 1,
                        "duration": 5,
                        "avg_cadence": 180,
                        "vertical_oscillation": 21,
                        "ground_contact_time": 99,
                        "power_avg": 0,
                        "power_max": 3001,
                    }
                ],
                "raw_data": {
                    "vertical_oscillation": 21,
                    "ground_contact_time": 99,
                    "power_avg": 0,
                    "power_max": 3001,
                },
            },
            {
                "activity_id": "swim-invalid",
                "type": "swimming",
                "distance": 1,
                "duration": 20,
                "raw_data": {"avg_swolf": 250},
            },
        ]
    )

    running, swimming = window.activities
    assert running.vertical_oscillation_cm is None
    assert running.ground_contact_time_ms is None
    assert running.power_avg_w is None
    assert running.power_max_w is None
    assert running.processed_power_avg_w is None
    assert running.processed_power_max_w is None
    assert running.invalid_optional_metrics == (
        "vertical_oscillation_cm",
        "ground_contact_time_ms",
        "power_avg_w",
        "power_max_w",
    )
    assert running.segments[0].vertical_oscillation_cm is None
    assert running.segments[0].ground_contact_time_ms is None
    assert running.segments[0].power_avg_w is None
    assert running.segments[0].power_max_w is None
    assert running.segments[0].processed_power_avg_w is None
    assert running.segments[0].processed_power_max_w is None
    assert running.segments[0].invalid_optional_metrics == running.invalid_optional_metrics
    assert swimming.avg_swolf is None
    assert swimming.invalid_optional_metrics == ("avg_swolf",)

    running_projection, swimming_projection = window.processed_data()
    advanced = running_projection["advanced_metrics"]
    assert advanced["vertical_oscillation"] == 21
    assert advanced["ground_contact_time"] == 99
    assert advanced["power_avg"] == 0
    assert advanced["power_max"] == 3001
    assert "running_efficiency" not in running_projection
    assert swimming_projection["advanced_metrics"]["avg_swolf"] == 250
    assert "swimming_efficiency" not in swimming_projection


def test_processed_projection_does_not_leak_canonical_metric_aliases():
    window = normalize_activity_window(
        [
            {
                "activity_id": "cycle-aliases",
                "type": "cycling",
                "distance": 20,
                "duration": 60,
                "raw_data": {
                    "average_power": 200,
                    "max_power": 300,
                },
            },
            {
                "activity_id": "run-aliases",
                "type": "running",
                "distance": 1,
                "duration": 5,
                "splits": [
                    {
                        "split_index": 1,
                        "duration": 5,
                        "average_cadence": 180,
                    }
                ],
                "raw_data": {"avg_cadence": 180},
            },
        ]
    )

    cycling, running = window.activities
    assert cycling.power_avg_w == 200
    assert cycling.power_max_w == 300
    assert cycling.processed_power_avg_w is None
    assert cycling.processed_power_max_w is None
    assert dict(cycling.cycling_efficiency or {}) == {"power_ratio": 1.5}
    assert running.avg_cadence_spm == 180
    assert running.processed_avg_cadence_spm is None
    assert running.runner_type == "frequency_runner"
    assert running.segments[0].avg_cadence_spm == 180
    assert running.segments[0].processed_avg_cadence_spm is None

    cycling_projection, running_projection = window.processed_data()
    assert cycling_projection["advanced_metrics"]["power_avg"] is None
    assert cycling_projection["advanced_metrics"]["power_max"] is None
    assert "cycling_efficiency" not in cycling_projection
    assert running_projection["advanced_metrics"]["avg_cadence"] is None
    assert "runner_type" not in running_projection


def test_activity_window_direct_constructor_defensively_copies_collections():
    activity = normalize_activity_window(
        [{"activity_id": 1, "type": "running"}]
    ).activities[0]
    source_activities = [activity]
    source_by_id = {activity.canonical_id: activity}

    window = ActivityWindow(source_activities, source_by_id)
    source_activities.clear()
    source_by_id.clear()

    assert window.activities == (activity,)
    assert dict(window.by_id) == {activity.canonical_id: activity}


def test_empty_activity_window_is_valid():
    window = normalize_activity_window([])

    assert window.activities == ()
    assert dict(window.by_id) == {}
    assert window.processed_data() == []
