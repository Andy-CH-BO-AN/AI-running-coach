"""LINE 訊息格式化器。

輸入 coach_context 中的單一 activity dict，輸出純文字 LINE 訊息。
訊息只包含客觀訓練數據，不含 AI 分析或訓練建議。

TODO: 未來 coach_context 加入 start_time_local / end_time_local 後，
      可依相同 source_activity_type 與時間間隔合併相鄰活動為一則訊息。
      屆時可另外建立 activity grouping layer，format_activity_message 接收
      list[dict]；目前第一版每次只傳一筆，保持介面簡潔。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.notifications.constants import LINE_SAFE_TEXT_LENGTH
from src.notifications.text_utils import utf16_length

# ──────────────────────────────────────────────────────────────────────────────
# 運動類型對照
# ──────────────────────────────────────────────────────────────────────────────

_SPORT_EMOJI = {
    "running": "🏃",
    "swimming": "🏊",
    "cycling": "🚴",
}
_SWIMMING_SOURCE_TYPES = frozenset({"swimming", "lap_swimming"})
_STRENGTH_SOURCE_TYPE = "strength_training"


def _is_swimming_source_type(source_activity_type: str) -> bool:
    return source_activity_type.lower() in _SWIMMING_SOURCE_TYPES


def _sport_display_name(source_activity_type: str) -> str:
    """取得顯示名稱。

    只依 source_activity_type 決定顯示名稱。未知類型保留原始值，
    不使用 coach_context 推測的內部 type。
    """
    sat = source_activity_type.lower()
    if sat == "running":
        return "跑步"
    if sat in _SWIMMING_SOURCE_TYPES:
        return "游泳"
    if sat == "cycling":
        return "自行車"
    if sat == _STRENGTH_SOURCE_TYPE:
        return "肌力訓練"
    return source_activity_type


def _sport_emoji(source_activity_type: str) -> str:
    if _is_swimming_source_type(source_activity_type):
        return _SPORT_EMOJI["swimming"]
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
    elif source_type in _SWIMMING_SOURCE_TYPES and avg_pace:
        details.append(f"配速 {avg_pace}/100m")
    elif source_type == "cycling":
        speed = _format_speed(segment.get("speed_kmh"))
        if speed:
            details.append(f"速度 {speed}")

    avg_hr = segment.get("avg_hr")
    if avg_hr is not None:
        details.append(f"心率 {avg_hr} bpm")

    return "｜".join(details)


def _format_pace_seconds_per_100m(value: Any) -> str | None:
    """Render a coach-context pace fact without deriving a new aggregate."""
    if isinstance(value, bool):
        return None
    try:
        total_seconds = int(value)
    except (TypeError, ValueError):
        return None
    if total_seconds < 0:
        return None

    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _swimming_pace_detail(avg_pace: Any) -> str | None:
    if avg_pace in (None, ""):
        return None
    pace = str(avg_pace)
    return pace if pace.endswith("/100m") else f"{pace}/100m"


def _format_swimming_segment(
    segment: dict[str, Any],
    *,
    compact: bool,
) -> str:
    """Format one swim segment without exposing Garmin's source index."""
    if str(segment.get("segment_type") or "").lower() == "rest":
        duration_min = segment.get("elapsed_duration_min")
        if duration_min is None:
            duration_min = segment.get("duration_min")
        duration = _format_duration(duration_min)
        return f"休息｜{duration}" if duration is not None else "休息"

    details: list[str] = []
    distance = _format_distance(segment.get("distance_km"))
    if distance:
        details.append(distance)

    duration = _format_duration(segment.get("duration_min"))
    if duration:
        details.append(duration)

    pace = _swimming_pace_detail(segment.get("avg_pace"))
    if pace:
        details.append(pace if compact else f"配速 {pace}")

    avg_hr = segment.get("avg_hr")
    if avg_hr is not None:
        details.append(f"HR {avg_hr}" if compact else f"心率 {avg_hr} bpm")

    # A valid dict always remains visible, even when Garmin supplied no metrics.
    return "｜".join(details) or "分段"


def _append_blank_line(lines: list[str], *, dense: bool) -> None:
    if not dense and lines and lines[-1] != "":
        lines.append("")


