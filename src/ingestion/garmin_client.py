import os
import time
import logging
from typing import List, Dict, Any, Optional
from garminconnect import Garmin
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)


def get_user_biometric_data(client: Garmin) -> Dict[str, Optional[float]]:
    """
    Get user's biometric data including max heart rate and resting heart rate.
    
    Args:
        client: Garmin client instance
    
    Returns:
        Dict with biometric info (max_heart_rate, resting_heart_rate)
    """
    try:
        max_hr = None
        resting_hr = None
        
        # Try different methods to get HR data
        try:
            # Try get_personal_records
            personal_records = client.get_personal_records()
            if personal_records:
                # Look for HR related records
                for record in personal_records:
                    if 'maxHeartRate' in str(record).lower():
                        max_hr = record.get('value')
                        break
                    if 'restingHeartRate' in str(record).lower():
                        resting_hr = record.get('value')
                        break
        except Exception as e:
            logger.debug(f"Error occurred while fetching personal records: {e}")
        
        # Try to estimate max HR from activities (use the max value we've seen)
        # This will be calculated after we get all activities
        
        return {
            'max_heart_rate': max_hr,
            'resting_heart_rate': resting_hr
        }
    except Exception as e:
        logger.warning(f"Could not fetch biometric data: {e}")
        return {
            'max_heart_rate': None,
            'resting_heart_rate': None
        }


def estimate_max_hr_from_activities(activities: List[Dict[str, Any]]) -> Optional[int]:
    """
    Estimate user's max heart rate from activities data.
    
    Args:
        activities: List of activity dicts
    
    Returns:
        Estimated max HR as int, or None if no HR data available
    """
    max_hrs = [a.get('max_heart_rate') for a in activities if a.get('max_heart_rate')]
    if max_hrs:
        return int(max(max_hrs))
    return None


def get_activity_splits(client: Garmin, activity_id: int) -> List[Dict[str, Any]]:
    """
    Fetch split data for a specific activity.
    
    Args:
        client: Garmin client instance
        activity_id: ID of the activity to fetch splits for
    
    Returns:
        List of split dicts, each containing:
        - distance: distance in km
        - duration: duration in minutes
        - pace: pace in min/km (None if distance is 0)
        - average_heart_rate: average heart rate for this split
        - max_heart_rate: max heart rate for this split
        - split_index: lap/split number (1-indexed)
    """
    splits = []
    try:
        # Get splits/laps data from the activity
        splits_data = client.get_activity_splits(activity_id)
        
        if splits_data and isinstance(splits_data, dict):
            lap_dtos = splits_data.get('lapDTOs', [])
            
            if lap_dtos:
                for lap_index, lap_data in enumerate(lap_dtos, 1):
                    try:
                        # Convert distance from meters to km
                        distance_m = lap_data.get('distance', 0)
                        distance = distance_m / 1000 if distance_m else 0
                        
                        # Convert duration from seconds to minutes (not milliseconds)
                        duration_s = lap_data.get('duration', 0)
                        duration = duration_s / 60 if duration_s else 0
                        
                        # Calculate pace (min/km)
                        pace = duration / distance if distance > 0 else None
                        
                        # Get heart rate data (note: API uses 'averageHR' and 'maxHR', not 'avgHeartRate')
                        avg_hr = lap_data.get('averageHR')
                        max_hr = lap_data.get('maxHR')
                        
                        splits.append({
                            'distance': distance,
                            'duration': duration,
                            'pace': pace,
                            'average_heart_rate': avg_hr,
                            'max_heart_rate': max_hr,
                            'split_index': lap_index
                        })
                        
                    except Exception as e:
                        logger.debug(f"Failed to process lap {lap_index}: {e}")
                        continue
    except Exception as e:
        logger.warning(f"Could not fetch splits for activity {activity_id}: {e}")
    
    return splits


