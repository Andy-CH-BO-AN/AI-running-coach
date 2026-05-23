import os
import time
import logging
import random
from typing import List, Dict, Any, Optional
from garminconnect import Garmin
from dotenv import load_dotenv
from datetime import date as date_cls, datetime, timedelta
from src.preprocessing.data_processor import calculate_pace, should_skip_short_cycling

load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Configuration constants
API_RETRY_MAX = 3
API_RETRY_BACKOFF_BASE = 2
GARMIN_PR_MAPS = {
    "RUNNING": {
        1: '1km', 2: '1mile', 3: '5km', 4: '10km', 
        5: 'half_marathon', 6: 'marathon', 7: 'longest_run'
    },
    "SWIMMING": {
        17: 'longest_swim', 18: '100m_swim', 20: '400m_swim', 22: '750m_swim'
    },
    "CYCLING": {
        8: 'longest_ride'
    },
    "MISC": {
        13: 'max_ascent', 14: 'monthly_max_steps', 15: 'goal_streak'
    }
}
TARGET_ACTIVITY_TYPES = {'running': 'running', 'lap_swimming': 'swimming', 'cycling': 'cycling'}
RUNNING_PR_DISTANCES_KM = {
    1: 1.0,
    2: 1.60934,
    3: 5.0,
    4: 10.0,
    5: 21.0975,
    6: 42.195,
}

def safe_api_call(func, *args, **kwargs) -> Any:
    """具備指數退避邏輯的 API 呼叫包裝器"""
    for attempt in range(API_RETRY_MAX):
        try:
            result = func(*args, **kwargs)
            # 只要不是 None 就回傳，如果是空串列/字典也算成功
            return result if result is not None else {}
        except Exception as e:
            if attempt < API_RETRY_MAX - 1:
                # 修正 random 呼叫方式
                wait_time = (API_RETRY_BACKOFF_BASE ** attempt) + random.uniform(0, 1)
                logger.warning(f"API 重試中 {attempt + 1}/{API_RETRY_MAX}，等待 {wait_time:.1f}s: {e}")
                time.sleep(wait_time)
            else:
                logger.error(f"API 呼叫徹底失敗: {e}")
                return None

