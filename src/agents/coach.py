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
    
    context = f"User Biometric Data:\n"
    if user_data:
        context += f"- Max Heart Rate: {user_data.get('max_heart_rate', 'Unknown')}\n"
        context += f"- Resting Heart Rate: {user_data.get('resting_heart_rate', 'Unknown')}\n"
    else:
        context += "- No biometric data available\n"
    
    context += f"\nActivity Data:\n{data_str}"
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

# 使用範例:
# report = coach(running_data, user_biometrics)
# print(report)