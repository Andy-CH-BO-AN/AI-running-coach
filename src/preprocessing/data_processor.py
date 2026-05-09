from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def calculate_pace(duration_ms: Optional[float], distance_m: Optional[float], activity_type: str = 'running') -> Optional[float]:
    if not duration_ms or not distance_m or distance_m <= 0:
        return None
    
    duration_min = duration_ms / 60000
    distance_km = distance_m / 1000

    if activity_type == 'running':
        pace = duration_min / distance_km
        # 取消 20.0 的限制，只要不是扯到天際（>100）都顯示出來
        return round(pace, 2) if pace < 100.0 else 99.99

    elif activity_type == 'swimming':
        distance_100m = distance_m / 100
        pace_100m = duration_min / distance_100m
        # 游泳同樣放寬門檻
        return round(pace_100m, 2) if pace_100m < 100.0 else 99.99

    elif activity_type == 'cycling':
        hours = duration_min / 60
        speed_kmh = distance_km / hours
        # 單車只要有在動 (時速 > 0.1) 就顯示
        return round(speed_kmh, 1) if speed_kmh > 0.1 else 0.1

    return None

def format_pace(value: Optional[float], activity_type: str = 'running') -> str:
    """格式化顯示：跑步/游泳轉成 MM:SS，單車保持 km/h"""
    if value is None:
        return "N/A"
    
    if activity_type == 'cycling':
        return f"{value} km/h"
    
    # 處理 MM:SS 格式 (適用於跑步與游泳)
    # 使用 divmod 確保秒數處理更乾淨
    total_seconds = int(round(value * 60))
    minutes, seconds = divmod(total_seconds, 60)
    
    suffix = "/100m" if activity_type == 'swimming' else "/km"
    return f"{minutes}:{seconds:02d} {suffix}"

def classify_runner_type(cadence: Optional[float]) -> Optional[str]:
    """
    根據步頻分類跑者類型
    目標步頻：180 spm (每分鐘步數)
    - 頻率型：>= 180 spm（步幅短、步頻快）
    - 力量型：< 180 spm（步幅長、步頻慢）
    
    Note: 180 spm 是一般建議; 精英跑者可能在160-170範圍內有效
    """
    if cadence is None:
        return None
    
    # 驗證合理範圍 (40-220 spm 是正常範圍)
    if cadence < 40:
        return "walking or resting"
    
    if cadence >= 180:
        return "frequency_runner"  # 頻率型
    else:
        return "power_runner"  # 力量型

def calculate_hrr(resting_hr: Optional[float], max_hr: Optional[float]) -> Optional[float]:
    """
    計算儲備心率 (Heart Rate Reserve)
    HRR = 最大心率 - 安靜心率
    這是計算心率區間的基礎
    """
    if not resting_hr or not max_hr:
        return None
    
    # 驗證合理範圍
    if resting_hr < 30 or resting_hr > 100:
        logger.warning(f"Unrealistic resting heart rate: {resting_hr}")
        return None
    
    if max_hr < 120 or max_hr > 230:
        logger.warning(f"Unrealistic max heart rate: {max_hr}")
        return None
    
    hrr = max_hr - resting_hr
    return round(hrr, 1) if hrr > 0 else None

def calculate_running_efficiency(vertical_oscillation: Optional[float], ground_contact_time: Optional[float]) -> Optional[Dict[str, Any]]:
    """
    評估跑步效率
    - 垂直振幅越小越好（不要跳太高），通常 6-10cm
    - 觸地時間越短越好（推蹬力量強），通常 200-300ms
    
    Grading:
        Oscillation: excellent <6, good <8, fair <10, poor >=10
        Contact Time: excellent <200, good <250, fair <300, poor >=300
    """
    efficiency = {}
    
    if vertical_oscillation is not None:
        # 驗證合理範圍 (0-20 cm)
        if vertical_oscillation < 0 or vertical_oscillation > 20:
            logger.warning(f"Unrealistic vertical oscillation: {vertical_oscillation} cm, skipping")
        else:
            if vertical_oscillation < 6:
                efficiency['oscillation_grade'] = "excellent"  # 卓越
            elif vertical_oscillation < 8:
                efficiency['oscillation_grade'] = "good"  # 良好
            elif vertical_oscillation < 10:
                efficiency['oscillation_grade'] = "fair"  # 一般
            else:
                efficiency['oscillation_grade'] = "poor"  # 不佳
            efficiency['vertical_oscillation'] = round(vertical_oscillation, 1)
    
    if ground_contact_time is not None:
        # 驗證合理範圍 (100-500 ms)
        if ground_contact_time < 100 or ground_contact_time > 500:
            logger.warning(f"Unrealistic ground contact time: {ground_contact_time} ms, skipping")
        else:
            if ground_contact_time < 200:
                efficiency['contact_grade'] = "excellent"
            elif ground_contact_time < 250:
                efficiency['contact_grade'] = "good"
            elif ground_contact_time < 300:
                efficiency['contact_grade'] = "fair"
            else:
                efficiency['contact_grade'] = "poor"
            efficiency['ground_contact_time'] = round(ground_contact_time, 1)
    
    return efficiency if efficiency else None

