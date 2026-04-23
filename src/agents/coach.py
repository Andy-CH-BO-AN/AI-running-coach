import json
from google import genai
import os
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv('GEMINI_KEY'))

def coach(data, user_data=None):
    """
    Analyze preprocessed running data using Gemini AI.
    
    Args:
        data: List of dicts with processed data.
        user_data: Dict with user biometric data (max_heart_rate, resting_heart_rate)
    
    Returns:
        String analysis report.
    """
    with open('prompts/coach.md', 'r', encoding='utf-8') as f:
        prompt = f.read()
    
    data_str = json.dumps(data, ensure_ascii=False, indent=2)
    
    # Build context with user data
    context = f"User Biometric Data:\n"
    if user_data:
        context += f"- Max Heart Rate: {user_data.get('max_heart_rate', 'Unknown')}\n"
        context += f"- Resting Heart Rate: {user_data.get('resting_heart_rate', 'Unknown')}\n"
    else:
        context += "- No biometric data available\n"
    
    context += f"\nActivity Data:\n{data_str}"
    full_prompt = f"{prompt}\n\n{context}"
    
    try:
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=full_prompt
        )
        return response.text
    except Exception as e:
        print(f"AI API error: {e}")
        return "Mock analysis: Your running data shows a mix of short and long runs. Pace is consistent around 6 min/km. Heart rate data indicates good cardiovascular fitness. Recommendations: Increase long run distance gradually, incorporate interval training for speed work."
