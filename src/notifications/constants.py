"""LINE 通知模組常數。

所有可調整的門檻值集中於此，不應散落在其他模組中。
"""
from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────────
# LINE API
# ──────────────────────────────────────────────────────────────────────────────

LINE_PUSH_URL: str = "https://api.line.me/v2/bot/message/push"

# LINE Messaging API text-message ceiling.
LINE_MAX_TEXT_LENGTH: int = 5000

# A Push Message request can carry up to five message objects.
LINE_MAX_MESSAGES_PER_PUSH: int = 5

# Per-run safety caps. Degraded mode has no persistent deduplication.
MAX_LINE_NOTIFICATIONS_PER_RUN: int = 20
MAX_DEGRADED_LINE_NOTIFICATIONS_PER_RUN: int = 3

# 連線超時（秒）
CONNECT_TIMEOUT_SEC: int = 5

# 讀取超時（秒）
READ_TIMEOUT_SEC: int = 10

# 最大嘗試次數（含第一次）
MAX_ATTEMPTS: int = 3

# 退避間隔（秒），長度應為 MAX_ATTEMPTS - 1
RETRY_BACKOFF_SECONDS: list[float] = [1.0, 2.0]

# ──────────────────────────────────────────────────────────────────────────────
# PostgreSQL Advisory Lock
# ──────────────────────────────────────────────────────────────────────────────

# 固定 lock key，確保同時只有一個 LINE notification job 執行
# 使用固定整數，與其他模組區隔（Postgres pg_try_advisory_lock 接受 bigint）
LINE_NOTIFICATION_LOCK_KEY: int = 20260726004
