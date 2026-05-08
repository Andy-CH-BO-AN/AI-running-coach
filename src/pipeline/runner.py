from src.ingestion.garmin_client import get_garmin_activities
from src.preprocessing.data_processor import preprocess_data
from agents.coach import coach
import pandas as pd
import os
from datetime import datetime

def run_pipeline():
    """
    Execute the full AI coach pipeline.
    """
    print("Starting Garmin AI Coach Pipeline...")
    
    # 1. Ingestion
    print("Fetching Garmin data...")
    garmin_data = get_garmin_activities(100)
    raw_activities = garmin_data.get('activities', [])
    user_data = garmin_data.get('user_data', {}) # 這裡才是真正的字典
    
    print(f"User profile - Max HR: {user_data.get('max_heart_rate')}, Resting HR: {user_data.get('resting_heart_rate')}")
    
    # 2. Preprocessing
    print("Preprocessing data...")
    processed_data = preprocess_data(raw_activities)
    
    # 3. Analysis 
    print("Analyzing data with AI...")
    response = coach(data=processed_data, user_data=user_data)
    
    # 4. Output CSV
    print("Generating CSV output...")
    # 建立 output 資料夾（如果不存在）
    os.makedirs('output', exist_ok=True)
    
    date_today = datetime.now().strftime('%Y%m%d')
    filename = f'output/ai_analysis_{date_today}.csv'
    
    # 因為 response 是 AI 回傳的一長串文字報告，存入 CSV 時建議給它個欄位名稱
    df = pd.DataFrame([{'date': date_today, 'ai_report': response}])
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    
    print(f"Pipeline completed. Output saved to {filename}")
    return filename