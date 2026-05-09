import json
import os
from google import genai
from google.api_core import exceptions  # 用於精確捕獲 API 錯誤
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv('GEMINI_KEY'))

def coach(data, user_data=None):
    """
    使用 Gemini AI 分析跑步數據。
    優先使用 Pro 模型，若失敗（如達到限制）則回退至 Flash 模型。
    """
    with open('prompts/coach.md', 'r', encoding='utf-8') as f:
        system_prompt = f.read()
    
    data_str = json.dumps(data, ensure_ascii=False, indent=2)
    
    # --- 核心修正：建構完整的 User Context ---
    context = "### User Biometric Data & PRs\n"
    if user_data:
        # 直接序列化整個 user_data，確保 AI 能看到 PRs (跑步、游泳、單車)
        user_context_str = json.dumps(user_data, ensure_ascii=False, indent=2)
        context += user_context_str
    else:
        context += "- No biometric data available\n"
    
    context += f"\n\n### Activity Data to Analyze:\n{data_str}"
    full_prompt = f"{system_prompt}\n\n{context}"

    # 定義模型優先順序
    models_to_try = ["gemini-pro-latest", "gemini-flash-latest"]
    
    for model_name in models_to_try:
        try:
            print(f"正在嘗試使用模型: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=full_prompt
            )
            return response.text
        
        except Exception as e:
            # 如果是最後一個模型也失敗了，才噴出錯誤或回傳 Mock
            if model_name == models_to_try[-1]:
                print(f"所有模型皆調用失敗: {e}")
                return "Mock analysis: 目前 AI 服務繁忙，請稍後再試。建議維持規律跑量，注意心率區間。"
            
            print(f"模型 {model_name} 暫時無法使用（可能達到額度限制），準備切換至下一個備援模型...")
            continue

def run_local_analysis(csv_path, json_path):
    """
    讀取地端 CSV 和 JSON 檔案並執行 AI 分析
    """
    # 1. 讀取活動數據 (CSV)
    # 這裡假設你的 CSV 是經過 data_processor 處理過的格式
    try:
        import pandas as pd
        df = pd.read_csv(csv_path)
        # 將 DataFrame 轉為 List of Dict，這通常是 AI 最容易讀取的 JSON 結構
        running_data = df.to_dict(orient='records')
        print(f"成功讀取活動數據: {csv_path} (共 {len(running_data)} 筆紀錄)")
    except Exception as e:
        print(f"讀取 CSV 失敗: {e}")
        return

    # 2. 讀取使用者生理與 PR 數據 (JSON)
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            user_biometrics = json.load(f)
        print(f"成功讀取使用者數據: {json_path}")
    except Exception as e:
        print(f"讀取 JSON 失敗: {e}")
        user_biometrics = None

    # 3. 執行分析
    print("正在送往 Gemini 進行深度分析...")
    report = coach(running_data, user_biometrics)
    
    print("\n" + "="*30 + " AI 教練分析報告 " + "="*30)
    print(report)
    print("="*75)

    # 4. (選填) 將報告存檔
    report_filename = csv_path.replace('.csv', '_report.md')
    with open(report_filename, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"報告已存檔至: {report_filename}")

if __name__ == "__main__":
    # 指定你的地端路徑
    CSV_FILE = "data/processed/processed_20260509_175604.csv"
    JSON_FILE = "data/raw/garmin_user_20260509_175604.json"
    
    run_local_analysis(CSV_FILE, JSON_FILE)