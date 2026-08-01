"""LINE 訊息格式化器。

輸入 coach_context 中的單一 activity dict，輸出純文字 LINE 訊息。
訊息只包含客觀訓練數據，不含 AI 分析或訓練建議。

TODO: 未來 coach_context 加入 start_time_local / end_time_local 後，
      可依相同 source_activity_type 與時間間隔合併相鄰活動為一則訊息。
      屆時可另外建立 activity grouping layer，format_activity_message 接收
      list[dict]；目前第一版每次只傳一筆，保持介面簡潔。
"""
from __future__ import annotations

from typing import Any

# ──────────────────────────────────────────────────────────────────────────────
# 運動類型對照
# ──────────────────────────────────────────────────────────────────────────────

_SPORT_EMOJI = {
    "running": "🏃",
    "swimming": "🏊",
    "cycling": "🚴",
}


def _sport_display_name(source_activity_type: str) -> str:
    """取得顯示名稱。

    只依 source_activity_type 決定顯示名稱。未知類型保留原始值，
    不使用 coach_context 推測的內部 type。
    """
    sat = source_activity_type.lower()
    if sat == "running":
        return "跑步"
    if sat == "swimming":
        return "游泳"
    if sat == "cycling":
        return "自行車"
    return source_activity_type


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


def _format_speed(speed_kmh: float | None) -> str | None:
    """格式化速度，移除無意義尾端零。"""
    if speed_kmh is None:
        return None
    try:
        formatted = f"{float(speed_kmh):.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return None
    return f"{formatted} km/h"


def _format_segment(
    segment: dict[str, Any],
    position: int,
    source_activity_type: str,
) -> str:
    """以運動原始類型格式化單一 split，不使用推測的 session type。"""
    split_index = segment.get("split_index")
    label = split_index if split_index not in (None, "") else position
    details: list[str] = [f"#{label}"]

    distance = _format_distance(segment.get("distance_km"))
    if distance:
        details.append(distance)

    duration = _format_duration(segment.get("duration_min"))
    if duration:
        details.append(duration)

    source_type = source_activity_type.lower()
    avg_pace = segment.get("avg_pace")
    if source_type == "running" and avg_pace:
        details.append(f"配速 {avg_pace}/km")
    elif source_type == "swimming" and avg_pace:
        details.append(f"配速 {avg_pace}/100m")
    elif source_type == "cycling":
        speed = _format_speed(segment.get("speed_kmh"))
        if speed:
            details.append(f"速度 {speed}")

    avg_hr = segment.get("avg_hr")
    if avg_hr is not None:
        details.append(f"心率 {avg_hr} bpm")

    return "｜".join(details)


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
    source_type = str(activity.get("source_activity_type") or "")
    date_str = activity.get("date", "")

    emoji = _sport_emoji(source_type)
    display_name = _sport_display_name(source_type)

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

    # 配速單位只依原始運動類型，跑步一律顯示整體 avg_pace。
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

    # ── 所有分段：只依原始運動類型決定配速／速度單位。
    segments = activity.get("segments")
    if isinstance(segments, list) and segments:
        lines.append("")
        lines.append("分段明細")
        for position, segment in enumerate(segments, start=1):
            if isinstance(segment, dict):
                lines.append(_format_segment(segment, position, source_type))

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
