import os
import time
import logging
import random
from typing import List, Dict, Any, Optional
from garminconnect import Garmin
from dotenv import load_dotenv
from datetime import datetime, timedelta
from src.preprocessing.data_processor import calculate_pace

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
        18: '100m_swim', 20: '400m_swim', 22: '750m_swim'
    },
    "CYCLING": {
        8: 'longest_ride', 14: '20min_max_power'
    },
    "MISC": {
        13: 'max_ascent', 15: 'goal_streak'
    }
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
    # --- 1. 跑步與一般時間類 (1km, 1mile, 5km, 10km, 半馬) ---
    if typeId in [1, 2, 3, 4, 5]:
        total_seconds = round(value)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        formatted_value = f"{minutes}:{seconds:02d}"
        
        # 計算配速邏輯
        if typeId == 1: # 1K
            pace = f"{formatted_value} /km"
        elif typeId == 2: # 1mile
            p_sec = total_seconds / 1.60934
            pace = f"{int(p_sec // 60)}:{int(p_sec % 60):02d} /km"
        elif typeId == 3: # 5k
            p_sec = total_seconds / 5
            pace = f"{int(p_sec // 60)}:{int(p_sec % 60):02d} /km"
        elif typeId == 4: # 10k
            p_sec = total_seconds / 10
            pace = f"{int(p_sec // 60)}:{int(p_sec % 60):02d} /km"
        elif typeId == 5: # Half
            p_sec = total_seconds / 21.0975
            pace = f"{int(p_sec // 60)}:{int(p_sec % 60):02d} /km"
        elif typeId == 6: # Marathon
            p_sec = total_seconds / 42.195
            pace = f"{int(p_sec // 60)}:{int(p_sec % 60):02d} /km"
        
        return formatted_value, pace

    # --- 2. 距離類 (最長跑步, 最長騎乘) ---
    if typeId in [7, 8]:
        # 你的數據顯示 7 號是 21334.5 (m)，所以要除以 1000
        value_km = value / 1000
        return f"{value_km:.2f} km", ""

    # --- 3. 功率類 (20min 最大功率) ---
    if typeId == 14:
        # 修正 mW -> W 的問題 (你的數據 519438.0)
        if value > 5000:
            val_w = int(value // 1000)
        else:
            val_w = int(value)
        return f"{val_w} W", ""

    # --- 4. 游泳類 (100m, 400m, 750m) ---
    if typeId in [18, 20, 22]:
        total_seconds = round(value)
        return f"{total_seconds // 60}:{total_seconds % 60:02d}", ""

    # --- 5. 爬升類 ---
    if typeId == 13:
        # 修正你的 154133.0 單位誤植問題
        if value > 5000:
            val_m = int(value // 1000)
        else:
            val_m = int(value)
        return f"{val_m} m", ""

    # 預設直接回傳
    return str(round(value, 2)), ""

def get_activity_details(client: Garmin, activity_id: int, activity_type: str) -> Dict[str, Any]:
    details = {}
    full_detail = safe_api_call(client.get_activity, activity_id)
    if not full_detail: return details
    
    summary = full_detail.get('summaryDTO', {})
    details.update({
        'elevation_gain': summary.get('elevationGain'),
        'elevation_loss': summary.get('elevationLoss'),
        'temperature': summary.get('averageTemperature'),
        'training_stress_score': summary.get('activityTrainingLoad'),
        'intensity_factor': summary.get('intensityFactor')
    })

    if activity_type == 'running':
        details.update({
            'cadence': summary.get('averageRunCadence'),
            'stride_length': summary.get('strideLength'),
            'power_avg': summary.get('averagePower')
        })
    elif activity_type == 'cycling':
        details['power_avg'] = summary.get('averagePower') or summary.get('avgPower')
        details['cadence'] = summary.get('averageBikeCadence') or summary.get('avgCadence')
    
    return details

def get_activity_splits(client: Garmin, activity_id: int) -> List[Dict[str, Any]]:
    splits = []
    splits_data = safe_api_call(client.get_activity_splits, activity_id)
    if not splits_data: return splits

    lap_dtos = splits_data.get('lapDTOs', [])
    for idx, lap in enumerate(lap_dtos, 1):
        dist, dur = lap.get('distance', 0), lap.get('duration', 0)
        if dur < 1 or dist < 1: continue
        
        cadence = (lap.get('averageRunCadence') or lap.get('averageBikeCadence') or 
                   lap.get('averageSwimCadence') or lap.get('avgCadence'))

        splits.append({
            'split_index': idx,
            'distance': dist / 1000,
            'duration': dur / 60,
            'pace': calculate_pace(dur * 1000, dist),
            'average_heart_rate': lap.get('averageHR'),
            'avg_cadence': cadence
        })
    return splits

def get_garmin_activities(n: Optional[int] = 30) -> Dict[str, Any]:
    email, password = os.getenv('GARMIN_ACCOUNT'), os.getenv('GARMIN_PASSWORD')
    if not email or not password:
        logger.error("帳號密碼未設定")
        return {'activities': [], 'user_data': {}}

    client = Garmin(email, password)
    client.login()
    
    # 抓取生理數據
    user_data = get_user_biometric_data(client)

    running_activities = []
    start, page_size = 0, 50

    while len(running_activities) < (n or 999):
        activities = safe_api_call(client.get_activities, start, page_size)
        if not activities: break

        for activity in activities:
            if len(running_activities) >= (n or 999): break
            max_hr = max(
                user_data.get('max_heart_rate') or 0, 
                activity.get('maxHR') or 0
            )
            user_data['max_heart_rate'] = max_hr
            
            type_info = activity.get('activityType', {})
            type_key = type_info.get('typeKey') if isinstance(type_info, dict) else type_info
            target_types = {'running': 'running', 'lap_swimming': 'swimming', 'cycling': 'cycling'}
            
            if type_key in target_types:
                act_id = activity.get('activityId')
                act_type = target_types[type_key]
                dist_m, dur_s = activity.get('distance', 0), activity.get('duration', 0)
                
                running_activities.append({
                    'type': act_type,
                    'date': activity.get('startTimeLocal', '')[:10],
                    'distance': dist_m / 1000,
                    'duration': dur_s / 60,
                    'average_pace': calculate_pace(dur_s * 1000, dist_m),
                    'average_heart_rate': activity.get('averageHR'),
                    'activity_id': act_id,
                    'splits': get_activity_splits(client, act_id),
                    'raw_data': get_activity_details(client, act_id, act_type)
                })
        
        start += page_size
        if len(activities) < page_size: break

    
    print(f"✅ 成功抓取 {len(running_activities)} 筆活動並完成數據校正")
    return {'activities': running_activities, 'user_data': user_data}