def preprocess_data(raw_activities):
    """
    Preprocess raw Garmin data into unified format, including multi-sport types and lap splits.
    
    Args:
        raw_activities: List of dicts from ingestion (pass the 'activities' list from get_garmin_activities output).
    
    Returns:
        List of dicts in unified format.
    """
    processed = []
    
    for item in raw_activities:
        distance = item.get('distance', 0)
        type = item.get('type', 'running')
        
        if distance > 1 and type == 'cycling':
            
            # 處理分圈 (Splits) 資料
            processed_splits = []
            for split in item.get('splits', []):
                processed_splits.append({
                    'split_index': split.get('split_index'),
                    'distance_km': split.get('distance'),
                    'duration_min': split.get('duration'),
                    'pace_min_per_km': split.get('pace'),
                    'avg_hr': split.get('average_heart_rate'),
                    'max_hr': split.get('max_heart_rate')
                })
                
            # 整合主活動資料與分圈資料
            processed.append({
                'activity_id': item.get('activity_id'),
                'type': item.get('type', 'running'), # 包含 running, swimming, cycling
                'date': item.get('date'),
                'distance_km': distance,
                'duration_min': item.get('duration'),
                'avg_pace_min_per_km': item.get('average_pace'),
                'avg_hr': item.get('average_heart_rate'),
                'max_hr': item.get('max_heart_rate'),
                'splits': processed_splits
            })
            
    return processed