"""LINE 訊息格式化器。

輸入 coach_context 中的單一 activity dict，輸出純文字 LINE 訊息。
訊息只包含客觀訓練數據，不含 AI 分析或訓練建議。

TODO: 未來 coach_context 加入 start_time_local / end_time_local 後，
      可依相同 source_activity_type 與時間間隔合併相鄰活動為一則訊息。
      屆時可另外建立 activity grouping layer，format_activity_message 接收
      list[dict]；目前第一版每次只傳一筆，保持介面簡潔。
"""
from __future__ import annotations

import statistics
from typing import Any

from src.notifications.constants import (
    MAX_DISPLAYED_REPS,
    MAX_WORK_PACE_SEC_PER_KM,
    MIN_WORK_CADENCE_SPM,
    MIN_WORK_DISTANCE_KM,
    REP_DISTANCE_TOLERANCE,
    TRUNCATED_HEAD_COUNT,
    TRUNCATED_TAIL_COUNT,
)

# ──────────────────────────────────────────────────────────────────────────────
# 運動類型對照
# ──────────────────────────────────────────────────────────────────────────────

_SPORT_EMOJI = {
    "running": "🏃",
    "swimming": "🏊",
    "cycling": "🚴",
}

_RUNNING_TYPE_NAMES: dict[str, str] = {
    "easy": "輕鬆跑",
    "interval": "間歇",
    "tempo": "節奏跑",
    "long": "長跑",
    "long_run": "長跑",
}


def _sport_display_name(source_activity_type: str, session_type: str) -> str:
    """取得顯示名稱。

    優先以 source_activity_type 決定大分類，
    再以 session_type 做細分（目前只對 running 有細分）。
    未知類型直接顯示 source_activity_type，不顯示內部 type。
    """
    sat = source_activity_type.lower()
    if sat == "running":
        return _RUNNING_TYPE_NAMES.get(session_type.lower(), "跑步")
    if sat == "swimming":
        return "游泳"
    if sat == "cycling":
        return "自行車"
    return sat  # 未知類型顯示 source_activity_type 原值


def _sport_emoji(source_activity_type: str) -> str:
    return _SPORT_EMOJI.get(source_activity_type.lower(), "🏋️")


# ──────────────────────────────────────────────────────────────────────────────
# Garmin Connect 連結
# ──────────────────────────────────────────────────────────────────────────────

_GARMIN_ACTIVITY_BASE = "https://connect.garmin.com/modern/activity/"


def _garmin_activity_url(activity_id: Any) -> str | None:
    """將 activity_id 轉為 Garmin Connect 連結。

    接受規則（依序檢查）：
    - bool 一律拒絕（Python 中 bool 是 int 的子類，True→1 會產生錯誤連結）
    - int：直接使用
    - float：僅接受 is_integer() 為 True（12345.0 可；12345.9 拒絕）
    - str：僅接受可直接轉換的純整數字串（"12345" 可；"12345.0" 拒絕）
    - 其餘型別：拒絕

    不接受外部傳入的任意 URL，固定使用 _GARMIN_ACTIVITY_BASE 模板。
    """
    if activity_id is None:
        return None
    # bool 是 int 子類，必須優先排除，否則 True → 1、False → 0
    if isinstance(activity_id, bool):
        return None
    if isinstance(activity_id, int):
        aid = activity_id
    elif isinstance(activity_id, float):
        if not activity_id.is_integer():
            return None
        aid = int(activity_id)
    elif isinstance(activity_id, str):
        try:
            aid = int(activity_id)  # "12345.9" 等非純整數字串會 raise ValueError
        except ValueError:
            return None
    else:
        return None
    if aid <= 0:
        return None
    return f"{_GARMIN_ACTIVITY_BASE}{aid}"


# ──────────────────────────────────────────────────────────────────────────────
# 數值格式化工具
# ──────────────────────────────────────────────────────────────────────────────

def _format_distance(distance_km: float | None) -> str | None:
    """格式化距離。< 1km 顯示整數公尺，≥ 1km 顯示去尾端零的 km。"""
    if distance_km is None:
        return None
    if distance_km < 1.0:
        meters = round(distance_km * 1000)
        return f"{meters}m"
    # 保留最多兩位小數，移除無意義尾端零
    formatted = f"{distance_km:.2f}".rstrip("0").rstrip(".")
    return f"{formatted} km"


