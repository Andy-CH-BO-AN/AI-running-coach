import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv
from google import genai

load_dotenv()

PROMPT_PATH = Path("prompts/coach.md")
DEFAULT_GOAL_PATH = Path("prompts/goal.md")
OUTPUT_DIR = Path("output")
MODEL_FALLBACKS = ("gemini-pro-latest", "gemini-flash-latest")

client = genai.Client(api_key=os.getenv("GEMINI_KEY"))


def _read_text_file(path: Path) -> str:
    with path.open("r", encoding="utf-8") as file_obj:
        return file_obj.read()


def _build_context(
    data: List[Dict[str, Any]],
    user_data: Optional[Dict[str, Any]],
    goal_path: Optional[str],
) -> str:
    sections = []

    if goal_path:
        goal_file = Path(goal_path)
        if goal_file.exists():
            sections.append(f"### 我的訓練目標 (My Goals):\n{_read_text_file(goal_file)}")

    if user_data:
        user_context = json.dumps(user_data, ensure_ascii=False, indent=2)
    else:
        user_context = "- No biometric data available"
    sections.append(f"### User Biometric Data & PRs:\n{user_context}")

    data_context = json.dumps(data, ensure_ascii=False, indent=2)
    sections.append(f"### Activity Data to Analyze:\n{data_context}")

    return "\n\n".join(sections)


def coach(
    data: List[Dict[str, Any]],
    user_data: Optional[Dict[str, Any]] = None,
    goal_path: str = "",
) -> str:
    system_prompt = _read_text_file(PROMPT_PATH)
    full_prompt = f"{system_prompt}\n\n{_build_context(data, user_data, goal_path)}"

    for model_name in MODEL_FALLBACKS:
        try:
            print(f"正在嘗試使用模型: {model_name}...")
            response = client.models.generate_content(model=model_name, contents=full_prompt)
            return response.text
        except Exception as exc:
            if model_name == MODEL_FALLBACKS[-1]:
                print(f"所有模型皆調用失敗: {exc}")
                return "AI 服務暫時無法連線。建議根據近期體感調整訓練量。"
            print(f"模型 {model_name} 暫時無法使用，準備切換備援模型...")

    return "AI 服務暫時無法連線。建議根據近期體感調整訓練量。"


def _load_processed_records(csv_path: str) -> Optional[List[Dict[str, Any]]]:
    try:
        data_frame = pd.read_csv(csv_path)
        running_data = data_frame.to_dict(orient="records")
        print(f"成功讀取活動數據: {csv_path} (共 {len(running_data)} 筆)")
        return running_data
    except Exception as exc:
        print(f"讀取 CSV 失敗: {exc}")
        return None


def _load_user_biometrics(json_path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(json_path, "r", encoding="utf-8") as file_obj:
            user_biometrics = json.load(file_obj)
        print(f"成功讀取使用者數據: {json_path}")
        return user_biometrics
    except Exception as exc:
        print(f"讀取 JSON 失敗: {exc}")
        return None


def _write_local_report(report: str, source_csv_path: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")
    report_path = OUTPUT_DIR / f"ai_report_{timestamp}.md"

    with report_path.open("w", encoding="utf-8") as file_obj:
        file_obj.write("# 🏃‍♂️ Garmin AI Coach Analysis Report\n\n")
        file_obj.write(f"- **生成日期:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file_obj.write(f"- **數據來源:** `{os.path.basename(source_csv_path)}`\n")
        file_obj.write("---\n\n")
        file_obj.write(report)
        file_obj.write("\n\n---\n*Happy Running!*")

    return report_path


def run_local_analysis(
    csv_path: str,
    json_path: str,
    goal_path: str = str(DEFAULT_GOAL_PATH),
) -> None:
    running_data = _load_processed_records(csv_path)
    if running_data is None:
        return

    user_biometrics = _load_user_biometrics(json_path)
    if not Path(goal_path).exists():
        print(f"警告: 找不到 {goal_path}，將進行無目標分析。")

    print("正在送往 Gemini 進行深度分析...")
    report = coach(running_data, user_biometrics, goal_path=goal_path)
    report_path = _write_local_report(report, csv_path)
    print(f"✨ 分析完成！報告已存至: {report_path}")


if __name__ == "__main__":
    csv_file = "data/processed/processed_20260509_222333.csv"
    json_file = "data/raw/garmin_user_20260509_222333.json"
    goal_file = str(DEFAULT_GOAL_PATH)

    run_local_analysis(csv_file, json_file, goal_file)
