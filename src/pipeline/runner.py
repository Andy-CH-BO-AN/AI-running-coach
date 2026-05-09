from src.ingestion.garmin_client import get_garmin_activities
from src.preprocessing.data_processor import preprocess_data
from agents.coach import coach
import json
import pandas as pd
import os
from datetime import datetime

def run_pipeline():
    """
    Execute the full AI coach pipeline with data persistence and Markdown reporting.
    """
    print("🚀 Starting Garmin AI Coach Pipeline...")
    
    # 1. Ingestion
    garmin_data = get_garmin_activities(50)
    raw_activities = garmin_data.get('activities', [])
    user_data = garmin_data.get('user_data', {})
    
    if not raw_activities:
        print("❌ No activities found.")
        return None
    
    # --- [新增] 儲存 Raw Data (JSON 格式最能保留原始結構) ---
    os.makedirs('data/raw', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    with open(f'data/raw/garmin_raw_{timestamp}.json', 'w', encoding='utf-8') as f:
        json.dump(raw_activities, f, ensure_ascii=False, indent=4)

    with open(f'data/raw/garmin_user_{timestamp}.json', 'w', encoding='utf-8') as f:
        json.dump(user_data, f, ensure_ascii=False, indent=4)
    
    # 2. Preprocessing
    print("🧹 Preprocessing data...")
    processed_data = preprocess_data(raw_activities)
    
    if not processed_data:
        print("⚠️ No data left after preprocessing.")
        return None

    # --- [新增] 儲存 Processed Data (CSV 方便後續快速檢視) ---
    os.makedirs('data/processed', exist_ok=True)
    # 將巢狀的 advanced_metrics 攤平以便存入 CSV
    df_processed = pd.json_normalize(processed_data)
    df_processed.to_csv(f'data/processed/processed_{timestamp}.csv', index=False, encoding='utf-8-sig')
    
    # 3. Analysis 
    print("🤖 Analyzing data with AI Coach...")
    response = coach(data=processed_data, user_data=user_data)
    
    # 4. Output CSV & Markdown Report
    print("💾 Generating reports...")
    os.makedirs('output', exist_ok=True)
    
    # 建立 DataFrame
    report_df = pd.DataFrame([{
        'Date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
        'Activities': len(processed_data),
        'Coach Analysis': response
    }])
    
    # 儲存 CSV (原始備份)
    report_df.to_csv(f'output/ai_analysis_{timestamp}.csv', index=False, encoding='utf-8-sig')
    
    # --- [新增] 儲存 Markdown (視覺化閱讀用) ---
    md_filename = f'output/ai_report_{timestamp}.md'
    with open(md_filename, 'w', encoding='utf-8') as f:
        f.write(f"# 🏃‍♂️ Garmin AI Coach Training Report\n\n")
        f.write(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"## 📊 Summary\n")
        # 使用 Pandas 的 to_markdown 功能 (需安裝 tabulate)
        f.write(report_df.to_markdown(index=False))
        f.write(f"\n\n---\n*Happy Running!*")

    print(f"✨ Pipeline completed!")
    print(f"📁 Raw Data: data/raw/")
    print(f"📁 Processed Data: data/processed/")
    print(f"📄 Markdown Report: {md_filename}")
    
    return md_filename