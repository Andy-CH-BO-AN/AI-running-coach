#!/usr/bin/env python3
"""Test script for Garmin client"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from ingestion.garmin_client import get_garmin_activities

print("Testing Garmin Client...")
print("=" * 80)

data = get_garmin_activities()
activities = data.get('activities', [])
user_data = data.get('user_data', {})

print(f"\nRetrieved {len(activities)} activities")
print("=" * 80)

print("\nUser Biometric Data:")
print(f"  Max Heart Rate: {user_data.get('max_heart_rate', 'N/A')}")
print(f"  Resting Heart Rate: {user_data.get('resting_heart_rate', 'N/A')}")
print("=" * 80)

if activities:
    print("\nFirst activity details:")
    for key, value in activities[0].items():
        print(f"  {key}: {value}")
    
    print(f"\nAll {len(activities)} activities summary:")
    for i, activity in enumerate(activities, 1):
        hr_val = activity.get('average_heart_rate')
        max_hr_val = activity.get('max_heart_rate')
        hr_str = f"{hr_val:.0f}" if hr_val is not None else "N/A"
        max_hr_str = f"{max_hr_val:.0f}" if max_hr_val is not None else "N/A"
        avg_pace = activity.get('average_pace')
        pace_str = f"{avg_pace:.1f}" if avg_pace is not None else "N/A"
        print(f"{i:3}. {activity['date']} - {activity['distance']:5.1f}km, {activity['duration']:5.1f}min, pace: {pace_str:>4}min/km, HR: {hr_str:>3}, max HR: {max_hr_str:>3}")
else:
    print("No activities retrieved!")

print("=" * 80)
print("Test complete.")
