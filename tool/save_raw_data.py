"""
保存 raw API 數據用於分析
- User profile
- Personal records
- 各活動類型的 splits 數據（跑步、自行車、游泳各一筆）
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from garminconnect import Garmin

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.garmin_client import safe_api_call

load_dotenv()


def save_raw_data():
    email, password = os.getenv("GARMIN_ACCOUNT"), os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        print("❌ 帳號密碼未設定")
        return

    client = Garmin(email, password)
    client.login()

    raw_data = {}

    # 1. 保存 user profile
    print("📍 獲取 user profile...")
    profile = safe_api_call(client.get_user_profile)
    raw_data["profile"] = profile

    # 2. 保存 personal records
    print("📍 獲取 personal records...")
    pr_records = safe_api_call(client.get_personal_record)
    raw_data["pr_records"] = pr_records

    # 3. 獲取各活動類型各一筆的 splits 數據
    print("📍 獲取活動列表...")
    activities_by_type = {"running": None, "cycling": None, "lap_swimming": None}

    start, page_size = 0, 50
    while len([v for v in activities_by_type.values() if v]) < 3:
        activities = safe_api_call(client.get_activities, start, page_size)
        if not activities:
            break

        for activity in activities:
            type_info = activity.get("activityType", {})
            type_key = type_info.get("typeKey") if isinstance(type_info, dict) else type_info

            if type_key in activities_by_type and activities_by_type[type_key] is None:
                activities_by_type[type_key] = activity
                print(f"   ✓ 找到 {type_key}: {activity.get('startTimeLocal')} ({activity.get('activityId')})")

        if len(activities) < page_size:
            break
        start += page_size

    # 4. 獲取 splits 數據
    raw_data["splits"] = {}
    for activity_type, activity in activities_by_type.items():
        if activity:
            activity_id = activity.get("activityId")
            print(f"📍 獲取 {activity_type} splits (ID: {activity_id})...")
            splits_data = safe_api_call(client.get_activity_splits, activity_id)
            raw_data["splits"][activity_type] = {
                "activity_info": activity,
                "splits_data": splits_data,
            }

    # 5. 保存到文件
    timestamp = datetime.now().strftime("%Y%m%d")
    output_file = ROOT_DIR / "data" / "sample" / f"raw_data_sample_{timestamp}.json"

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n✅ Raw data 已保存到: {output_file}")

    # 打印簡要摘要
    print("\n📊 數據摘要:")
    print(f"  - Profile: {len(str(profile))} 字符")
    print(f"  - PR Records: {len(pr_records) if pr_records else 0} 筆")
    for activity_type, data in raw_data["splits"].items():
        if data:
            splits_count = len(data["splits_data"].get("lapDTOs", []))
            print(f"  - {activity_type} splits: {splits_count} 個 lap")


if __name__ == "__main__":
    save_raw_data()