def _format_duration(duration_min: float | None) -> str | None:
    """格式化時間為 MM:SS。"""
    if duration_min is None:
        return None
    total_sec = round(duration_min * 60)
    minutes = total_sec // 60
    seconds = total_sec % 60
    return f"{minutes}:{seconds:02d}"


def _format_load(training_load: float | None) -> str | None:
    if training_load is None:
        return None
    # 顯示一位小數，移除尾端零
    formatted = f"{training_load:.1f}".rstrip("0").rstrip(".")
    return formatted


def _format_temp(temp_c: float | None) -> str | None:
    if temp_c is None:
        return None
    formatted = f"{temp_c:.1f}".rstrip("0").rstrip(".")
    return f"{formatted}°C"


def _pace_to_sec_per_km(pace_str: str) -> int | None:
    """將 'MM:SS' 格式配速字串轉換為秒/公里。解析失敗回傳 None。"""
    if not pace_str:
        return None
    # 過濾非跑步配速（含 km/h 的自行車速度）
    if "km/h" in pace_str:
        return None
    try:
        parts = pace_str.strip().split(":")
        if len(parts) != 2:
            return None
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, AttributeError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Interval 工作段提取
# ──────────────────────────────────────────────────────────────────────────────

def _is_work_segment(seg: dict[str, Any]) -> bool:
    """判定 segment 是否為工作段（排除站立/慢走恢復段）。

    多條件組合：
    1. cadence 有值且 < MIN_WORK_CADENCE_SPM → 排除
    2. 配速超過 MAX_WORK_PACE_SEC_PER_KM → 排除
    3. 距離 < MIN_WORK_DISTANCE_KM → 排除
    4. duration 長但距離極短（cadence 極低暗示站立）→ 排除
    """
    distance = seg.get("distance_km") or 0.0
    if distance < MIN_WORK_DISTANCE_KM:
        return False

    cadence = seg.get("cadence")
    if cadence is not None and cadence < MIN_WORK_CADENCE_SPM:
        return False

    avg_pace = seg.get("avg_pace")
    if avg_pace:
        pace_sec = _pace_to_sec_per_km(avg_pace)
        if pace_sec is not None and pace_sec > MAX_WORK_PACE_SEC_PER_KM:
            return False

    return True


def _extract_work_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """從 segments 中提取工作段，回傳含 rep_index 與 source_split_index 的 list。"""
    work = []
    rep_idx = 1
    for seg in segments:
        if _is_work_segment(seg):
            work.append({
                "rep_index": rep_idx,
                "source_split_index": seg.get("split_index"),
                "distance_km": seg.get("distance_km"),
                "avg_pace": seg.get("avg_pace"),
                "avg_hr": seg.get("avg_hr"),
            })
            rep_idx += 1
    return work


def _format_rep_line(rep: dict[str, Any]) -> str:
    """格式化單一工作段為顯示行。"""
    parts = [f"R{rep['rep_index']}"]
    dist = _format_distance(rep.get("distance_km"))
    if dist:
        parts.append(dist)
    pace = rep.get("avg_pace")
    if pace:
        parts.append(f"{pace}/km")
    return "｜".join(parts)


def _is_uniform_reps(reps: list[dict[str, Any]]) -> tuple[bool, float | None]:
    """判斷工作段距離是否均一（中位數 ±10%），回傳 (均一, 中位距離)。"""
    distances = [r["distance_km"] for r in reps if r.get("distance_km") is not None]
    if not distances:
        return False, None
    med = statistics.median(distances)
    if med == 0:
        return False, None
    is_uniform = all(
        abs(d - med) / med <= REP_DISTANCE_TOLERANCE for d in distances
    )
    return is_uniform, med


