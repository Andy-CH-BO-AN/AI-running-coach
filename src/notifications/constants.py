"""LINE 通知模組常數。

所有可調整的門檻值集中於此，不應散落在其他模組中。
"""
from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────────
# Interval 工作段判定閾值
# ──────────────────────────────────────────────────────────────────────────────

# 有 cadence 欄位時，低於此值視為站立/慢走恢復段（spm）
MIN_WORK_CADENCE_SPM: int = 100

# 配速超過此值（秒/公里）視為恢復段：15:00/km = 900 sec/km
MAX_WORK_PACE_SEC_PER_KM: int = 900

# 距離過短視為恢復段（km）
MIN_WORK_DISTANCE_KM: float = 0.05

# ──────────────────────────────────────────────────────────────────────────────
# 工作段顯示限制
# ──────────────────────────────────────────────────────────────────────────────

# 超過此數量時截斷顯示
MAX_DISPLAYED_REPS: int = 12

# 截斷時顯示頭部段數
TRUNCATED_HEAD_COUNT: int = 5

# 截斷時顯示尾部段數
TRUNCATED_TAIL_COUNT: int = 3

# 距離摘要容差：各段距離落在中位數 ±此比例內，才摘要為固定距離
REP_DISTANCE_TOLERANCE: float = 0.10

# ──────────────────────────────────────────────────────────────────────────────
# LINE API
# ──────────────────────────────────────────────────────────────────────────────

LINE_PUSH_URL: str = "https://api.line.me/v2/bot/message/push"

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
