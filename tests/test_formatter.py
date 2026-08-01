"""
訊息格式化器測試。

涵蓋：
- 跑步格式只依 source_activity_type，忽略推測的 type
- 游泳配速格式 /100m
- 自行車速度格式 km/h
- 距離 < 1km 顯示公尺，≥ 1km 顯示公里
- 缺少欄位時省略，不顯示 null
- 缺少溫度時省略溫度行
- 本週累積只顯示訓練負荷，不顯示 derived_total_distance_km
- 時間格式 MM:SS
- km 數值移除尾端零
"""
from __future__ import annotations

import pytest

from src.notifications.formatter import format_activity_message


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _make_easy_running_session(**overrides) -> dict:
    base = {
        "activity_id": 11111,
        "date": "2026-07-21",
        "type": "easy",
        "source_activity_type": "running",
        "distance_km": 8.05,
        "duration_min": 51.9,
        "training_load": 84.6,
        "avg_hr": 152,
        "avg_pace": "6:26",
        "segments": [],
        "environment": {"estimated_temp_c": 30.8, "humidity_pct": None, "hr_impact": None},
        "data_quality": {"status": "complete", "missing_fields": []},
    }
    base.update(overrides)
    return base


def _make_swim_session(**overrides) -> dict:
    base = {
        "activity_id": 23510530594,
        "date": "2026-07-07",
        "type": "swim",
        "source_activity_type": "swimming",
        "distance_km": 2.4,
        "duration_min": 68.9,
        "training_load": 158.5,
        "avg_hr": 149,
        "avg_pace": "2:52",
        "segments": [],
        "environment": {"estimated_temp_c": None, "humidity_pct": None, "hr_impact": None},
        "data_quality": {"status": "complete", "missing_fields": []},
    }
    base.update(overrides)
    return base


def _make_cycling_session(**overrides) -> dict:
    base = {
        "activity_id": 23441977562,
        "date": "2026-07-01",
        "type": "bike",
        "source_activity_type": "cycling",
        "distance_km": 9.09,
        "duration_min": 27.3,
        "training_load": 50.0,
        "avg_hr": 139,
        "avg_pace": "20.0 km/h",
        "segments": [],
        "environment": {"estimated_temp_c": None, "humidity_pct": None, "hr_impact": None},
        "data_quality": {"status": "complete", "missing_fields": []},
    }
    base.update(overrides)
    return base


def _make_week(training_load: float = 727.1, total_distance_km: float = 31.37) -> dict:
    return {
        "week_label": "07/20-07/26",
        "week_start": "2026-07-20",
        "week_end": "2026-07-26",
        "derived_total_distance_km": total_distance_km,
        "derived_total_duration_min": 188.3,
        "derived_training_load": training_load,
        "sessions": [],
    }


# ──────────────────────────────────────────────────────────────────────────────
# 跑步（easy）
# ──────────────────────────────────────────────────────────────────────────────

class TestEasyRunFormat:
    def test_contains_sport_name(self):
        msg = format_activity_message(_make_easy_running_session(), _make_week())
        assert "跑步" in msg

    def test_contains_date(self):
        msg = format_activity_message(_make_easy_running_session(), _make_week())
        assert "2026-07-21" in msg

    def test_contains_distance_km(self):
        msg = format_activity_message(_make_easy_running_session(), _make_week())
        assert "8.05" in msg
        assert "km" in msg

    def test_contains_avg_pace(self):
        msg = format_activity_message(_make_easy_running_session(), _make_week())
        assert "6:26" in msg
        assert "/km" in msg

    def test_contains_avg_hr(self):
        msg = format_activity_message(_make_easy_running_session(), _make_week())
        assert "152" in msg
        assert "bpm" in msg

    def test_contains_training_load(self):
        msg = format_activity_message(_make_easy_running_session(), _make_week())
        assert "84.6" in msg

    def test_contains_temperature(self):
        msg = format_activity_message(_make_easy_running_session(), _make_week())
        assert "30.8" in msg or "30" in msg
        assert "°C" in msg or "C" in msg

    def test_week_training_load_displayed(self):
        msg = format_activity_message(_make_easy_running_session(), _make_week())
        assert "727" in msg

    def test_time_format_mmss(self):
        """51.9 min → 51:54"""
        msg = format_activity_message(_make_easy_running_session(), _make_week())
        assert "51:54" in msg

    def test_distance_trailing_zero_removed(self):
        """距離 2.40 應顯示為 2.4，不是 2.40。"""
        session = _make_easy_running_session(distance_km=2.4)
        msg = format_activity_message(session, _make_week())
        assert "2.4" in msg
        assert "2.40" not in msg


