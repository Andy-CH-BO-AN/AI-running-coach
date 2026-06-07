from copy import deepcopy
import json
import os
import re
import time
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
MODEL_FALLBACKS = (
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
)
MAX_RETRIES_PER_MODEL = 3
RETRY_BACKOFF_SECONDS = 1


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _build_genai_client(*, vertexai: bool | None = None) -> genai.Client:
    api_key = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_KEY")
        or os.getenv("GEMINI_API_KEY")
    )
    if vertexai is None:
        vertexai = _env_flag("GOOGLE_GENAI_USE_VERTEXAI") or _env_flag("GEMINI_USE_VERTEXAI")

    client_kwargs: Dict[str, Any] = {
        "api_key": api_key,
        "http_options": {"api_version": "v1"},
    }

    if vertexai:
        client_kwargs["vertexai"] = True
        if not api_key:
            project = os.getenv("GOOGLE_CLOUD_PROJECT")
            location = os.getenv("GOOGLE_CLOUD_LOCATION")
            if project:
                client_kwargs["project"] = project
            if location:
                client_kwargs["location"] = location

    return genai.Client(**client_kwargs)


client = _build_genai_client()


class ReportParseError(ValueError):
    pass


def _read_text_file(path: Path) -> str:
    with path.open("r", encoding="utf-8") as file_obj:
        return file_obj.read()


def _build_context(
    data: List[Dict[str, Any]],
    user_data: Optional[Dict[str, Any]],
    goal_path: Optional[str],
    goal_text: Optional[str] = None,
    deterministic_context: Optional[Dict[str, Any]] = None,
) -> str:
    sections = []

    if goal_text is not None:
        sections.append(f"### 我的訓練目標 (My Goals):\n{goal_text}")
    elif goal_path:
        goal_file = Path(goal_path)
        if goal_file.exists():
            sections.append(f"### 我的訓練目標 (My Goals):\n{_read_text_file(goal_file)}")

    if user_data:
        user_context = json.dumps(user_data, ensure_ascii=False, indent=2)
    else:
        user_context = "- No biometric data available"
    sections.append(f"### User Biometric Data & PRs:\n{user_context}")

    if deterministic_context:
        context_json = json.dumps(
            _sanitize_deterministic_context_for_prompt(deterministic_context),
            ensure_ascii=False,
            indent=2,
        )
        sections.append(
            "### Deterministic Coach Context (code-calculated source of truth):\n"
            f"{context_json}"
        )

    data_context = json.dumps(_sanitize_processed_activity_data_for_prompt(data), ensure_ascii=False, indent=2)
    sections.append(f"### Processed Activity Data Reference:\n{data_context}")

    return "\n\n".join(sections)