def get_user_biometric_data(client):
    data = {
        'max_heart_rate': None,
        'resting_heart_rate': None,
        'vo2max_running': None,
        'lactate_threshold_speed_mps': None,   # m/s，原始值
        'lactate_threshold_pace': None,         # 格式化 MM:SS /km
        'lactate_threshold_heart_rate': None,
        'weight_kg': None,
        'height_cm': None,
        'available_training_days': [],
        'preferred_long_training_days': [],
        'pr_running': {}, 'pr_swimming': {}, 'pr_cycling': {}
    }

    today = datetime.now().date().isoformat()
    
    rhr_response = client.get_rhr_day(today)

    if rhr_response:
        try:
            rhr = (
                rhr_response["allMetrics"]["metricsMap"]
                ["WELLNESS_RESTING_HEART_RATE"][0]["value"]
            )
        except (KeyError, IndexError, TypeError):
            rhr = None
    else:
        rhr = None
    
    profile = client.get_user_profile()
    if profile:
        data['max_heart_rate'] = profile.get('maxHeartRate')
        if not rhr:
            rhr = profile.get('restingHeartRate')
        
        # 從 userData 抓進階生理數據
        user_data_raw = profile.get('userData', {})
        if user_data_raw:
            data['vo2max_running'] = user_data_raw.get('vo2MaxRunning')
            data['lactate_threshold_heart_rate'] = user_data_raw.get('lactateThresholdHeartRate')
            
            # 體重 (g -> kg)、身高 (cm)
            weight_g = user_data_raw.get('weight')
            if weight_g:
                data['weight_kg'] = round(weight_g / 1000, 1)
            data['height_cm'] = user_data_raw.get('height')
            
            # 乳酸閾值配速
            # Garmin API 的 lactateThresholdSpeed 單位實測為 m/s 但數值縮小 10 倍
            # 0.3778 × 10 = 3.778 m/s → 264.7 sec/km → 4:24 /km（符合你的半馬配速附近）
            lt_speed = user_data_raw.get('lactateThresholdSpeed')
            if lt_speed and lt_speed > 0:
                data['lactate_threshold_speed_mps'] = lt_speed
                corrected_speed = lt_speed * 10  # 修正縮放
                pace_sec_per_km = 1000 / corrected_speed
                lt_min = int(pace_sec_per_km // 60)
                lt_sec = int(pace_sec_per_km % 60)
                data['lactate_threshold_pace'] = f"{lt_min}:{lt_sec:02d} /km"
            
            # 訓練日偏好
            data['available_training_days'] = user_data_raw.get('availableTrainingDays', [])
            data['preferred_long_training_days'] = user_data_raw.get('preferredLongTrainingDays', [])
    
    data['resting_heart_rate'] = rhr

    # 處理個人紀錄
    pr_records = client.get_personal_record()
    if pr_records:
        for record in pr_records:
            tid, val = record.get('typeId'), record.get('value')
            if tid is None or val is None: continue
            
            f_val, pace = format_garmin_value(val, tid)
            display = f"{f_val} ({pace})" if pace else f_val

            if tid in GARMIN_PR_MAPS["RUNNING"]:
                data['pr_running'][GARMIN_PR_MAPS["RUNNING"][tid]] = display
            elif tid in GARMIN_PR_MAPS["SWIMMING"]:
                data['pr_swimming'][GARMIN_PR_MAPS["SWIMMING"][tid]] = display
            elif tid in GARMIN_PR_MAPS["CYCLING"]:
                data['pr_cycling'][GARMIN_PR_MAPS["CYCLING"][tid]] = display
            elif tid in GARMIN_PR_MAPS["MISC"]:
                data[GARMIN_PR_MAPS["MISC"][tid]] = display
    return data


def format_garmin_value(value, typeId):
    """
    客製化格式化函數：
    1. 自動計算配速 (/km)
    2. 自動修正單位：功率 (mW -> W), 距離 (m -> km)
    3. 修正 7, 8 號紀錄的誤植問題
    """
    # --- 1. 跑步與一般時間類 (1km, 1mile, 5km, 10km, 半馬, 全馬) ---
    if typeId in RUNNING_PR_DISTANCES_KM:
        total_seconds = round(value)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        formatted_value = f"{minutes}:{seconds:02d}"

        distance_km = RUNNING_PR_DISTANCES_KM.get(typeId)
        pace = ""
        if distance_km:
            p_sec = total_seconds / distance_km
            pace = f"{int(p_sec // 60)}:{int(p_sec % 60):02d} /km"

        return formatted_value, pace

    # --- 2. 距離類 (最長跑步, 最長騎乘) ---
    if typeId in [7, 8]:
        # 你的數據顯示 7 號是 21334.5 (m)，所以要除以 1000
        value_km = value / 1000
        return f"{value_km:.2f} km", ""

    # --- 3. 單月最多步數 ---
    if typeId == 14:
        return f"{int(value):,} 步", ""

    # --- 4. 游泳類 (100m, 400m, 750m) ---
    if typeId in [18, 20, 22]:
        total_seconds = round(value)
        return f"{total_seconds // 60}:{total_seconds % 60:02d}", ""

    # --- 4b. 游泳最長距離 (typeId 17, 單位 m) ---
    if typeId == 17:
        return f"{int(value)} m", ""

    # --- 5. 爬升類 ---
    if typeId == 13:
        if value > 5000:
            val_m = int(value // 1000)
        else:
            val_m = int(value)
        return f"{val_m} m", ""

    # --- 6. 連續目標天數（整數顯示）---
    if typeId == 15:
        return f"{int(value)} 天", ""

    # 預設直接回傳（整數就不顯示小數）
    if value == int(value):
        return str(int(value)), ""
    return str(round(value, 2)), ""

def _find_nested_value(data: Any, target_key: str) -> Any:
    """Recursively search dict/list payloads and return the first non-None match."""
    if isinstance(data, dict):
        if target_key in data and data[target_key] is not None:
            return data[target_key]

        for value in data.values():
            found = _find_nested_value(value, target_key)
            if found is not None:
                return found

    elif isinstance(data, list):
        for item in data:
            found = _find_nested_value(item, target_key)
            if found is not None:
                return found

    return None

def _get_activity_value(source: Any, *keys: str) -> Any:
    """Fetch the first matching value from a Garmin activity payload."""
    for key in keys:
        value = _find_nested_value(source, key)
        if value is not None:
            return value
    return None

def _extract_zone_seconds(zone_payload: Any, zone_base: str) -> Dict[str, Any]:
    """
    Normalize Garmin time-in-zone payloads.

    Expected API payload shape:
      [
        {"zoneNumber": 1, "secsInZone": 273.906, ...},
        ...
      ]

    Returns both the internal normalized keys and Garmin-compatible keys.
    """
    zone_data = {f'{zone_base}_zone_{i}': None for i in range(1, 6)}
    zone_data.update({f'{zone_base}TimeInZone_{i}': None for i in range(1, 6)})

    if isinstance(zone_payload, list):
        for entry in zone_payload:
            if not isinstance(entry, dict):
                continue
            zone_number = entry.get('zoneNumber')
            secs_in_zone = entry.get('secsInZone')
            if zone_number in range(1, 6):
                zone_data[f'{zone_base}_zone_{zone_number}'] = secs_in_zone
                zone_data[f'{zone_base}TimeInZone_{zone_number}'] = secs_in_zone
        return zone_data

    if isinstance(zone_payload, dict):
        for i in range(1, 6):
            zone_data[f'{zone_base}_zone_{i}'] = _get_activity_value(
                zone_payload,
                f'{zone_base}TimeInZone_{i}',
                f'{zone_base}_zone_{i}',
                f'secsInZone_{i}',
                f'zone_{i}',
            )
            zone_data[f'{zone_base}TimeInZone_{i}'] = zone_data[f'{zone_base}_zone_{i}']

    return zone_data

def _log_activity_payload_debug(activity_id: int, activity_type: str, sources: Dict[str, Any]) -> None:
    """Print payload shapes and zone candidates when debug mode is enabled."""
    if not os.getenv('GARMIN_DEBUG_ACTIVITY_DETAILS'):
        return

    print(f"\n[garmin_debug] activity_id={activity_id} activity_type={activity_type}")
    for source_name, payload in sources.items():
        if isinstance(payload, dict):
            print(f"[garmin_debug] {source_name} top-level keys: {list(payload.keys())}")
        elif isinstance(payload, list):
            print(f"[garmin_debug] {source_name} list length: {len(payload)}")
        else:
            print(f"[garmin_debug] {source_name}: {type(payload).__name__}")

    hr_map = _extract_zone_seconds(sources.get('hr_timezones'), 'hr')
    power_map = _extract_zone_seconds(sources.get('power_timezones'), 'power')
    print(f"[garmin_debug] hr_timezones normalized: {hr_map}")
    print(f"[garmin_debug] power_timezones normalized: {power_map}")

def get_activity_details(client: Garmin, activity_id: int, activity_type: str) -> Dict[str, Any]:
    details = {}
    full_detail = safe_api_call(client.get_activity, activity_id)
    if not full_detail: return details

    hr_timezones = safe_api_call(client.get_activity_hr_in_timezones, activity_id)
    power_timezones = safe_api_call(client.get_activity_power_in_timezones, activity_id)

    sources = {
        'activity': full_detail,
        'hr_timezones': hr_timezones,
        'power_timezones': power_timezones,
    }

    # Garmin 的 activity payload 可能出現在頂層、summaryDTO、activity_info，
    # 也可能在獨立 time-zone endpoint，所以統一做遞迴查找。
    def get_value(*keys: str) -> Any:
        for source in sources.values():
            value = _get_activity_value(source, *keys)
            if value is not None:
                return value
        return None

    # 溫度：取 min/max 平均
    min_temp = get_value('minTemperature')
    max_temp = get_value('maxTemperature')
    if min_temp is not None and max_temp is not None:
        avg_temp = round((min_temp + max_temp) / 2, 1)
    else:
        avg_temp = min_temp if min_temp is not None else max_temp

    # HR / power zone 秒數：主要來源是獨立 time-in-zone endpoint
    hr_zones = _extract_zone_seconds(hr_timezones, 'hr')
    power_zones = _extract_zone_seconds(power_timezones, 'power')

    # 如果 endpoint 沒回資料，才從 activity payload 補抓一次
    if not any(v is not None for v in hr_zones.values()):
        hr_zones = _extract_zone_seconds(full_detail, 'hr')
    if not any(v is not None for v in power_zones.values()):
        power_zones = _extract_zone_seconds(full_detail, 'power')

    _log_activity_payload_debug(activity_id, activity_type, sources)

    details.update({
        'elevation_gain': get_value('elevationGain'),
        'elevation_loss': get_value('elevationLoss'),
        'temperature': avg_temp,
        'training_stress_score': get_value('activityTrainingLoad'),
        'intensity_factor': get_value('intensityFactor'),
        'aerobic_training_effect': get_value('aerobicTrainingEffect'),
        'anaerobic_training_effect': get_value('anaerobicTrainingEffect'),
        **hr_zones,
        **power_zones,
    })

    if activity_type == 'running':
        # averageRunningCadenceInStepsPerMinute 是單腳 spm，×2 才是雙腳 spm
        raw_cadence = get_value('averageRunCadence', 'averageRunningCadenceInStepsPerMinute')
        raw_max_cad = get_value('maxRunCadence', 'maxRunningCadenceInStepsPerMinute', 'maxDoubleCadence')
        details.update({
            'cadence': raw_cadence,
            'max_cadence': raw_max_cad,  # maxDoubleCadence 已是雙腳，不需 ×2
            'stride_length': get_value('avgStrideLength', 'strideLength'),
            'power_avg': get_value('avgPower', 'averagePower'),
            'power_max': get_value('maxPower'),
            'vertical_oscillation': get_value('avgVerticalOscillation', 'verticalOscillation'),
            'ground_contact_time': get_value('avgGroundContactTime', 'groundContactTime'),
            'vertical_ratio': get_value('avgVerticalRatio', 'verticalRatio'),
            **power_zones,
        })
    elif activity_type == 'swimming':
        details.update({
            'avg_swolf': get_value('averageSWOLF', 'avgSWOLF', 'averageSwolf'),
            'total_strokes': get_value('totalNumberOfStrokes'),
            'avg_stroke_cadence': get_value('averageSwimCadence', 'averageSwimCadenceInStrokesPerMinute'),
        })
    elif activity_type == 'cycling':
        details.update({
            'power_avg': get_value('avgPower', 'averagePower'),
            'power_max': get_value('maxPower'),
            'cadence': get_value('averageBikeCadence', 'avgCadence'),
            **power_zones,
        })
    return details

def get_activity_splits(client: Garmin, activity_id: int, activity_type: str = 'running') -> List[Dict[str, Any]]:
    splits = []
    splits_data = safe_api_call(client.get_activity_splits, activity_id)
    if not splits_data: return splits

    lap_dtos = splits_data.get('lapDTOs', [])
    for idx, lap in enumerate(lap_dtos, 1):
        dist, dur = lap.get('distance', 0), lap.get('duration', 0)
        if dur < 1 or dist < 1: continue

        # 步頻：Garmin averageRunCadence 已經是雙腳 spm，直接用
        # 低步頻（間歇休息/走路）屬於正常數據，不過濾
        raw_cad = (lap.get('averageRunCadence') or lap.get('averageBikeCadence') or
                   lap.get('averageSwimCadence') or lap.get('avgCadence'))
        raw_max_cad = (lap.get('maxRunCadence') or lap.get('maxBikeCadence') or lap.get('maxCadence'))

        split = {
            'split_index': idx,
            'distance': dist / 1000,
            'duration': dur / 60,
            'pace': None if activity_type == 'cycling' else calculate_pace(dur * 1000, dist, activity_type),
            'average_heart_rate': lap.get('averageHR'),
            'max_heart_rate': lap.get('maxHR'),
            'avg_cadence': raw_cad,
            'max_cadence': raw_max_cad,
            'temperature': lap.get('averageTemperature'),
        }

        if activity_type == 'running':
            split.update({
                'stride_length': lap.get('strideLength'),
                'ground_contact_time': lap.get('groundContactTime'),
                'vertical_oscillation': lap.get('verticalOscillation'),
                'vertical_ratio': lap.get('verticalRatio'),
                'power_avg': lap.get('averagePower'),
                'power_max': lap.get('maxPower'),
            })
        elif activity_type == 'swimming':
            # 每圈的泳姿、SWOLF、划手數
            split.update({
                'swim_stroke': lap.get('swimStroke'),
                'avg_swolf': lap.get('averageSWOLF'),
                'total_strokes': lap.get('totalNumberOfStrokes'),
                'active_lengths': lap.get('numberOfActiveLengths'),
                # lengthDTOs：每 25m 一筆，含泳姿 + 每趟 SWOLF
                'lengths': [
                    {
                        'length_index': ln.get('lengthIndex'),
                        'distance': ln.get('distance'),
                        'duration': ln.get('duration'),
                        'swim_stroke': ln.get('swimStroke'),
                        'strokes': ln.get('totalNumberOfStrokes'),
                        'swolf': ln.get('averageSWOLF'),
                        'avg_hr': ln.get('averageHR'),
                    }
                    for ln in lap.get('lengthDTOs', [])
                ],
            })
        elif activity_type == 'cycling':
            split.update({
                'power_avg': lap.get('averagePower'),
                'power_max': lap.get('maxPower'),
                'elevation_gain': lap.get('elevationGain'),
                'elevation_loss': lap.get('elevationLoss'),
                'speed_kmh': calculate_pace(dur * 1000, dist, activity_type),
            })

        splits.append(split)
    return splits

def _parse_activity_date(activity: Dict[str, Any]) -> Optional[date_cls]:
    value = activity.get('startTimeLocal') or activity.get('date')
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def get_garmin_activities(
    n: Optional[int] = 30,
    progress: bool = False,
    since_date: Optional[date_cls] = None,
    fallback_max_heart_rate: Optional[float] = None,
) -> Dict[str, Any]:
    email, password = os.getenv('GARMIN_ACCOUNT'), os.getenv('GARMIN_PASSWORD')
    if not email or not password:
        logger.error("帳號密碼未設定")
        return {'activities': [], 'user_data': {}}

    if progress:
        types = ", ".join(TARGET_ACTIVITY_TYPES.values())
        since_text = f"; since_date>={since_date.isoformat()}" if since_date else ""
        target_count = 999 if n is None else max(n, 0)
        print(f"🔐 Garmin login starting; target activities={target_count}; types={types}{since_text}", flush=True)
    client = Garmin(email, password)
    client.login()

    if progress:
        print("✅ Garmin login completed; fetching user profile/biometrics", flush=True)
    # 抓取生理數據
    user_data = get_user_biometric_data(client)
    user_data['max_heart_rate'] = max(
        user_data.get('max_heart_rate') or 0,
        fallback_max_heart_rate or 0,
    ) or None

    collected_activities = []
    start, page_size = 0, 50
    target_types = TARGET_ACTIVITY_TYPES
    target_count = 999 if n is None else max(n, 0)

    while len(collected_activities) < target_count:
        if progress:
            print(
                f"📄 Fetching Garmin activities page start={start}, collected={len(collected_activities)}",
                flush=True,
            )
        activities = safe_api_call(client.get_activities, start, page_size)
        if not activities: break

        stop_after_page = False
        for activity in activities:
            if len(collected_activities) >= target_count: break

            activity_date = _parse_activity_date(activity)
            if since_date and activity_date and activity_date < since_date:
                stop_after_page = True
                if progress:
                    print(
                        f"🧭 Reached activity date {activity_date.isoformat()} before "
                        f"since_date {since_date.isoformat()}; stopping incremental fetch.",
                        flush=True,
                    )
                break

            max_hr = max(
                user_data.get('max_heart_rate') or 0, 
                activity.get('maxHR') or 0
            )
            user_data['max_heart_rate'] = max_hr
            
            type_info = activity.get('activityType', {})
            type_key = type_info.get('typeKey') if isinstance(type_info, dict) else type_info
            
            if type_key in target_types:
                act_id = activity.get('activityId')
                act_type = target_types[type_key]
                dist_m, dur_s = activity.get('distance', 0), activity.get('duration', 0)
                distance_km = dist_m / 1000 if dist_m is not None else None
                if should_skip_short_cycling(act_type, distance_km):
                    if progress:
                        print(
                            f"  ↳ Skipping short cycling activity={act_id} "
                            f"distance={distance_km:.2f}km",
                            flush=True,
                        )
                    continue

                performance_value = calculate_pace(dur_s * 1000, dist_m, act_type)
                raw_details = get_activity_details(client, act_id, act_type)
                if act_type == 'cycling':
                    raw_details['average_speed_kmh'] = performance_value

                if progress:
                    print(
                        f"  ↳ Fetching {act_type} activity={act_id} date={activity.get('startTimeLocal', '')[:10]} "
                        f"({len(collected_activities) + 1}/{target_count})",
                        flush=True,
                    )
                collected_activities.append({
                    'type': act_type,
                    'date': activity.get('startTimeLocal', '')[:10],
                    'distance': distance_km,
                    'duration': dur_s / 60,
                    'average_pace': None if act_type == 'cycling' else performance_value,
                    'average_heart_rate': activity.get('averageHR'),
                    'activity_id': act_id,
                    'splits': get_activity_splits(client, act_id, act_type),
                    'raw_data': raw_details,
                })
        
        start += page_size
        if stop_after_page: break
        if len(activities) < page_size: break

    
    print(f"✅ 成功抓取 {len(collected_activities)} 筆活動並完成數據校正")
    return {'activities': collected_activities, 'user_data': user_data}