# ──────────────────────────────────────────────────────────────────────────────
# 距離格式
# ──────────────────────────────────────────────────────────────────────────────

class TestDistanceFormat:
    def test_less_than_1km_shows_meters(self):
        session = _make_easy_running_session(distance_km=0.63)
        msg = format_activity_message(session, None)
        assert "630m" in msg or "630" in msg

    def test_1km_shows_km(self):
        session = _make_easy_running_session(distance_km=1.0)
        msg = format_activity_message(session, None)
        assert "1" in msg and "km" in msg


# ──────────────────────────────────────────────────────────────────────────────
# 推測的 type 不影響 LINE 顯示
# ──────────────────────────────────────────────────────────────────────────────

class TestInferredTypeIsolation:
    def test_interval_type_keeps_running_title_and_overall_pace(self):
        """type=interval 不改標題、不隱藏整體配速、不顯示舊分類分段。"""
        session = _make_easy_running_session(
            type="interval",
            avg_pace="6:08",
            segments=[{
                "split_index": 1,
                "distance_km": 0.621,
                "duration_min": 3.81,
                "avg_pace": "6:08",
            }],
        )

        msg = format_activity_message(session, _make_week())

        assert msg.split("\n", maxsplit=1)[0] == "🏃 跑步｜2026-07-21"
        assert "配速：6:08/km" in msg
        assert "間歇" not in msg
        assert "主課分段" not in msg
        assert "R1" not in msg
        assert "621m × 1" not in msg
        assert "（621m × 1）" not in msg
        assert "分段明細" in msg
        assert "#1｜621m｜3:49｜配速 6:08/km" in msg

    def test_all_running_splits_are_displayed_without_classifying_them(self):
        session = _make_easy_running_session(
            type="interval",
            segments=[
                {"split_index": 1, "distance_km": 1.0, "duration_min": 5.0, "avg_pace": "5:00", "avg_hr": 160},
                {"split_index": 2, "distance_km": 0.2, "duration_min": 3.0, "avg_pace": "15:00", "avg_hr": 120},
                {"split_index": 3, "distance_km": 1.0, "duration_min": 4.8, "avg_pace": "4:48", "avg_hr": 170},
            ],
        )

        msg = format_activity_message(session, None)

        assert "#1｜1 km｜5:00｜配速 5:00/km｜心率 160 bpm" in msg
        assert "#2｜200m｜3:00｜配速 15:00/km｜心率 120 bpm" in msg
        assert "#3｜1 km｜4:48｜配速 4:48/km｜心率 170 bpm" in msg
        assert "間歇" not in msg
        assert "R1" not in msg


# ──────────────────────────────────────────────────────────────────────────────
# 游泳
# ──────────────────────────────────────────────────────────────────────────────

class TestSwimFormat:
    def test_sport_name(self):
        msg = format_activity_message(_make_swim_session(), _make_week())
        assert "游泳" in msg

    def test_pace_unit_per_100m(self):
        msg = format_activity_message(_make_swim_session(), _make_week())
        assert "2:52" in msg
        assert "100m" in msg

    def test_no_temperature_when_missing(self):
        """游泳無溫度資料時，不顯示溫度行。"""
        msg = format_activity_message(_make_swim_session(), _make_week())
        assert "°C" not in msg and "溫度" not in msg

    def test_all_swimming_splits_show_per_100m_pace(self):
        session = _make_swim_session(segments=[
            {"split_index": 1, "distance_km": 0.05, "duration_min": 1.4, "avg_pace": "2:48", "avg_hr": 145},
            {"split_index": 2, "distance_km": 0.05, "duration_min": 1.5, "avg_pace": "3:00", "avg_hr": 147},
        ])

        msg = format_activity_message(session, None)

        assert "#1｜50m｜1:24｜配速 2:48/100m｜心率 145 bpm" in msg
        assert "#2｜50m｜1:30｜配速 3:00/100m｜心率 147 bpm" in msg