def _sanitize_deterministic_context_for_prompt(deterministic_context: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = deepcopy(deterministic_context)
    for week in sanitized.get("weekly_analysis") or []:
        if not isinstance(week, dict):
            continue
        session_counts = week.get("session_counts")
        if isinstance(session_counts, dict):
            session_counts.pop("by_type", None)
        for session in week.get("sessions") or []:
            if isinstance(session, dict):
                session.pop("type", None)
    return sanitized


def _sanitize_processed_activity_data_for_prompt(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for record in data or []:
        if not isinstance(record, dict):
            sanitized.append(record)
            continue
        copy = deepcopy(record)
        activity_type = copy.get("type")
        if activity_type in {"running", "cycling", "swimming", "lap_swimming"}:
            copy["source_activity_type"] = activity_type
            copy.pop("type", None)
        sanitized.append(copy)
    return sanitized


def _is_retryable_model_error(exc: Exception) -> bool:
    error_message = str(exc).lower()
    return (
        "503" in error_message
        or "429" in error_message
        or ("unavailable" in error_message and "high demand" in error_message)
        or "high demand" in error_message
        or "try again later" in error_message
    )


def _retry_delay_seconds(exc: Exception) -> Optional[float]:
    retry_delay_match = re.search(
        r"['\"]?retryDelay['\"]?\s*:\s*['\"]?([0-9]+(?:\.[0-9]+)?)s",
        str(exc),
    )
    if not retry_delay_match:
        return None
    return float(retry_delay_match.group(1))


def _is_vertexai_payload_mismatch(exc: Exception) -> bool:
    error_message = str(exc)
    return (
        "responseMimeType" in error_message
        and "generation_config" in error_message
    )


def _extract_json_document(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    start_index = cleaned.find("{")
    end_index = cleaned.rfind("}")
    if start_index == -1 or end_index == -1 or end_index <= start_index:
        raise ReportParseError("AI 回傳內容不是 JSON 物件")

    return cleaned[start_index : end_index + 1]


def _parse_report_json(text: str) -> Dict[str, Any]:
    json_text = _extract_json_document(text)
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ReportParseError("AI 回傳內容不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise ReportParseError("AI 回傳內容必須是 JSON 物件")
    return payload


def _build_failure_report(reason: str) -> Dict[str, Any]:
    now = datetime.now().astimezone()
    return {
        "meta": {
            "generated_at": now.isoformat(timespec="seconds"),
            "analysis_period_weeks": 4,
            "today": now.date().isoformat(),
        },
        "error": {
            "message": reason,
            "source": "gemini",
        },
    }


def _generate_content_with_retries(model_name: str, full_prompt: str) -> Dict[str, Any]:
    for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
        try:
            print(f"正在嘗試使用模型: {model_name} (第 {attempt}/{MAX_RETRIES_PER_MODEL} 次)...")
            response = client.models.generate_content(
                model=model_name,
                contents=full_prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0,
                },
            )
            response_text = getattr(response, "text", "") or ""
            return _parse_report_json(response_text)
        except Exception as exc:
            should_retry = (
                attempt < MAX_RETRIES_PER_MODEL
                and (
                    _is_retryable_model_error(exc)
                    or isinstance(exc, ReportParseError)
                )
            )
            if should_retry:
                retry_delay_seconds = _retry_delay_seconds(exc)
                wait_seconds = (
                    retry_delay_seconds
                    if retry_delay_seconds is not None
                    else RETRY_BACKOFF_SECONDS * attempt
                )
                print(
                    f"模型 {model_name} 暫時高負載，第 {attempt} 次失敗，"
                    f"{wait_seconds} 秒後重試..."
                )
                time.sleep(wait_seconds)
                continue
            raise


def coach(
    data: List[Dict[str, Any]],
    user_data: Optional[Dict[str, Any]] = None,
    deterministic_context: Optional[Dict[str, Any]] = None,
    goal_path: str = "",
    goal_text: Optional[str] = None,
) -> Dict[str, Any]:
    global client
    system_prompt = _read_text_file(PROMPT_PATH)
    full_prompt = f"{system_prompt}\n\n{_build_context(data, user_data, goal_path, goal_text=goal_text, deterministic_context=deterministic_context)}"
    switched_to_vertexai = False

    for model_name in MODEL_FALLBACKS:
        try:
            return _generate_content_with_retries(model_name, full_prompt)
        except Exception as exc:
            if (
                not switched_to_vertexai
                and not getattr(client, "vertexai", False)
                and _is_vertexai_payload_mismatch(exc)
            ):
                print("偵測到 GCP API key 需走 Vertex AI 模式，切換後重試同一模型...")
                client = _build_genai_client(vertexai=True)
                switched_to_vertexai = True
                try:
                    return _generate_content_with_retries(model_name, full_prompt)
                except Exception as vertex_exc:
                    exc = vertex_exc
            if model_name == MODEL_FALLBACKS[-1]:
                print(f"所有模型皆調用失敗: {exc}")
                return _build_failure_report(str(exc))
            print(f"模型 {model_name} 暫時無法使用: {exc}，準備切換備援模型...")

    return _build_failure_report("AI 服務暫時無法連線。建議根據近期體感調整訓練量。")


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


def _write_local_report(report: Dict[str, Any], _source_csv_path: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")
    report_path = OUTPUT_DIR / f"ai_report_{timestamp}.json"

    with report_path.open("w", encoding="utf-8") as file_obj:
        json.dump(report, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")

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
