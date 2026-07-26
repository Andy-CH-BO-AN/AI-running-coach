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
    #   "http_client_error" — 400/401/403 不重試
    #   "rate_limited"      — 429 重試後仍失敗
    #   "server_error"      — 5xx 重試後仍失敗
    #   "timeout"           — requests.Timeout 重試後仍失敗
    #   "connection_error"  — requests.ConnectionError 重試後仍失敗
    #   None                — 成功


def send_push_message(token: str, group_id: str, text: str) -> LineSendResult:
    """發送 LINE Push Message 至指定群組。

    Args:
        token: LINE Channel Access Token（不會出現在 log）。
        group_id: LINE 群組 ID（不會出現在 error log）。
        text: 訊息文字（最多 5000 字元）。

    Returns:
        LineSendResult — 不含任何敏感資訊。
    """
    payload = {
        "to": group_id,
        "messages": [{"type": "text", "text": text}],
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

                if resp.status_code in _NO_RETRY_CODES:
                    # 不重試，立即回傳
                    logger.error(
                        "LINE push rejected with status %d (no retry, attempt %d)",
                        resp.status_code,
                        attempt,
                    )
                    return LineSendResult(
                        success=False,
                        status_code=resp.status_code,
                        attempts=attempt,
                        error_type="http_client_error",
                    )

                # 429 / 5xx — 可重試
                last_error_type = "server_error" if resp.status_code >= 500 else "rate_limited"
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