# ──────────────────────────────────────────────────────────────────────────────
# 自行車
# ──────────────────────────────────────────────────────────────────────────────

class TestCyclingFormat:
    def test_sport_name(self):
        msg = format_activity_message(_make_cycling_session(), _make_week())
        assert "自行車" in msg

    def test_speed_unit_kmh(self):
        msg = format_activity_message(_make_cycling_session(), _make_week())
        assert "20" in msg
        assert "km/h" in msg

    def test_all_cycling_splits_show_speed(self):
        session = _make_cycling_session(segments=[
            {"split_index": 1, "distance_km": 5.0, "duration_min": 15.0, "speed_kmh": 20.0, "avg_hr": 135},
            {"split_index": 2, "distance_km": 4.09, "duration_min": 12.3, "speed_kmh": 19.95, "avg_hr": 143},
        ])

        msg = format_activity_message(session, None)

        assert "#1｜5 km｜15:00｜速度 20 km/h｜心率 135 bpm" in msg
        assert "#2｜4.09 km｜12:18｜速度 19.9 km/h｜心率 143 bpm" in msg


# ──────────────────────────────────────────────────────────────────────────────
# 缺少欄位
# ──────────────────────────────────────────────────────────────────────────────

class TestMissingFields:
    def test_missing_avg_hr_no_null(self):
        session = _make_easy_running_session(avg_hr=None)
        msg = format_activity_message(session, None)
        assert "null" not in msg.lower()
        assert "None" not in msg
        assert "bpm" not in msg  # 沒有心率就省略整行

    def test_missing_training_load_no_null(self):
        session = _make_easy_running_session(training_load=None)
        msg = format_activity_message(session, None)
        assert "null" not in msg.lower()

    def test_missing_temperature_no_line(self):
        session = _make_easy_running_session(
            environment={"estimated_temp_c": None, "humidity_pct": None, "hr_impact": None}
        )
        msg = format_activity_message(session, None)
        assert "°C" not in msg
        assert "溫度" not in msg

    def test_week_none_no_week_section(self):
        """week=None 時不顯示本週累積區塊。"""
        msg = format_activity_message(_make_easy_running_session(), None)
        assert "本週" not in msg or "累積" not in msg

    def test_missing_avg_pace_no_null(self):
        session = _make_easy_running_session(avg_pace=None)
        msg = format_activity_message(session, None)
        assert "null" not in msg.lower()
        assert "None" not in msg


# ──────────────────────────────────────────────────────────────────────────────
# 本週累積不顯示混合距離
# ──────────────────────────────────────────────────────────────────────────────

class TestWeeklyStats:
    def test_weekly_training_load_shown(self):
        msg = format_activity_message(_make_easy_running_session(), _make_week(training_load=500.0))
        assert "500" in msg

    def test_derived_total_distance_not_shown_as_week_distance(self):
        """derived_total_distance_km 是混合運動，不應顯示為本週距離。"""
        week = _make_week(training_load=500.0, total_distance_km=99.99)
        msg = format_activity_message(_make_easy_running_session(), week)
        # 99.99 不應出現在本週區塊（可能出現在本次訓練但不是本週累積）
        # 簡單驗證：沒有「本週距離」或「本週 ... 99」
        lines = msg.split("\n")
        week_section = False
        for line in lines:
            if "本週" in line:
                week_section = True
            if week_section and "99.99" in line:
                pytest.fail("derived_total_distance_km 出現在本週累積區塊")


# ──────────────────────────────────────────────────────────────────────────────
# 運動類型對照
# ──────────────────────────────────────────────────────────────────────────────

class TestActivityTypeMapping:
    @pytest.mark.parametrize("source_type,session_type,expected_name", [
        ("running", "easy", "跑步"),
        ("running", "interval", "跑步"),
        ("running", "tempo", "跑步"),
        ("running", "long", "跑步"),
        ("running", "long_run", "跑步"),
        ("swimming", "swim", "游泳"),
        ("cycling", "bike", "自行車"),
    ])
    def test_type_mapping(self, source_type, session_type, expected_name):
        session = _make_easy_running_session(
            source_activity_type=source_type,
            type=session_type,
        )
        msg = format_activity_message(session, None)
        assert expected_name in msg

    def test_unknown_source_activity_type_keeps_raw_value(self):
        """未知 source_activity_type 保留原始值，不顯示內部 type。"""
        session = _make_easy_running_session(
            source_activity_type="Hiking",
            type="unknown_xyz",
        )
        msg = format_activity_message(session, None)
        assert "Hiking" in msg
        assert "unknown_xyz" not in msg