def _build_swimming_overview_lines(
    activity: dict[str, Any],
    week: dict[str, Any] | None,
    *,
    dense: bool,
) -> list[str]:
    date_str = activity.get("date", "")
    lines = [f"{_sport_emoji('swimming')} 游泳｜{date_str}"]
    _append_blank_line(lines, dense=dense)

    distance_km = activity.get("distance_km")
    distance = _format_distance(distance_km)
    if distance:
        lines.append(f"距離：{distance}")

    elapsed_duration = activity.get("elapsed_duration_min")
    elapsed = _format_duration(elapsed_duration)
    if elapsed is not None:
        lines.append(f"總時間：{elapsed}")

    swim_duration = activity.get("swim_duration_min")
    rest_duration = activity.get("rest_duration_min")
    has_reliable_breakdown = swim_duration is not None and rest_duration is not None
    if has_reliable_breakdown:
        swim = _format_duration(swim_duration)
        rest = _format_duration(rest_duration)
        if swim is not None:
            lines.append(f"游泳時間：{swim}")
        if rest is not None:
            lines.append(f"休息時間：{rest}")

        swim_pace = _format_pace_seconds_per_100m(
            activity.get("swim_pace_seconds_per_100m")
        )
        if swim_pace:
            lines.append(f"平均游泳配速：{swim_pace}/100m")

    elapsed_pace = _format_pace_seconds_per_100m(
        activity.get("elapsed_pace_seconds_per_100m")
    )
    if elapsed_pace:
        lines.append(f"含休息平均配速：{elapsed_pace}/100m")

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

    if week is not None and week.get("derived_training_load") is not None:
        _append_blank_line(lines, dense=dense)
        lines.append("📊 本週累積")
        lines.append(f"訓練負荷：{_format_load(week.get('derived_training_load'))}")

    url = _garmin_activity_url(activity.get("activity_id"))
    if url:
        _append_blank_line(lines, dense=dense)
        lines.append(f"🔗 {url}")

    return lines


def _build_swimming_detail_lines(
    activity: dict[str, Any],
    *,
    compact: bool,
) -> list[str]:
    segments = activity.get("segments")
    if not isinstance(segments, list):
        return []

    segment_lines = [
        _format_swimming_segment(segment, compact=compact)
        for segment in segments
        if isinstance(segment, dict)
    ]
    return ["分段明細", *segment_lines] if segment_lines else []


def _combine_message_lines(
    overview_lines: list[str],
    detail_lines: list[str],
    *,
    dense: bool,
) -> str:
    lines = list(overview_lines)
    if detail_lines:
        _append_blank_line(lines, dense=dense)
        lines.extend(detail_lines)
    return "\n".join(line for line in lines if not dense or line != "")


def _paginate_complete_lines(lines: list[str]) -> list[str]:
    """Paginate without deleting, merging, or splitting any output line."""
    pages: list[str] = []
    current: list[str] = []
    current_length = 0

    for line in lines:
        line_length = utf16_length(line)
        if line_length > LINE_SAFE_TEXT_LENGTH:
            raise ValueError("A formatted LINE output line exceeds the safe length limit")
        added_length = line_length + (1 if current else 0)
        if current and current_length + added_length > LINE_SAFE_TEXT_LENGTH:
            pages.append("\n".join(current))
            current = [line]
            current_length = line_length
        else:
            current.append(line)
            current_length += added_length

    if current:
        pages.append("\n".join(current))
    return pages


def _format_swimming_messages(
    activity: dict[str, Any],
    week: dict[str, Any] | None,
) -> list[str]:
    rich_overview = _build_swimming_overview_lines(activity, week, dense=False)
    rich_details = _build_swimming_detail_lines(activity, compact=False)
    rich_message = _combine_message_lines(rich_overview, rich_details, dense=False)
    if utf16_length(rich_message) <= LINE_SAFE_TEXT_LENGTH:
        return [rich_message]

    compact_details = _build_swimming_detail_lines(activity, compact=True)
    compact_message = _combine_message_lines(rich_overview, compact_details, dense=False)
    if utf16_length(compact_message) <= LINE_SAFE_TEXT_LENGTH:
        return [compact_message]

    dense_overview = _build_swimming_overview_lines(activity, week, dense=True)
    dense_message = _combine_message_lines(dense_overview, compact_details, dense=True)
    if utf16_length(dense_message) <= LINE_SAFE_TEXT_LENGTH:
        return [dense_message]

    overview_message = "\n".join(dense_overview)
    if utf16_length(overview_message) > LINE_SAFE_TEXT_LENGTH:
        raise ValueError("Swimming activity overview exceeds the safe LINE length limit")

    return [overview_message, *_paginate_complete_lines(compact_details)]


