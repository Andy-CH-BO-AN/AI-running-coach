"""
訊息格式化器測試。

涵蓋：
- 跑步（easy）格式正確
- interval 只顯示工作段，不顯示整體 avg_pace
- interval 正確排除站立恢復（高配速 + 低 cadence）
- interval 工作段 > 12 段時截斷顯示
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


def _make_interval_session(**overrides) -> dict:
    """7/20 的 interval session — 含站立恢復段。"""
    base = {
        "activity_id": 23665383280,
        "date": "2026-07-20",
        "type": "interval",
        "source_activity_type": "running",
        "distance_km": 0.63,
        "duration_min": 7.7,
        "training_load": 78.7,
        "avg_hr": 144,
        "avg_pace": "12:09",  # 被恢復段拉高，不應顯示
        "segments": [
            {"segment_type": "lap", "split_index": 1, "distance_km": 0.100,
             "duration_min": 0.35, "avg_pace": "3:30", "avg_hr": 131,
             "temperature_c": 32.0, "cadence": 146.5, "stride_length_m": 1.5, "note": None},
            {"segment_type": "lap", "split_index": 2, "distance_km": 0.032,
             "duration_min": 1.51, "avg_pace": "46:29", "avg_hr": 145,
             "temperature_c": 32.0, "cadence": 17.7, "stride_length_m": 1.0, "note": None},  # 恢復
            {"segment_type": "lap", "split_index": 3, "distance_km": 0.094,
             "duration_min": 0.35, "avg_pace": "3:46", "avg_hr": 134,
             "temperature_c": 32.0, "cadence": 136.7, "stride_length_m": 1.47, "note": None},
            {"segment_type": "lap", "split_index": 4, "distance_km": 0.036,
             "duration_min": 1.51, "avg_pace": "42:15", "avg_hr": 147,
             "temperature_c": 32.0, "cadence": 29.2, "stride_length_m": 1.26, "note": None},  # 恢復
            {"segment_type": "lap", "split_index": 5, "distance_km": 0.098,
             "duration_min": 0.35, "avg_pace": "3:33", "avg_hr": 129,
             "temperature_c": 32.0, "cadence": 145.3, "stride_length_m": 1.47, "note": None},
            {"segment_type": "lap", "split_index": 6, "distance_km": 0.040,
             "duration_min": 1.48, "avg_pace": "37:10", "avg_hr": 147,
             "temperature_c": 32.0, "cadence": 28.3, "stride_length_m": 1.19, "note": None},  # 恢復
            {"segment_type": "lap", "split_index": 7, "distance_km": 0.095,
             "duration_min": 0.33, "avg_pace": "3:29", "avg_hr": 137,
             "temperature_c": 32.0, "cadence": 158.8, "stride_length_m": 1.49, "note": None},
            {"segment_type": "lap", "split_index": 8, "distance_km": 0.041,
             "duration_min": 1.50, "avg_pace": "36:11", "avg_hr": 150,
             "temperature_c": 32.0, "cadence": 38.3, "stride_length_m": 0.99, "note": None},  # 恢復
            {"segment_type": "lap", "split_index": 9, "distance_km": 0.099,
             "duration_min": 0.34, "avg_pace": "3:29", "avg_hr": 131,
             "temperature_c": 32.0, "cadence": 157.0, "stride_length_m": 1.49, "note": None},
        ],
        "environment": {"estimated_temp_c": 32.0, "humidity_pct": None, "hr_impact": None},
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
        assert "輕鬆跑" in msg

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
# Interval — 工作段提取
# ──────────────────────────────────────────────────────────────────────────────

class TestIntervalFormat:
    def test_no_overall_avg_pace(self):
        """整體 avg_pace 12:09 不應出現在 interval 訊息中。"""
        msg = format_activity_message(_make_interval_session(), _make_week())
        assert "12:09" not in msg

    def test_work_segments_displayed(self):
        """5 個工作段（R1-R5）應出現在訊息中。"""
        msg = format_activity_message(_make_interval_session(), _make_week())
        assert "R1" in msg
        assert "R5" in msg
        # 共有 5 個工作段（奇數 split_index = 1,3,5,7,9）
        assert "R6" not in msg

    def test_recovery_segments_excluded(self):
        """站立恢復配速（46:29、42:15 等）不應出現。"""
        msg = format_activity_message(_make_interval_session(), _make_week())
        assert "46:29" not in msg
        assert "42:15" not in msg
        assert "37:10" not in msg
        assert "36:11" not in msg

    def test_work_segment_paces_shown(self):
        """快速段配速應出現。"""
        msg = format_activity_message(_make_interval_session(), _make_week())
        assert "3:30" in msg
        assert "3:46" in msg or "3:29" in msg

    def test_work_segments_use_R_numbering(self):
        """工作段以 R1、R2 顯示。"""
        msg = format_activity_message(_make_interval_session(), _make_week())
        assert "R1" in msg
        assert "R2" in msg

    def test_interval_section_header(self):
        """應有主課分段標頭。"""
        msg = format_activity_message(_make_interval_session(), _make_week())
        assert "主課分段" in msg or "分段" in msg

    def test_interval_without_cadence_uses_pace_threshold(self):
        """沒有 cadence 欄位時，只依配速閾值排除恢復段。"""
        session = _make_interval_session()
        # 移除所有 cadence
        for seg in session["segments"]:
            seg.pop("cadence", None)
        msg = format_activity_message(session, None)
        # 恢復段配速仍應被排除
        assert "46:29" not in msg
        assert "42:15" not in msg


# ──────────────────────────────────────────────────────────────────────────────
# Interval — 超過 12 段截斷顯示
# ──────────────────────────────────────────────────────────────────────────────

class TestIntervalTruncation:
    def _make_many_rep_session(self, rep_count: int) -> dict:
        """建立含 rep_count 個工作段（每段 100m 3:30/km cadence=150）的 interval 課。"""
        segments = []
        for i in range(rep_count):
            seg_idx = i * 2 + 1
            segments.append({
                "segment_type": "lap",
                "split_index": seg_idx,
                "distance_km": 0.1,
                "duration_min": 0.35,
                "avg_pace": "3:30",
                "avg_hr": 155,
                "temperature_c": 28.0,
                "cadence": 180.0,
                "stride_length_m": 1.5,
                "note": None,
            })
            # 每個工作段後加一個恢復段
            if i < rep_count - 1:
                segments.append({
                    "segment_type": "lap",
                    "split_index": seg_idx + 1,
                    "distance_km": 0.05,
                    "duration_min": 1.5,
                    "avg_pace": "30:00",
                    "avg_hr": 140,
                    "temperature_c": 28.0,
                    "cadence": 20.0,
                    "stride_length_m": 1.0,
                    "note": None,
                })
        return {
            "activity_id": 99999,
            "date": "2026-07-25",
            "type": "interval",
            "source_activity_type": "running",
            "distance_km": 1.5,
            "duration_min": 30.0,
            "training_load": 150.0,
            "avg_hr": 165,
            "avg_pace": "15:00",
            "segments": segments,
            "environment": {"estimated_temp_c": None, "humidity_pct": None, "hr_impact": None},
            "data_quality": {"status": "complete", "missing_fields": []},
        }

    def test_exactly_12_reps_shows_all(self):
        session = self._make_many_rep_session(12)
        msg = format_activity_message(session, None)
        assert "R12" in msg
        assert "R13" not in msg

    def test_13_reps_truncates(self):
        """13 段應截斷，顯示前 5 + 後 3 + 統計摘要。"""
        session = self._make_many_rep_session(13)
        msg = format_activity_message(session, None)
        assert "R1" in msg
        assert "R5" in msg
        # 前 5 後 3：R11、R12、R13 應出現
        assert "R11" in msg or "R12" in msg or "R13" in msg
        # R6-R10 不應顯示
        assert "R6" not in msg


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
        ("running", "easy", "輕鬆跑"),
        ("running", "interval", "間歇"),
        ("running", "tempo", "節奏跑"),
        ("running", "long", "長跑"),
        ("running", "long_run", "長跑"),
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

    def test_unknown_type_shows_source_activity_type(self):
        """未知 type 顯示 source_activity_type 原值，不顯示難懂內部 type。"""
        session = _make_easy_running_session(
            source_activity_type="hiking",
            type="unknown_xyz",
        )
        msg = format_activity_message(session, None)
        assert "hiking" in msg
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
