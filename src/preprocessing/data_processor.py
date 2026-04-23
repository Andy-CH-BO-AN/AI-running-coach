def preprocess_data(raw_data):
    """
    Preprocess raw Garmin data into unified format.
    
    Args:
        raw_data: List of dicts from ingestion.
    
    Returns:
        List of dicts in unified format.
    """
    processed = []
    for item in raw_data:
        if item['distance'] > 0 and item['distance'] >= 0.5:  # Remove invalid and very short entries
            processed.append({
                'date': item['date'],
                'distance_km': item['distance'],
                'duration_min': item['duration'],
                'avg_pace_min_per_km': item['average_pace'],
                'avg_hr': item['average_heart_rate']
            })
    return processed