def _format_strength_messages(
    activity: dict[str, Any],
    week: dict[str, Any] | None,
) -> list[str]:
    """Show compact strength facts; individual exercise sets stay in the AI input."""
    lines = [f"{_sport_emoji(_STRENGTH_SOURCE_TYPE)} 肌力訓練｜{activity.get('date', '')}", ""]
    duration = _format_duration(activity.get("duration_min"))
    if duration:
        lines.append(f"時間：{duration}")
    avg_hr = activity.get("avg_hr")
    if avg_hr is not None:
        lines.append(f"平均心率：{avg_hr} bpm")
    load = _format_load(activity.get("training_load"))
    if load:
        lines.append(f"訓練負荷：{load}")
    strength = activity.get("strength")
    if isinstance(strength, Mapping):
        total_sets = strength.get("total_sets")
        total_reps = strength.get("total_reps")
        if total_sets is not None:
            lines.append(f"總組數：{total_sets}")
        if total_reps is not None:
            lines.append(f"總次數：{total_reps}")
        volume = _weekly_number(strength.get("total_volume_kg"), digits=2)
        if volume is not None:
            lines.append(f"總容量：{volume} kg")
    if week is not None and week.get("derived_training_load") is not None:
        lines.extend(["", "📊 本週累積", f"訓練負荷：{_format_load(week.get('derived_training_load'))}"])
    url = _garmin_activity_url(activity.get("activity_id"))
    if url:
        lines.extend(["", f"🔗 {url}"])
    message = "\n".join(lines)
    if utf16_length(message) <= LINE_SAFE_TEXT_LENGTH:
        return [message]
    return _paginate_complete_lines(lines)


# ──────────────────────────────────────────────────────────────────────────────
# 主格式化函式
# ──────────────────────────────────────────────────────────────────────────────