def _format_interval_section(segments: list[dict[str, Any]]) -> str | None:
    """格式化主課分段區塊。無工作段時回傳 None。"""
    reps = _extract_work_segments(segments)
    if not reps:
        return None

    lines = ["主課分段"]

    if len(reps) <= MAX_DISPLAYED_REPS:
        for rep in reps:
            lines.append(_format_rep_line(rep))
    else:
        # 截斷顯示：統計摘要 + 前 5 + 後 3
        paces_sec = [
            _pace_to_sec_per_km(r["avg_pace"])
            for r in reps
            if r.get("avg_pace") and _pace_to_sec_per_km(r["avg_pace"]) is not None
        ]
        lines.append(f"共 {len(reps)} 段")

        if paces_sec:
            avg_sec = round(statistics.mean(paces_sec))
            avg_pace_str = f"{avg_sec // 60}:{avg_sec % 60:02d}"
            fastest = min(paces_sec)
            slowest = max(paces_sec)
            fastest_str = f"{fastest // 60}:{fastest % 60:02d}"
            slowest_str = f"{slowest // 60}:{slowest % 60:02d}"
            lines.append(f"平均 {avg_pace_str}/km｜最快 {fastest_str}｜最慢 {slowest_str}")

        lines.append("— 前段 —")
        for rep in reps[:TRUNCATED_HEAD_COUNT]:
            lines.append(_format_rep_line(rep))
        lines.append("— 後段 —")
        for rep in reps[-TRUNCATED_TAIL_COUNT:]:
            lines.append(_format_rep_line(rep))

    # 均一課表摘要
    is_uniform, med_dist = _is_uniform_reps(reps)
    if is_uniform and med_dist is not None:
        med_m = round(med_dist * 1000)
        lines.insert(1, f"（{med_m}m × {len(reps)}）")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# 主格式化函式
# ──────────────────────────────────────────────────────────────────────────────

def format_activity_message(
    activity: dict[str, Any],
    week: dict[str, Any] | None,
) -> str:
    """將單一 activity dict 格式化為 LINE 純文字訊息。

    Args:
        activity: coach_context 中的 weekly_analysis[].sessions[] 單筆 dict。
        week: 該活動所屬的 weekly_analysis entry（用於取得訓練負荷）。
              若為 None，則不顯示本週累積區塊。

    Returns:
        LINE 純文字訊息（不含 AI 分析或訓練建議）。
    """
    source_type = activity.get("source_activity_type", "")
    session_type = activity.get("type", "")
    date_str = activity.get("date", "")

    emoji = _sport_emoji(source_type)
    display_name = _sport_display_name(source_type, session_type)

    lines: list[str] = []

    # ── 標題
    lines.append(f"{emoji} {display_name}｜{date_str}")
    lines.append("")

    # ── 基本數據
    dist_str = _format_distance(activity.get("distance_km"))
    if dist_str:
        lines.append(f"距離：{dist_str}")

    dur_str = _format_duration(activity.get("duration_min"))
    if dur_str:
        lines.append(f"時間：{dur_str}")

    # 配速/速度：interval 跑步不顯示整體 avg_pace
    is_interval_running = (
        session_type.lower() == "interval"
        and source_type.lower() == "running"
    )
    if not is_interval_running:
        avg_pace = activity.get("avg_pace")
        if avg_pace:
            if source_type.lower() == "running":
                lines.append(f"配速：{avg_pace}/km")
            elif source_type.lower() == "swimming":
                lines.append(f"配速：{avg_pace}/100m")
            elif source_type.lower() == "cycling":
                # avg_pace 對自行車已含 km/h（如 "20.0 km/h"）
                lines.append(f"速度：{avg_pace}")

    avg_hr = activity.get("avg_hr")
    if avg_hr is not None:
        lines.append(f"平均心率：{avg_hr} bpm")

    load_str = _format_load(activity.get("training_load"))
    if load_str:
        lines.append(f"訓練負荷：{load_str}")

    env = activity.get("environment") or {}
    temp_str = _format_temp(env.get("estimated_temp_c"))
    if temp_str:
        lines.append(f"溫度：{temp_str}")

    # ── Interval 主課分段
    if is_interval_running:
        segments = activity.get("segments") or []
        interval_section = _format_interval_section(segments)
        if interval_section:
            lines.append("")
            lines.append(interval_section)

    # ── 本週累積
    if week is not None:
        week_load = week.get("derived_training_load")
        if week_load is not None:
            load_display = _format_load(week_load)
            lines.append("")
            lines.append("📊 本週累積")
            lines.append(f"訓練負荷：{load_display}")
            # 注意：derived_total_distance_km 混合跑步、游泳、自行車，
            # 第一版不顯示，避免誤導。
            # 待 coach_context 提供分運動類型的 subtotal 後再啟用。

    # ── Garmin Connect 連結（本週累積之後）
    url = _garmin_activity_url(activity.get("activity_id"))
    if url:
        lines.append("")
        lines.append(f"🔗 {url}")

    return "\n".join(lines)
