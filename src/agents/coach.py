import json
import os
import pandas as pd
from datetime import datetime
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv('GEMINI_KEY'))

def coach(data, user_data=None, goal_path=""):
    """
    使用 Gemini AI 分析跑步數據。
    新增 goal 參數，讓 AI 針對目標進行分析。
    """
    # 讀取 Prompt 模板
    with open('prompts/coach.md', 'r', encoding='utf-8') as f:
        system_prompt = f.read()
    
    data_str = json.dumps(data, ensure_ascii=False, indent=2)
    
    # --- 建構完整的 Context ---
    context = ""
    
    # 1. 插入目標 (Priority 1)
    if goal_path and os.path.exists(goal_path):
        with open(goal_path, 'r', encoding='utf-8') as f:
            goal = f.read()
        context += f"### 我的訓練目標 (My Goals):\n{goal}\n\n"
    
    # 2. 插入個人生理數據與 PR
    context += "### User Biometric Data & PRs:\n"
    if user_data:
        user_context_str = json.dumps(user_data, ensure_ascii=False, indent=2)
        context += user_context_str
    else:
        context += "- No biometric data available\n"
    
    # 3. 插入活動數據
    context += f"\n\n### Activity Data to Analyze:\n{data_str}"
    
    # 組合完整的 Prompt
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
            if model_name == models_to_try[-1]:
                print(f"所有模型皆調用失敗: {e}")
                return "AI 服務暫時無法連線。建議根據近期體感調整訓練量。"
            print(f"模型 {model_name} 暫時無法使用，準備切換備援模型...")
            continue

def run_local_analysis(csv_path, json_path, goal_path='prompts/goal.md'):
    """
    讀取地端 CSV、JSON 和 Goal 檔案並執行 AI 分析，僅儲存 Markdown。
    """
    # 1. 讀取活動數據 (CSV)
    try:
        df = pd.read_csv(csv_path)
        running_data = df.to_dict(orient='records')
        print(f"成功讀取活動數據: {csv_path} (共 {len(running_data)} 筆)")
    except Exception as e:
        print(f"讀取 CSV 失敗: {e}")
        return

    # 2. 讀取使用者生理數據 (JSON)
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            user_biometrics = json.load(f)
        print(f"成功讀取使用者數據: {json_path}")
    except Exception as e:
        print(f"讀取 JSON 失敗: {e}")
        user_biometrics = None

    # 3. 讀取目標數據 (Markdown)
    if not os.path.exists(goal_path):
        print(f"警告: 找不到 {goal_path}，將進行無目標分析。")

    # 4. 執行 AI 分析
    print("正在送往 Gemini 進行深度分析...")
    report = coach(running_data, user_biometrics, goal_path=goal_path)
    
    # 5. 生成報告存檔 (僅存 Markdown)
    os.makedirs('output', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_filename = f"output/ai_report_{timestamp}.md"
    
    with open(report_filename, 'w', encoding='utf-8') as f:
        f.write(f"# 🏃‍♂️ Garmin AI Coach Analysis Report\n\n")
        f.write(f"- **生成日期:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- **數據來源:** `{os.path.basename(csv_path)}`\n")
        f.write(f"---\n\n")
        f.write(report)
        f.write(f"\n\n---\n*Happy Running!*")

    print(f"✨ 分析完成！報告已存至: {report_filename}")

if __name__ == "__main__":
    # 指定你的地端路徑
    CSV_FILE = "data/processed/processed_20260509_222333.csv"
    JSON_FILE = "data/raw/garmin_raw_20260509_222333.json"
    GOAL_FILE = "prompts/goal.md"
    
    run_local_analysis(CSV_FILE, JSON_FILE, GOAL_FILE)