def _format_legacy_activity_message(
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
        elif _is_swimming_source_type(source_type):
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


def format_activity_messages(
    activity: dict[str, Any],
    week: dict[str, Any] | None,
) -> list[str]:
    """Format one activity into transport-ready LINE text messages.

    Swimming owns its compact formatting and safe pagination here. Other
    sports retain the legacy single-message output byte for byte.
    """
    source_type = str(activity.get("source_activity_type") or "").lower()
    if source_type in _SWIMMING_SOURCE_TYPES:
        return _format_swimming_messages(activity, week)
    if source_type == _STRENGTH_SOURCE_TYPE:
        return _format_strength_messages(activity, week)

    legacy_message = _format_legacy_activity_message(activity, week)
    if utf16_length(legacy_message) <= LINE_SAFE_TEXT_LENGTH:
        return [legacy_message]
    return _paginate_complete_lines(legacy_message.split("\n"))


def format_activity_coach_messages(
    activity: dict[str, Any],
    week: dict[str, Any] | None,
    *,
    analysis: str,
) -> list[str]:
    """Append persisted AI coaching without changing deterministic activity pages."""
    if not isinstance(analysis, str) or not analysis.strip():
        raise ValueError("Activity AI analysis is required")
    coach_message = f"🤖 AI 教練\n\n{analysis.strip()}"
    if utf16_length(coach_message) > LINE_SAFE_TEXT_LENGTH:
        raise ValueError("Activity AI analysis exceeds the safe LINE length limit")
    return [*format_activity_messages(activity, week), coach_message]


def format_activity_message(
    activity: dict[str, Any],
    week: dict[str, Any] | None,
) -> str:
    """Backward-compatible single-string formatter interface."""
    messages = format_activity_messages(activity, week)
    return "\n".join(messages)


# ──────────────────────────────────────────────────────────────────────────────
# 每週訓練報告
# ──────────────────────────────────────────────────────────────────────────────

def _weekly_number(value: Any, *, digits: int = 1) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _weekly_plan_lines(
    seed: Mapping[str, Any],
    plan: Sequence[Any],
) -> list[str]:
    days = seed.get("days")
    if not isinstance(days, list) or len(days) != 7 or len(plan) != 7:
        raise ValueError("Weekly report requires a seven-day deterministic plan")
    lines: list[str] = []
    for day, suggestion in zip(days, plan, strict=True):
        if not isinstance(day, Mapping) or not isinstance(suggestion, Mapping):
            raise ValueError("Weekly report plan entries must be objects")
        day_of_week = day.get("day_of_week")
        date_value = day.get("date")
        session = suggestion.get("session")
        description = suggestion.get("description")
        if not all(isinstance(value, str) and value.strip() for value in (day_of_week, date_value, session, description)):
            raise ValueError("Weekly report plan is incomplete")
        lines.append(f"• {day_of_week} {date_value}｜{session}：{description}")
    return lines


def format_weekly_report_messages(
    summary_json: Mapping[str, Any],
    *,
    report_text: str,
    report_json: Mapping[str, Any] | None,
) -> list[str]:
    """Format deterministic weekly facts plus a persisted AI interpretation.

    Dates, aggregates and training load are always read from ``summary_json``.
    The model can contribute only the analysis, recommendation and per-day plan
    wording.  Pagination keeps every persisted LINE page below the safe limit.
    """
    if not isinstance(report_json, Mapping):
        raise ValueError("Weekly AI report is missing its structured output")
    week_start = summary_json.get("week_start")
    week_end = summary_json.get("week_end")
    totals = summary_json.get("totals")
    sports = summary_json.get("sports")
    load = summary_json.get("training_load")
    plan_seed = summary_json.get("next_week_plan_seed")
    analysis = report_json.get("analysis")
    recommendation = report_json.get("recommendation")
    plan = report_json.get("next_week_plan")
    if not all(isinstance(value, str) and value.strip() for value in (week_start, week_end, analysis, recommendation, report_text)):
        raise ValueError("Weekly report is missing required text")
    if not isinstance(totals, Mapping) or not isinstance(sports, list) or not isinstance(load, Mapping) or not isinstance(plan_seed, Mapping) or not isinstance(plan, list):
        raise ValueError("Weekly report is missing deterministic facts")

    lines = [f"📊 週訓練報告｜{week_start}～{week_end}", "", "訓練總覽"]
    workout_count = totals.get("workout_count")
    distance = _weekly_number(totals.get("distance_km"), digits=2)
    duration = _weekly_number(totals.get("duration_min"))
    overview = [
        f"{workout_count} 次" if isinstance(workout_count, int) else None,
        f"{distance} km" if distance is not None else None,
        f"{duration} 分" if duration is not None else None,
    ]
    lines.append(f"• 總計：{'｜'.join(item for item in overview if item)}")
    for sport in sports:
        if not isinstance(sport, Mapping):
            continue
        name = sport.get("display_name")
        count = sport.get("count")
        distance = _weekly_number(sport.get("distance_km"), digits=2)
        duration = _weekly_number(sport.get("duration_min"))
        if isinstance(name, str) and isinstance(count, int):
            details = [f"{count} 次"]
            if distance is not None:
                details.append(f"{distance} km")
            if duration is not None:
                details.append(f"{duration} 分")
            lines.append(f"• {name}：{'｜'.join(details)}")

    lines.extend(["", "Garmin 訓練負荷"])
    weekly_load = _weekly_number(load.get("garmin_weekly_load"))
    if weekly_load is not None:
        lines.append(f"• 本週負荷：{weekly_load}")
    chronic_load = _weekly_number(load.get("chronic_load"))
    if chronic_load is not None:
        lines.append(f"• 近期基準：{chronic_load}")
    ratio = _weekly_number(load.get("acute_chronic_ratio"), digits=2)
    if ratio is not None:
        lines.append(f"• 急慢性負荷比：{ratio}")

    lines.extend(["", "🤖 AI 教練", analysis.strip(), "", f"建議：{recommendation.strip()}", "", "📅 下一週課表"])
    lines.extend(_weekly_plan_lines(plan_seed, plan))
    return _paginate_complete_lines(lines)
