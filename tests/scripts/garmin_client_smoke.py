#!/usr/bin/env python3
"""Manual smoke test for Garmin client."""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "src"))

from ingestion.garmin_client import get_garmin_activities


def main():
    print("Testing Garmin Client...")
    print("=" * 80)

    data = get_garmin_activities()
    activities = data.get("activities", [])
    user_data = data.get("user_data", {})

    print(f"\nRetrieved {len(activities)} activities")
    print("=" * 80)

    print("\nUser Biometric Data:")
    print(f"  Max Heart Rate: {user_data.get('max_heart_rate', 'N/A')}")
    print(f"  Resting Heart Rate: {user_data.get('resting_heart_rate', 'N/A')}")
    print("=" * 80)

    if activities:
        print("\nFirst activity details:")
        for key, value in activities[0].items():
            if key != "splits":
                print(f"  {key}: {value}")

        if activities[0].get("splits"):
            print(f"\n  Splits for first activity ({len(activities[0]['splits'])} splits):")
            for split in activities[0]["splits"]:
                hr_str = f"{split.get('average_heart_rate', 'N/A'):.0f}" if split.get("average_heart_rate") else "N/A"
                max_hr_str = f"{split.get('max_heart_rate', 'N/A'):.0f}" if split.get("max_heart_rate") else "N/A"
                pace_str = f"{split['pace']:.1f}" if split["pace"] is not None else "N/A"
                print(
                    f"    Split {split['split_index']}: {split['distance']:.1f}km, "
                    f"{split['duration']:.1f}min, pace: {pace_str:>5}min/km, "
                    f"HR: {hr_str:>3}, max: {max_hr_str:>3}"
                )

        print(f"\nAll {len(activities)} activities summary:")
        for i, activity in enumerate(activities, 1):
            hr_val = activity.get("average_heart_rate")
            max_hr_val = activity.get("max_heart_rate")
            hr_str = f"{hr_val:.0f}" if hr_val is not None else "N/A"
            max_hr_str = f"{max_hr_val:.0f}" if max_hr_val is not None else "N/A"
            avg_pace = activity.get("average_pace")
            pace_str = f"{avg_pace:.1f}" if avg_pace is not None else "N/A"
            splits_count = len(activity.get("splits", []))
            print(
                f"{i:3}. {activity['date']} - {activity['distance']:5.1f}km, "
                f"{activity['duration']:5.1f}min, pace: {pace_str:>4}min/km, "
                f"HR: {hr_str:>3}, max HR: {max_hr_str:>3}, splits: {splits_count}"
            )
    else:
        print("No activities retrieved!")

    print("=" * 80)
    print("Test complete.")


if __name__ == "__main__":
    main()