def calculate_cycling_efficiency(power_avg: Optional[float], power_max: Optional[float]) -> Optional[Dict[str, Any]]:
    """
    評估自行車騎行效率
    - Power Ratio (Max/Avg): 高比率表示有力量爆發能力
    """
    efficiency = {}
    
    if power_avg and power_max and power_avg > 0:
        # 驗證合理範圍
        if power_avg < 0 or power_avg > 2000 or power_max < 0 or power_max > 3000:
            logger.warning(f"Unrealistic power data: avg={power_avg}W, max={power_max}W")
            return None
        
        ratio = power_max / power_avg if power_avg > 0 else None
        if ratio:
            efficiency['power_ratio'] = round(ratio, 2)
            if ratio < 1.2:
                efficiency['power_consistency'] = "very_steady"  # 非常穩定
            elif ratio < 1.5:
                efficiency['power_consistency'] = "steady"  # 穩定
            elif ratio < 2.0:
                efficiency['power_consistency'] = "variable"  # 可變
            else:
                efficiency['power_consistency'] = "spiky"  # 多峰值
    
    return efficiency if efficiency else None

def calculate_swimming_efficiency(avg_swolf: Optional[float]) -> Optional[Dict[str, Any]]:
    """
    評估游泳效率 - SWOLF (Swim Golf) 分數
    SWOLF = 每 25 米所需的時間 + 每 25 米的划手數
    分數越低越好
    """
    efficiency = {}
    
    if avg_swolf is not None:
        # 驗證合理範圍 (一般 100-180)
        if avg_swolf < 50 or avg_swolf > 250:
            logger.warning(f"Unrealistic SWOLF: {avg_swolf}")
            return None
        
        efficiency['avg_swolf'] = round(avg_swolf, 1)
        
        if avg_swolf < 120:
            efficiency['swolf_grade'] = "excellent"
        elif avg_swolf < 140:
            efficiency['swolf_grade'] = "good"
        elif avg_swolf < 160:
            efficiency['swolf_grade'] = "fair"
        else:
            efficiency['swolf_grade'] = "poor"
    
    return efficiency if efficiency else None

def preprocess_data(raw_activities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """預處理並整合所有 raw data 與計算後的指標"""
    processed = []
    
    # Configuration
    MIN_CYCLING_DISTANCE = 1.0 
    
    for item in raw_activities:
        dist_km = item.get('distance', 0)
        dur_min = item.get('duration', 0)
        a_type = item.get('type', 'running')

        if a_type == 'cycling' and dist_km < MIN_CYCLING_DISTANCE:
            continue
        
        optimized_value = calculate_pace(
            duration_ms=dur_min * 60000, 
            distance_m=dist_km * 1000, 
            activity_type=a_type
        )
        
        # 基礎活動記錄
        processed_item = {
            'activity_id': item.get('activity_id'),
            'type': a_type,
            'date': item.get('date'),
            'distance_km': round(dist_km, 2),
            'performance_value': optimized_value,
            'performance_formatted': format_pace(optimized_value, a_type),
            'avg_hr': item.get('average_heart_rate'),
            'max_hr': item.get('max_heart_rate'),
            'splits': item.get('splits', [])
        }

        # --- 修正：先抓取 raw_data 字典，防呆預設為空字典 ---
        raw_data = item.get('raw_data', {})
        
        # 心率區間與功率區間時間分布（所有活動都有）
        hr_zone_data = {f'hr_zone_{i}': raw_data.get(f'hr_zone_{i}') for i in range(1, 6)}
        power_zone_data = {f'power_zone_{i}': raw_data.get(f'power_zone_{i}') for i in range(1, 6)}
        
        if a_type == 'running':
            # 修正 Garmin Key 名稱對應至 raw_data 中的實際名稱
            cadence = raw_data.get('cadence')
            vo = raw_data.get('vertical_oscillation')
            gct = raw_data.get('ground_contact_time')
            
            processed_item['advanced_metrics'] = {
                'avg_cadence': cadence,
                'max_cadence': raw_data.get('max_cadence'),
                'vertical_oscillation': vo,
                'ground_contact_time': gct,
                'stride_length': raw_data.get('stride_length'),
                'elevation_gain': raw_data.get('elevation_gain'),
                'elevation_loss': raw_data.get('elevation_loss'),
                'power_avg': raw_data.get('power_avg'),
                'power_max': raw_data.get('power_max'),
                'training_effect': {
                    'aerobic': raw_data.get('aerobic_training_effect'),
                    'anaerobic': raw_data.get('anaerobic_training_effect')
                },
                'training_load': raw_data.get('training_stress_score'), # 對應 JSON 中的 TSS
                'hr_zones': hr_zone_data,
                'power_zones': power_zone_data
            }
            
            if cadence:
                processed_item['runner_type'] = classify_runner_type(cadence)
            
            if vo and gct:
                processed_item['running_efficiency'] = calculate_running_efficiency(vo, gct)
                
        elif a_type == 'swimming':
            processed_item['advanced_metrics'] = {
                'stroke_count': raw_data.get('total_strokes'),
                'avg_swolf': raw_data.get('avg_swolf'),
                'pool_length': raw_data.get('pool_length'),
                'stroke_style': raw_data.get('avg_stroke_type'),
                'hr_zones': hr_zone_data,
                'power_zones': power_zone_data
            }
            
            swolf = raw_data.get('avg_swolf')
            if swolf:
                processed_item['swimming_efficiency'] = calculate_swimming_efficiency(swolf)
            
        elif a_type == 'cycling':
            processed_item['advanced_metrics'] = {
                'elevation_gain': raw_data.get('elevation_gain'),
                'elevation_loss': raw_data.get('elevation_loss'),
                'hr_zones': hr_zone_data,
                'power_zones': power_zone_data,
                'power_avg': raw_data.get('power_avg'),
                'power_max': raw_data.get('power_max'),
                'avg_cadence': raw_data.get('cadence')
            }
            
            p_avg = raw_data.get('power_avg')
            p_max = raw_data.get('power_max')
            if p_avg and p_max:
                processed_item['cycling_efficiency'] = calculate_cycling_efficiency(p_avg, p_max)
        
        processed.append(processed_item)
            
    return processed