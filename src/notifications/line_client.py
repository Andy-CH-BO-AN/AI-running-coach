"""LINE Push Message API 客戶端。

設計原則：
- 結構化回傳 LineSendResult，讓上層可區分錯誤類型
- 429/5xx/timeout/ConnectionError 可重試，400/401/403 不重試
- log 不得包含 token、Authorization header 值或完整 group_id
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

from src.notifications.constants import (
    CONNECT_TIMEOUT_SEC,
    LINE_MAX_TEXT_LENGTH,
    LINE_PUSH_URL,
    MAX_ATTEMPTS,
    READ_TIMEOUT_SEC,
    RETRY_BACKOFF_SECONDS,
)

logger = logging.getLogger(__name__)

# 不重試的 HTTP 狀態碼（客戶端錯誤）
_NO_RETRY_CODES: frozenset[int] = frozenset({400, 401, 403})


@dataclass
class LineSendResult:
    """LINE Push API 發送結果。不包含任何 token 或敏感資訊。"""

    success: bool
    status_code: int | None
    attempts: int
    error_type: str | None
    # error_type 可能值：
    #   "http_client_error"      — 4xx (除了 429 外) 不重試
    #   "unexpected_http_status" — 3xx 等其餘非 200 狀態碼不重試
    #   "rate_limited"           — 429 重試後仍失敗
    #   "server_error"           — 5xx 重試後仍失敗
    #   "timeout"                — requests.Timeout 重試後仍失敗
    #   "connection_error"       — requests.ConnectionError 重試後仍失敗
    #   None                     — 成功


def send_push_message(token: str, group_id: str, text: str) -> LineSendResult:
    """發送 LINE Push Message 至指定群組。

    Args:
        token: LINE Channel Access Token（不會出現在 log）。
        group_id: LINE 群組 ID（不會出現在 error log）。
        text: 訊息文字（最多 5000 字元；超長安全截斷）。

    Returns:
        LineSendResult — 不含任何敏感資訊。
    """
    safe_text = _truncate_text(text)
    payload = {
        "to": group_id,
        "messages": [{"type": "text", "text": safe_text}],
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    last_status_code: int | None = None
    last_error_type: str | None = None

    with requests.Session() as http:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = http.post(
                    LINE_PUSH_URL,
                    json=payload,
                    headers=headers,
                    timeout=(CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC),
                )
                last_status_code = resp.status_code

                if resp.status_code == 200:
                    logger.info("LINE push sent successfully (attempt %d)", attempt)
                    return LineSendResult(
                        success=True,
                        status_code=200,
                        attempts=attempt,
                        error_type=None,
                    )

                # 重試條件：僅限 429 (Rate Limit) 與 500-599 (Server Error)
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    last_error_type = "rate_limited" if resp.status_code == 429 else "server_error"
                    logger.warning(
                        "LINE push returned status %d (attempt %d/%d)",
                        resp.status_code,
                        attempt,
                        MAX_ATTEMPTS,
                    )
                    if attempt < MAX_ATTEMPTS:
                        if resp.status_code == 429:
                            retry_after = _parse_retry_after(resp.headers)
                            backoff = retry_after if retry_after is not None else RETRY_BACKOFF_SECONDS[attempt - 1]
                        else:
                            backoff = RETRY_BACKOFF_SECONDS[attempt - 1]
                        time.sleep(backoff)
                    continue

                # 其餘所有非 200 狀態碼（例如 4xx 除了 429 外、3xx 等）— 不重試，立即回傳
                logger.error(
                    "LINE push rejected with status %d (no retry, attempt %d)",
                    resp.status_code,
                    attempt,
                )
                error_type = "http_client_error" if 400 <= resp.status_code < 500 else "unexpected_http_status"
                return LineSendResult(
                    success=False,
                    status_code=resp.status_code,
                    attempts=attempt,
                    error_type=error_type,
                )

            except requests.Timeout:
                last_error_type = "timeout"
                logger.warning(
                    "LINE push timed out (attempt %d/%d)", attempt, MAX_ATTEMPTS
                )
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])

            except requests.ConnectionError:
                last_error_type = "connection_error"
                logger.warning(
                    "LINE push connection error (attempt %d/%d)", attempt, MAX_ATTEMPTS
                )
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])

    logger.error(
        "LINE push failed after %d attempts (last error: %s, status: %s)",
        MAX_ATTEMPTS,
        last_error_type,
        last_status_code,
    )
    return LineSendResult(
        success=False,
        status_code=last_status_code,
        attempts=MAX_ATTEMPTS,
        error_type=last_error_type,
    )


def _parse_retry_after(headers: dict) -> float | None:
    """解析 Retry-After header，回傳秒數；解析失敗回傳 None。"""
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _truncate_text(text: str) -> str:
    """Keep payloads within LINE's limit without logging message contents."""
    if len(text) <= LINE_MAX_TEXT_LENGTH:
        return text

    suffix = "\n…訊息過長，後續內容已截斷。"
    safe_length = LINE_MAX_TEXT_LENGTH - len(suffix)
    logger.warning(
        "LINE push text truncated from %d to %d characters",
        len(text),
        LINE_MAX_TEXT_LENGTH,
    )
    return f"{text[:safe_length]}{suffix}"