def get_garmin_activities(n: Optional[int] = 30) -> Dict[str, Any]:
    """
    Fetch all running activities from Garmin Connect with retry logic.
    
    Args:
        n: Maximum number of activities to fetch (default 30, None = all activities)
    
    Returns:
        Dict with:
        - 'activities': List of running activities with splits data
        - 'user_data': Dict with max_heart_rate, resting_heart_rate, etc.
    """
    email = os.getenv('GARMIN_ACCOUNT')
    password = os.getenv('GARMIN_PASSWORD')
    
    if not email or not password:
        logger.error("GARMIN_ACCOUNT or GARMIN_PASSWORD not set in .env")
        return {'activities': [], 'user_data': {}}
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            logger.info(f"Connecting to Garmin (attempt {retry_count + 1}/{max_retries})...")
            client = Garmin(email, password)
            client.login()
            
            # Get user biometric data first
            logger.info("Fetching user biometric data...")
            user_data = get_user_biometric_data(client)
            logger.debug(f"Max HR: {user_data.get('max_heart_rate')}")
            logger.debug(f"Resting HR: {user_data.get('resting_heart_rate')}")
            
            # Fetch activities with pagination
            running_activities = []
            page_size = 100  # Garmin typically returns up to 100 per page
            start = 0
            
            logger.info("Fetching all running activities...")
            
            while True:
                try:
                    # Fetch a page of activities
                    activities = client.get_activities(start, page_size)
                    
                    if not activities:
                        logger.info(f"Reached end of activities at page starting from {start}")
                        break
                    
                    activities_before = len(running_activities)
                    
                    for activity in activities:
                        # Filter only running activities
                        activity_type = activity.get('activityType', {})
                        type_key = activity_type.get('typeKey') if isinstance(activity_type, dict) else activity_type
                        print(f"Processing activity {activity.get('activityId')} of type {type_key}...")
                        
                        if type_key == 'running':
                            try:
                                # Extract date (format: YYYY-MM-DD)
                                date = activity.get('startTimeLocal', '')[:10]
                                
                                # Convert distance from meters to km
                                distance_m = activity.get('distance', 0)
                                distance = distance_m / 1000 if distance_m else 0
                                
                                # Convert duration from seconds to minutes
                                duration_s = activity.get('duration', 0)
                                duration = duration_s / 60 if duration_s else 0
                                
                                # Calculate average pace (min/km)
                                avg_pace = duration / distance if distance > 0 else None
                                
                                # Get average and max heart rate
                                avg_hr = activity.get('averageHR')
                                max_hr_activity = activity.get('maxHR')
                                
                                # Fetch splits data for this activity
                                activity_splits = get_activity_splits(client, activity.get('activityId'))
                                
                                running_activities.append({
                                    'type': 'running',
                                    'date': date,
                                    'distance': distance,
                                    'duration': duration,
                                    'average_pace': avg_pace,
                                    'average_heart_rate': avg_hr,
                                    'max_heart_rate': max_hr_activity,
                                    'activity_id': activity.get('activityId'),
                                    'splits': activity_splits
                                })
                                
                            except Exception as e:
                                logger.debug(f"Failed to process activity {activity.get('activityId')}: {e}")
                                continue
                        elif type_key == 'lap_swimming':
                            try:
                                # Extract date (format: YYYY-MM-DD)
                                date = activity.get('startTimeLocal', '')[:10]
                                
                                # Convert distance from meters to km
                                distance_m = activity.get('distance', 0)
                                distance = distance_m / 1000 if distance_m else 0
                                
                                # Convert duration from seconds to minutes
                                duration_s = activity.get('duration', 0)
                                duration = duration_s / 60 if duration_s else 0
                                
                                # Calculate average pace (min/km)
                                avg_pace = duration / distance if distance > 0 else None
                                
                                # Get average and max heart rate
                                avg_hr = activity.get('averageHR')
                                max_hr_activity = activity.get('maxHR')
                                
                                # Fetch splits data for this activity
                                activity_splits = get_activity_splits(client, activity.get('activityId'))
                                
                                running_activities.append({
                                    'type': 'swimming',
                                    'date': date,
                                    'distance': distance,
                                    'duration': duration,
                                    'average_pace': avg_pace,
                                    'average_heart_rate': avg_hr,
                                    'max_heart_rate': max_hr_activity,
                                    'activity_id': activity.get('activityId'),
                                    'splits': activity_splits
                                })
                                
                            except Exception as e:
                                logger.debug(f"Failed to process activity {activity.get('activityId')}: {e}")
                                continue
                        elif type_key == 'cycling':
                            try:
                                # Extract date (format: YYYY-MM-DD)
                                date = activity.get('startTimeLocal', '')[:10]
                                
                                # Convert distance from meters to km
                                distance_m = activity.get('distance', 0)
                                distance = distance_m / 1000 if distance_m else 0
                                
                                # Convert duration from seconds to minutes
                                duration_s = activity.get('duration', 0)
                                duration = duration_s / 60 if duration_s else 0
                                
                                # Calculate average pace (min/km)
                                avg_pace = duration / distance if distance > 0 else None
                                
                                # Get average and max heart rate
                                avg_hr = activity.get('averageHR')
                                max_hr_activity = activity.get('maxHR')
                                
                                # Fetch splits data for this activity
                                activity_splits = get_activity_splits(client, activity.get('activityId'))
                                
                                running_activities.append({
                                    'type': 'cycling',
                                    'date': date,
                                    'distance': distance,
                                    'duration': duration,
                                    'average_pace': avg_pace,
                                    'average_heart_rate': avg_hr,
                                    'max_heart_rate': max_hr_activity,
                                    'activity_id': activity.get('activityId'),
                                    'splits': activity_splits
                                })
                                
                            except Exception as e:
                                logger.debug(f"Failed to process activity {activity.get('activityId')}: {e}")
                                continue
                    
                    activities_added = len(running_activities) - activities_before
                    logger.debug(f"Page {start // page_size + 1}: Added {activities_added} running activities (total: {len(running_activities)})")
                    
                    # Check if we've reached the limit
                    if n and len(running_activities) >= n:
                        logger.info(f"Reached limit of {n} activities")
                        running_activities = running_activities[:n]
                        break
                    
                    # If we got fewer activities than page size, we're at the end
                    if len(activities) < page_size:
                        logger.debug(f"Got {len(activities)} activities, which is less than page size {page_size}")
                        break
                    
                    start += page_size
                    
                except Exception as e:
                    logger.error(f"Error fetching page starting at {start}: {e}")
                    break
            
            logger.info(f"Successfully fetched {len(running_activities)} total running activities")
            
            # Estimate max HR from activities if not already set
            if not user_data.get('max_heart_rate'):
                estimated_max_hr = estimate_max_hr_from_activities(running_activities)
                if estimated_max_hr:
                    logger.info(f"Estimated max HR from activities: {estimated_max_hr}")
                    user_data['max_heart_rate'] = estimated_max_hr
            
            return {
                'activities': running_activities,
                'user_data': user_data
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching Garmin data (attempt {retry_count + 1}): {error_msg}")
            
            # Check if it's a rate limit error (429)
            if "429" in error_msg or "rate limit" in error_msg.lower():
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = 2 ** retry_count  # Exponential backoff: 2, 4, 8 seconds
                    logger.warning(f"Rate limited. Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                else:
                    logger.error("Max retries exceeded. Giving up.")
                    return {'activities': [], 'user_data': {}}
            else:
                # For other errors, return empty
                logger.error(f"Non-recoverable error: {error_msg}")
                return {'activities': [], 'user_data': {}}
    return {'activities': [], 'user_data': {}}
