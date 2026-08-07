"""LINE Push Message API 客戶端。

設計原則：
- 結構化回傳 LineSendResult，讓上層可區分錯誤類型
- 429/5xx/timeout/ConnectionError 可重試，400/401/403 不重試
- log 不得包含 token、Authorization header 值或完整 group_id
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import requests

from src.notifications.constants import (
    CONNECT_TIMEOUT_SEC,
    LINE_MAX_MESSAGES_PER_PUSH,
    LINE_MAX_TEXT_LENGTH,
    LINE_PUSH_URL,
    MAX_ATTEMPTS,
    READ_TIMEOUT_SEC,
    RETRY_BACKOFF_SECONDS,
)
from src.notifications.text_utils import utf16_length

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
        text: 訊息文字。超過單一文字訊息上限時，保留所有內容並分批傳送。

    Returns:
        LineSendResult — 不含任何敏感資訊。
    """
    return send_push_messages(token, group_id, [text])


def send_push_messages(
    token: str,
    group_id: str,
    texts: Sequence[str],
) -> LineSendResult:
    """Send an explicitly grouped sequence of LINE text messages.

    Caller-provided message boundaries are retained. Any item above LINE's
    hard limit is additionally split before batching.
    """
    if isinstance(texts, str):
        raise TypeError("texts must be a sequence of strings, not a single string")

    messages: list[str] = []
    for text in texts:
        if not isinstance(text, str):
            raise TypeError("all LINE messages must be strings")
        messages.extend(_split_text_messages(text))
    if not messages:
        raise ValueError("at least one LINE message is required")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    with requests.Session() as http:
        total_attempts = 0
        batch_count = (len(messages) + LINE_MAX_MESSAGES_PER_PUSH - 1) // LINE_MAX_MESSAGES_PER_PUSH
        for batch_index in range(batch_count):
            batch_messages = messages[
                batch_index * LINE_MAX_MESSAGES_PER_PUSH:(batch_index + 1) * LINE_MAX_MESSAGES_PER_PUSH
            ]
            payload = {
                "to": group_id,
                "messages": [{"type": "text", "text": message} for message in batch_messages],
            }
            # key 對完全相同的收件人與 payload 穩定：同次重試與 24 小時內
            # 後續排程重跑，都不會重複推送已被 LINE 受理的前一批。
            batch_headers = {
                **headers,
                "X-Line-Retry-Key": _retry_key(group_id, messages, batch_index),
            }
            result = _send_payload(http, payload, batch_headers)
            total_attempts += result.attempts
            if not result.success:
                logger.error(
                    "LINE push batch %d/%d failed (status=%s, error=%s)",
                    batch_index + 1,
                    batch_count,
                    result.status_code,
                    result.error_type,
                )
                return LineSendResult(
                    success=False,
                    status_code=result.status_code,
                    attempts=total_attempts,
                    error_type=result.error_type,
                )

    return LineSendResult(
        success=True,
        status_code=200,
        attempts=total_attempts,
        error_type=None,
    )


def _send_payload(
    http: requests.Session,
    payload: dict[str, object],
    headers: dict[str, str],
) -> LineSendResult:
    """送出單一 LINE Push payload，保留既有的重試規則。"""
    last_status_code: int | None = None
    last_error_type: str | None = None

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
                return LineSendResult(True, 200, attempt, None)

            # 使用同一 retry key 的前一個 request 已被 LINE 接受。
            if resp.status_code == 409:
                logger.info("LINE push was already accepted (attempt %d)", attempt)
                return LineSendResult(True, 409, attempt, None)

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

            logger.error(
                "LINE push rejected with status %d (no retry, attempt %d)",
                resp.status_code,
                attempt,
            )
            error_type = "http_client_error" if 400 <= resp.status_code < 500 else "unexpected_http_status"
            return LineSendResult(False, resp.status_code, attempt, error_type)

        except requests.Timeout:
            last_error_type = "timeout"
            logger.warning("LINE push timed out (attempt %d/%d)", attempt, MAX_ATTEMPTS)
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])

        except requests.ConnectionError:
            last_error_type = "connection_error"
            logger.warning("LINE push connection error (attempt %d/%d)", attempt, MAX_ATTEMPTS)
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


def _retry_key(group_id: str, messages: list[str], batch_index: int) -> str:
    """Create a stable, position-specific retry key for one logical send."""
    payload = json.dumps(
        {"to": group_id, "messages": messages, "batch_index": batch_index},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, payload))


def _utf16_length(text: str) -> int:
    """LINE 的文字長度以 UTF-16 code units 計算。"""
    return utf16_length(text)


def _split_text_messages(text: str) -> list[str]:
    """依換行優先切割，保留所有文字且每則都符合 LINE 長度上限。"""
    if _utf16_length(text) <= LINE_MAX_TEXT_LENGTH:
        return [text]

    messages: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if _utf16_length(line) > LINE_MAX_TEXT_LENGTH:
            if current:
                messages.append(current)
                current = ""
            messages.extend(_split_long_text(line))
        elif current and _utf16_length(current) + _utf16_length(line) > LINE_MAX_TEXT_LENGTH:
            messages.append(current)
            current = line
        else:
            current += line

    if current:
        messages.append(current)
    return messages or [text]


def _split_long_text(text: str) -> list[str]:
    """將無法按換行切割的文字安全切成 UTF-16 長度上限內的片段。"""
    messages: list[str] = []
    current: list[str] = []
    current_length = 0
    for char in text:
        char_length = _utf16_length(char)
        if current and current_length + char_length > LINE_MAX_TEXT_LENGTH:
            messages.append("".join(current))
            current = []
            current_length = 0
        current.append(char)
        current_length += char_length
    if current:
        messages.append("".join(current))
    return messages
