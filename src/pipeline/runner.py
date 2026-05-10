from src.ingestion.garmin_client import get_garmin_activities
from src.preprocessing.data_processor import preprocess_data
from agents.coach import coach
import json
import pandas as pd
import os
from datetime import datetime

def run_pipeline():
    """
    執行完整的 AI 教練 Pipeline，僅儲存原始數據與 Markdown 報告。
    """
    print("🚀 Starting Garmin AI Coach Pipeline...")
    
    # 1. Ingestion (擷取數據)
    garmin_data = get_garmin_activities(75)
    raw_activities = garmin_data.get('activities', [])
    user_data = garmin_data.get('user_data', {})
    
    if not raw_activities:
        print("❌ No activities found.")
        return None
    
    # 儲存 Raw Data
    os.makedirs('data/raw', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d')
    with open(f'data/raw/garmin_raw_{timestamp}.json', 'w', encoding='utf-8') as f:
        json.dump(raw_activities, f, ensure_ascii=False, indent=4)
    with open(f'data/raw/garmin_user_{timestamp}.json', 'w', encoding='utf-8') as f:
        json.dump(user_data, f, ensure_ascii=False, indent=4)
    
    # 2. Preprocessing (預處理)
    print("🧹 Preprocessing data...")
    processed_data = preprocess_data(raw_activities)
    
    if not processed_data:
        print("⚠️ No data left after preprocessing.")
        return None

    # 儲存已處理的資料 (CSV 僅作為數據備份)
    os.makedirs('data/processed', exist_ok=True)
    df_processed = pd.json_normalize(processed_data)
    df_processed.to_csv(f'data/processed/processed_{timestamp}.csv', index=False, encoding='utf-8-sig')
    
    # 3. Analysis (AI 分析)
    print("🤖 Analyzing data with AI Coach...")
    response = coach(data=processed_data, user_data=user_data, goal_path="prompts/goal.md")
    
    # 4. Output Markdown Report (移除 CSV 分析備份)
    print("💾 Generating Markdown report...")
    os.makedirs('output', exist_ok=True)
    
    md_filename = f'output/ai_report_{timestamp}.md'
    with open(md_filename, 'w', encoding='utf-8') as f:
        # 寫入報告標題與元數據
        f.write(f"# 🏃‍♂️ Garmin AI Coach Training Report\n\n")
        f.write(f"- **分析日期:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- **分析活動數量:** {len(processed_data)}\n\n")
        f.write(f"---\n\n")
        
        # 直接寫入 AI 的分析內容（ response 本身就是 Markdown 格式）
        f.write(response)
        
        f.write(f"\n\n---\n*Happy Running!*")

    print(f"✨ Pipeline completed!")
    print(f"📄 Markdown Report: {md_filename}")
    
    return md_filename