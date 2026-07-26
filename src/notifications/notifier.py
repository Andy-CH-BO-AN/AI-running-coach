"""LINE 通知協調器。

流程：
1. 檢查環境變數 → 未啟用則 skip
2. 取得 PostgreSQL advisory lock（避免並行發送）
3. 讀取 coach_context JSON
4. 查詢 DB 已記錄的 activity_id
5. 若 DB 為空 → seed baseline，不發送
6. 計算新活動 → 無新活動則 skip
7. 逐筆發送 → LINE 成功後立即 commit DB 紀錄
8. 釋放 lock（finally 確保一定執行）

TODO: 未來 coach_context 加入 start_time_local / end_time_local 後，
      可依相同 source_activity_type 與時間間隔合併相鄰活動為一則訊息。
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator

from sqlalchemy.orm import Session

from src.db.repositories import (
    get_notified_activity_ids,
    is_notification_system_initialized,
    record_notification,
    seed_baseline_notifications,
)
from src.notifications.constants import LINE_NOTIFICATION_LOCK_KEY
from src.notifications.formatter import format_activity_message
from src.notifications.line_client import send_push_message

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Result type
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class NotificationResult:
    """通知流程執行結果。

    status:
        "disabled"       — LINE 環境變數未設定
        "skipped_locked" — 無法取得 advisory lock（另一個 job 正在執行）
        "seeded"         — 首次執行，已 seed baseline，未發送任何訊息
        "no_new"         — 無新活動，未發送
        "done"           — 執行完畢（部分或全部成功）
        "error"          — 讀取 JSON 或 DB 查詢等非 LINE API 錯誤
    """

    status: str
    sent: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return f"NotificationResult(status={self.status}, sent={self.sent}, failed={self.failed})"


# ──────────────────────────────────────────────────────────────────────────────
# DB session helper（方便測試替換）
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def _get_db_session() -> Generator[Session, None, None]:
    from src.db.session import SessionLocal
    with SessionLocal() as session:
        yield session


# ──────────────────────────────────────────────────────────────────────────────
# Advisory lock helpers（使用獨立 Connection 避免 pool 回收與不同連線問題）
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def _get_lock_connection() -> Generator[Any, None, None]:
    """建立專用於 Advisory Lock 的獨立 DB Connection。"""
    from src.db.session import engine
    with engine.connect() as conn:
        yield conn


def _acquire_advisory_lock(conn: Any) -> bool:
    """嘗試取得 PostgreSQL advisory lock。

    使用 pg_try_advisory_lock（非阻塞），回傳 True 表示取得成功。
    傳入 dedicated Connection 確保整個流程鎖在同一條實體連線。
    """
    from sqlalchemy import text
    result = conn.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": LINE_NOTIFICATION_LOCK_KEY},
    )
    return bool(result.scalar())


def _release_advisory_lock(conn: Any) -> None:
    """釋放 PostgreSQL advisory lock。"""
    from sqlalchemy import text
    conn.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": LINE_NOTIFICATION_LOCK_KEY},
    )


# ──────────────────────────────────────────────────────────────────────────────
# 輔助函式
# ──────────────────────────────────────────────────────────────────────────────

def _load_coach_context(path: str) -> dict[str, Any]:
    """讀取 coach_context JSON 檔案。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _extract_all_sessions(context: dict[str, Any]) -> list[tuple[dict, dict]]:
    """從 coach_context 取出所有 (session, week) 對，保持原始順序。"""
    pairs: list[tuple[dict, dict]] = []
    for week in context.get("weekly_analysis", []):
        for session in week.get("sessions", []):
            pairs.append((session, week))
    return pairs