# ──────────────────────────────────────────────────────────────────────────────
# Garmin Connect 活動連結
# ──────────────────────────────────────────────────────────────────────────────

_GARMIN_BASE = "https://connect.garmin.com/modern/activity/"


class TestGarminActivityLink:
    def test_valid_int_activity_id_shows_link(self):
        """正整數 activity_id 應顯示正確的 Garmin Connect URL。"""
        session = _make_easy_running_session(activity_id=23738727822)
        msg = format_activity_message(session, None)
        assert f"{_GARMIN_BASE}23738727822" in msg
        assert "🔗" in msg

    def test_numeric_string_activity_id_shows_link(self):
        """數字字串 activity_id 應正常轉換並顯示連結。"""
        session = _make_easy_running_session(activity_id="23738727822")
        msg = format_activity_message(session, None)
        assert f"{_GARMIN_BASE}23738727822" in msg

    def test_link_appears_after_week_section(self):
        """連結應出現在本週累積區塊之後。"""
        session = _make_easy_running_session(activity_id=12345)
        msg = format_activity_message(session, _make_week())
        week_pos = msg.find("本週累積")
        link_pos = msg.find(_GARMIN_BASE)
        assert week_pos != -1
        assert link_pos != -1
        assert link_pos > week_pos

    def test_link_appears_without_week_section(self):
        """week=None 時，連結仍正常顯示。"""
        session = _make_easy_running_session(activity_id=12345)
        msg = format_activity_message(session, None)
        assert f"{_GARMIN_BASE}12345" in msg

    def test_missing_activity_id_no_link(self):
        """activity_id 缺失時不顯示連結。"""
        session = _make_easy_running_session()
        del session["activity_id"]
        msg = format_activity_message(session, None)
        assert _GARMIN_BASE not in msg

    def test_none_activity_id_no_link(self):
        """activity_id 為 None 時不顯示連結。"""
        session = _make_easy_running_session(activity_id=None)
        msg = format_activity_message(session, None)
        assert _GARMIN_BASE not in msg

    def test_non_numeric_string_activity_id_no_link(self):
        """非數字字串 activity_id 不顯示連結。"""
        session = _make_easy_running_session(activity_id="abc123")
        msg = format_activity_message(session, None)
        assert _GARMIN_BASE not in msg

    def test_zero_activity_id_no_link(self):
        """activity_id 為 0 時不顯示連結。"""
        session = _make_easy_running_session(activity_id=0)
        msg = format_activity_message(session, None)
        assert _GARMIN_BASE not in msg

    def test_negative_activity_id_no_link(self):
        """activity_id 為負數時不顯示連結。"""
        session = _make_easy_running_session(activity_id=-9999)
        msg = format_activity_message(session, None)
        assert _GARMIN_BASE not in msg

    def test_float_whole_number_shows_link(self):
        """整數值的 float（如 12345.0）可正常轉換為正整數並顯示連結。"""
        session = _make_easy_running_session(activity_id=12345.0)
        msg = format_activity_message(session, None)
        assert f"{_GARMIN_BASE}12345" in msg

    def test_non_integer_float_no_link(self):
        """非整數 float（如 12345.9）不應截斷為 12345，應不顯示連結。"""
        session = _make_easy_running_session(activity_id=12345.9)
        msg = format_activity_message(session, None)
        assert _GARMIN_BASE not in msg

    def test_bool_true_no_link(self):
        """True（Python bool，int 子類）不應產生 activity/1，應不顯示連結。"""
        session = _make_easy_running_session(activity_id=True)
        msg = format_activity_message(session, None)
        assert _GARMIN_BASE not in msg

    def test_bool_false_no_link(self):
        """False（Python bool，int 子類）不應產生 activity/0，應不顯示連結。"""
        session = _make_easy_running_session(activity_id=False)
        msg = format_activity_message(session, None)
        assert _GARMIN_BASE not in msg