def _find_week_for_session(
    session_dict: dict[str, Any],
    weekly_analysis: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """找到包含此 activity 的 weekly_analysis entry。"""
    aid = session_dict.get("activity_id")
    for week in weekly_analysis:
        for s in week.get("sessions", []):
            if s.get("activity_id") == aid:
                return week
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 主函式
# ──────────────────────────────────────────────────────────────────────────────

def run_line_notification(coach_context_path: str) -> NotificationResult:
    """執行 LINE 群組通知流程。

    Args:
        coach_context_path: coach_context JSON 檔案的絕對路徑。

    Returns:
        NotificationResult — 描述執行結果與統計。
        不會 raise；所有錯誤均 log 後回傳適當狀態。
    """
    # ── 1. 檢查環境變數
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    group_id = os.environ.get("LINE_GROUP_ID")

    if not token or not group_id:
        logger.info(
            "LINE notification disabled: missing required environment variables "
            "(LINE_CHANNEL_ACCESS_TOKEN and/or LINE_GROUP_ID)"
        )
        return NotificationResult(status="disabled")

    # ── 2. 讀取 coach_context
    try:
        context = _load_coach_context(coach_context_path)
    except (json.JSONDecodeError, OSError):
        logger.exception(
            "LINE notification: failed to load coach_context from %s",
            coach_context_path,
        )
        return NotificationResult(status="error")

    # ── 3. Dedicated Connection Advisory Lock + 主流程
    with _get_lock_connection() as lock_conn:
        lock_acquired = False
        try:
            lock_acquired = _acquire_advisory_lock(lock_conn)
            if not lock_acquired:
                logger.info(
                    "LINE notification: skipped (advisory lock held by another process)"
                )
                return NotificationResult(status="skipped_locked")

            with _get_db_session() as db_session:
                return _run_with_lock(context, db_session, token, group_id)

        except Exception:
            logger.exception(
                "LINE notification: unexpected error in notification flow"
            )
            return NotificationResult(status="error")

        finally:
            if lock_acquired:
                try:
                    _release_advisory_lock(lock_conn)
                except Exception:
                    logger.exception("LINE notification: failed to release advisory lock")


def _run_with_lock(
    context: dict[str, Any],
    db_session: Session,
    token: str,
    group_id: str,
) -> NotificationResult:
    """在 advisory lock 保護下執行通知流程。"""
    # ── 查詢已記錄的 activity_id
    try:
        notified_ids = get_notified_activity_ids(db_session)
        is_initialized = len(notified_ids) > 0
    except Exception:
        logger.exception("LINE notification: DB query failed")
        db_session.rollback()
        return NotificationResult(status="error")

    all_pairs = _extract_all_sessions(context)
    all_ids = [s.get("activity_id") for s, _ in all_pairs if s.get("activity_id") is not None]

    # ── 首次執行：seed baseline
    if not is_initialized:
        logger.info(
            "LINE notification: first run detected — seeding %d activities as baseline",
            len(all_ids),
        )
        try:
            seed_baseline_notifications(db_session, all_ids)
        except Exception:
            logger.exception("LINE notification: DB error during baseline seed")
            # rollback 讓 session 回到乾淨狀態
            db_session.rollback()
            return NotificationResult(status="error")
        return NotificationResult(status="seeded")

    # ── 計算新活動
    new_pairs = [
        (s, w) for s, w in all_pairs
        if s.get("activity_id") is not None
        and s["activity_id"] not in notified_ids
    ]

    if not new_pairs:
        logger.info("LINE notification: no new activities to notify")
        return NotificationResult(status="no_new")

    logger.info(
        "LINE notification: %d new activities to send", len(new_pairs)
    )

    # ── 逐筆發送
    sent = 0
    failed = 0

    for activity, week in new_pairs:
        activity_id = activity["activity_id"]
        try:
            message = format_activity_message(activity, week)
        except Exception:
            logger.exception(
                "LINE notification: formatter error for activity %s", activity_id
            )
            failed += 1
            continue

        result = send_push_message(token, group_id, message)

        if result.success:
            # LINE 成功後立即 commit DB 紀錄（每筆獨立，不因後續失敗 rollback）
            try:
                record_notification(db_session, activity_id)
                sent += 1
                logger.info(
                    "LINE notification: sent and recorded activity %s", activity_id
                )
            except Exception:
                # LINE 已發送但 DB 寫入失敗 → 下次可能重複發送，需明確 log 並 rollback 清理 session
                logger.exception(
                    "LINE notification: LINE sent successfully but DB commit FAILED "
                    "for activity %s — this activity may be sent again on next run",
                    activity_id,
                )
                db_session.rollback()
                failed += 1
        else:
            logger.error(
                "LINE notification: send FAILED for activity %s "
                "(status=%s, attempts=%d, error=%s) — will retry on next run",
                activity_id,
                result.status_code,
                result.attempts,
                result.error_type,
            )
            failed += 1

    return NotificationResult(status="done", sent=sent, failed=failed)
