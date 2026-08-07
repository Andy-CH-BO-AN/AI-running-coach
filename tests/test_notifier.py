"""
通知協調器（notifier）測試。

涵蓋：
- 環境變數缺失時回傳 disabled，不呼叫 LINE API
- 首次執行（DB 空）seed baseline，不發送 LINE
- 無新活動回傳 no_new，不呼叫 LINE API
- 新活動只發一次（rerun 不重複）
- LINE 成功後才寫入 line_notifications
- LINE 失敗不寫入紀錄，不影響後續活動
- 部分成功部分失敗的計數與狀態
- Advisory lock 已被占用時回傳 skipped_locked，不發送
- 第一筆成功第二筆失敗時第一筆紀錄仍保留
- LINE 成功但 DB commit 失敗時有明確 error log
- runner 使用實際產生的 coach_context path
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from src.notifications.line_client import LineSendResult
from src.db.settings import is_database_connection_error
from src.notifications.notifier import (
    NotificationDatabaseAccess,
    NotificationResult,
    run_daily_line_notification,
    run_line_notification,
)


# ──────────────────────────────────────────────────────────────────────────────
# Test fixtures & helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_coach_context(sessions_by_week: list[list[dict]] | None = None) -> dict:
    """建立最小可用的 coach_context 結構。"""
    if sessions_by_week is None:
        sessions_by_week = [[
            {"activity_id": 1001, "date": "2026-07-20", "type": "easy",
             "source_activity_type": "running", "distance_km": 8.0,
             "duration_min": 50.0, "training_load": 100.0, "avg_hr": 150,
             "avg_pace": "6:15", "segments": [],
             "environment": {"estimated_temp_c": 28.0, "humidity_pct": None, "hr_impact": None},
             "data_quality": {"status": "complete", "missing_fields": []}},
        ]]

    weekly_analysis = []
    for idx, sessions in enumerate(sessions_by_week):
        weekly_analysis.append({
            "week_label": f"Week {idx}",
            "week_start": "2026-07-20",
            "week_end": "2026-07-26",
            "derived_total_distance_km": 30.0,
            "derived_total_duration_min": 180.0,
            "derived_training_load": 500.0,
            "sessions": sessions,
        })

    return {"meta": {"today": "2026-07-26"}, "weekly_analysis": weekly_analysis}


def _write_context(tmp_path: Path, context: dict) -> Path:
    p = tmp_path / "coach_context_20260726.json"
    p.write_text(json.dumps(context), encoding="utf-8")
    return p


DUMMY_TOKEN = "dummy_token"
DUMMY_GROUP = "dummy_group"

SUCCESS_RESULT = LineSendResult(success=True, status_code=200, attempts=1, error_type=None)
FAIL_RESULT = LineSendResult(success=False, status_code=500, attempts=3, error_type="server_error")


def _connection_error(message: str = "connection refused") -> OperationalError:
    return OperationalError("SELECT 1", {}, ConnectionError(message))


@pytest.fixture(autouse=True)
def mock_lock_connection():
    """自動 mock _get_lock_connection，避免單元測試嘗試連線實體 PostgreSQL。"""
    mock_conn = MagicMock()
    with patch("src.notifications.notifier._get_lock_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        yield mock_conn


# ──────────────────────────────────────────────────────────────────────────────
# 環境變數缺失
# ──────────────────────────────────────────────────────────────────────────────

class TestMissingEnvVars:
    def test_missing_token_returns_disabled(self, tmp_path):
        ctx_path = _write_context(tmp_path, _make_coach_context())
        with patch.dict(os.environ, {}, clear=True):
            result = run_line_notification(str(ctx_path))
        assert result.status == "disabled"

    def test_missing_group_id_returns_disabled(self, tmp_path):
        ctx_path = _write_context(tmp_path, _make_coach_context())
        with patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN}, clear=True):
            result = run_line_notification(str(ctx_path))
        assert result.status == "disabled"

    def test_disabled_does_not_call_line_api(self, tmp_path):
        ctx_path = _write_context(tmp_path, _make_coach_context())
        with patch.dict(os.environ, {}, clear=True), \
             patch("src.notifications.notifier.send_push_messages") as mock_send:
            run_line_notification(str(ctx_path))
        mock_send.assert_not_called()

    def test_disabled_logs_message(self, tmp_path, caplog):
        ctx_path = _write_context(tmp_path, _make_coach_context())
        with patch.dict(os.environ, {}, clear=True), \
             caplog.at_level(logging.INFO, logger="src.notifications.notifier"):
            run_line_notification(str(ctx_path))
        assert any("disabled" in r.getMessage().lower() or
                   "missing" in r.getMessage().lower()
                   for r in caplog.records)


# ──────────────────────────────────────────────────────────────────────────────
# 首次執行：Seed baseline
# ──────────────────────────────────────────────────────────────────────────────

class TestSeedBaseline:
    def _env(self):
        return {"LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN, "LINE_GROUP_ID": DUMMY_GROUP}

    def test_empty_db_seeds_and_returns_seeded(self, tmp_path):
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value=set()), \
             patch("src.notifications.notifier.seed_baseline_notifications") as mock_seed, \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"):
            result = run_line_notification(str(ctx_path))

        assert result.status == "seeded"
        mock_seed.assert_called_once()

    def test_seed_does_not_call_line_api(self, tmp_path):
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value=set()), \
             patch("src.notifications.notifier.seed_baseline_notifications"), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.send_push_messages") as mock_send:
            run_line_notification(str(ctx_path))

        mock_send.assert_not_called()

    def test_first_run_empty_context_then_second_run_new_activity_sends_notification(self, tmp_path):
        """第一次 context 無活動 (seeded)，第二次新增一筆活動時應正常發送 LINE 訊息。"""
        empty_ctx_path = _write_context(tmp_path, _make_coach_context(sessions_by_week=[[]]))
        new_activity_ctx_path = _write_context(tmp_path, _make_coach_context(sessions_by_week=[[
            {"activity_id": 1001, "date": "2026-07-20", "type": "easy",
             "source_activity_type": "running", "distance_km": 5.0,
             "duration_min": 30.0, "training_load": 50.0, "avg_hr": 140,
             "avg_pace": "6:00", "segments": [],
             "environment": {"estimated_temp_c": None, "humidity_pct": None, "hr_impact": None},
             "data_quality": {"status": "complete", "missing_fields": []}}
        ]]))

        # 1. 第一次執行 (empty context) -> get_notified_activity_ids 返回 set()，系統進行 baseline seed
        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value=set()), \
             patch("src.notifications.notifier.seed_baseline_notifications") as mock_seed, \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.send_push_messages") as mock_send_1:
            res1 = run_line_notification(str(empty_ctx_path))

        assert res1.status == "seeded"
        mock_seed.assert_called_once()
        mock_send_1.assert_not_called()

        # 2. 第二次執行 (new activity 1001) -> notified_ids = {-1} (sentinel marker)
        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={-1}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.record_notification") as mock_record_2, \
             patch("src.notifications.notifier.send_push_messages", return_value=SUCCESS_RESULT) as mock_send_2:
            res2 = run_line_notification(str(new_activity_ctx_path))

        assert res2.status == "done"
        assert res2.sent == 1
        mock_send_2.assert_called_once()
        assert mock_record_2.call_count == 1
        assert mock_record_2.call_args[0][1] == 1001


# ──────────────────────────────────────────────────────────────────────────────
# 無新活動
# ──────────────────────────────────────────────────────────────────────────────

class TestNoNewActivity:
    def _env(self):
        return {"LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN, "LINE_GROUP_ID": DUMMY_GROUP}

    def test_all_notified_returns_no_new(self, tmp_path):
        context = _make_coach_context()
        ctx_path = _write_context(tmp_path, context)
        all_ids = {1001}

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value=all_ids), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.send_push_messages") as mock_send:
            result = run_line_notification(str(ctx_path))

        assert result.status == "no_new"
        mock_send.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# 正常發送流程
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalSend:
    def _env(self):
        return {"LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN, "LINE_GROUP_ID": DUMMY_GROUP}

    def test_new_activity_sends_once(self, tmp_path):
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.record_notification") as mock_record, \
             patch("src.notifications.notifier.send_push_messages", return_value=SUCCESS_RESULT):
            result = run_line_notification(str(ctx_path))

        assert result.status == "done"
        assert result.sent == 1
        assert result.failed == 0
        mock_record.assert_called_once()

    def test_activity_message_pages_are_sent_together_before_db_write(self, tmp_path):
        ctx_path = _write_context(tmp_path, _make_coach_context())
        pages = ["活動總覽", "分段明細\n休息｜0:30"]

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.format_activity_messages", return_value=pages), \
             patch("src.notifications.notifier.send_push_messages", return_value=SUCCESS_RESULT) as send, \
             patch("src.notifications.notifier.record_notification") as record:
            result = run_line_notification(str(ctx_path))

        assert result.sent == 1
        send.assert_called_once_with(DUMMY_TOKEN, DUMMY_GROUP, pages)
        record.assert_called_once()

    def test_line_success_then_db_write(self, tmp_path):
        """LINE 成功後才寫入 DB。"""
        ctx_path = _write_context(tmp_path, _make_coach_context())
        call_order = []

        def mock_send(*args, **kwargs):
            call_order.append("send")
            return SUCCESS_RESULT

        def mock_record(*args, **kwargs):
            call_order.append("record")

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value=set()), \
             patch("src.notifications.notifier.seed_baseline_notifications"), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"):
            # 首次執行會 seed，不會 send；用有歷史紀錄的情境
            pass  # 改用下方直接測試

        # 直接測試有新活動的情境
        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.send_push_messages", side_effect=mock_send), \
             patch("src.notifications.notifier.record_notification", side_effect=mock_record):
            run_line_notification(str(ctx_path))

        assert call_order == ["send", "record"], \
            f"預期 send→record 順序，實際：{call_order}"

    def test_line_failure_no_db_write(self, tmp_path):
        """LINE 失敗不寫入 DB。"""
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.record_notification") as mock_record, \
             patch("src.notifications.notifier.send_push_messages", return_value=FAIL_RESULT):
            result = run_line_notification(str(ctx_path))

        assert result.failed == 1
        assert result.sent == 0
        mock_record.assert_not_called()

    def test_rerun_not_sent_twice(self, tmp_path):
        """rerun 時，已通知的活動不重複發送。"""
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={1001}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.send_push_messages") as mock_send:
            result = run_line_notification(str(ctx_path))

        mock_send.assert_not_called()
        assert result.status == "no_new"


# ──────────────────────────────────────────────────────────────────────────────
# 部分成功部分失敗
# ──────────────────────────────────────────────────────────────────────────────

class TestPartialSuccess:
    def _env(self):
        return {"LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN, "LINE_GROUP_ID": DUMMY_GROUP}

    def _make_two_activity_context(self, tmp_path: Path) -> Path:
        sessions = [
            {"activity_id": 1001, "date": "2026-07-20", "type": "easy",
             "source_activity_type": "running", "distance_km": 5.0,
             "duration_min": 30.0, "training_load": 80.0, "avg_hr": 150,
             "avg_pace": "6:00", "segments": [],
             "environment": {"estimated_temp_c": None, "humidity_pct": None, "hr_impact": None},
             "data_quality": {"status": "complete", "missing_fields": []}},
            {"activity_id": 1002, "date": "2026-07-20", "type": "easy",
             "source_activity_type": "running", "distance_km": 3.0,
             "duration_min": 20.0, "training_load": 50.0, "avg_hr": 145,
             "avg_pace": "6:40", "segments": [],
             "environment": {"estimated_temp_c": None, "humidity_pct": None, "hr_impact": None},
             "data_quality": {"status": "complete", "missing_fields": []}},
        ]
        return _write_context(tmp_path, _make_coach_context([[sessions[0], sessions[1]]]))

    def test_first_success_second_fail_counts_correct(self, tmp_path):
        ctx_path = self._make_two_activity_context(tmp_path)

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.record_notification"), \
             patch("src.notifications.notifier.send_push_messages",
                   side_effect=[SUCCESS_RESULT, FAIL_RESULT]):
            result = run_line_notification(str(ctx_path))

        assert result.sent == 1
        assert result.failed == 1

    def test_first_success_second_fail_first_record_kept(self, tmp_path):
        """第一筆成功紀錄不受第二筆失敗影響。"""
        ctx_path = self._make_two_activity_context(tmp_path)
        recorded_ids = []

        def mock_record(session, activity_id):
            recorded_ids.append(activity_id)

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.record_notification", side_effect=mock_record), \
             patch("src.notifications.notifier.send_push_messages",
                   side_effect=[SUCCESS_RESULT, FAIL_RESULT]):
            run_line_notification(str(ctx_path))

        assert 1002 in recorded_ids
        assert 1001 not in recorded_ids


# ──────────────────────────────────────────────────────────────────────────────
# Advisory Lock
# ──────────────────────────────────────────────────────────────────────────────

class TestAdvisoryLock:
    def _env(self):
        return {"LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN, "LINE_GROUP_ID": DUMMY_GROUP}

    def test_lock_occupied_returns_skipped_locked(self, tmp_path):
        """無法取得 advisory lock 時回傳 skipped_locked，不發送。"""
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=False), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.send_push_messages") as mock_send:
            result = run_line_notification(str(ctx_path))

        assert result.status == "skipped_locked"
        mock_send.assert_not_called()

    def test_lock_released_after_success(self, tmp_path):
        """正常流程後 lock 必須被釋放。"""
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock") as mock_release, \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.send_push_messages", return_value=SUCCESS_RESULT), \
             patch("src.notifications.notifier.record_notification"):
            run_line_notification(str(ctx_path))

        mock_release.assert_called_once()

    def test_lock_released_on_exception(self, tmp_path):
        """即使發生例外，lock 仍必須被釋放。"""
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock") as mock_release, \
             patch("src.notifications.notifier._get_db_session"), \
            patch("src.notifications.notifier.get_notified_activity_ids",
                   side_effect=RuntimeError("DB down")):
            with pytest.raises(RuntimeError, match="DB down"):
                run_line_notification(str(ctx_path))

        mock_release.assert_called_once()

    def test_connection_error_before_send_uses_stateless_degraded_mode(self, tmp_path):
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock") as mock_release, \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.get_notified_activity_ids", side_effect=_connection_error()), \
             patch("src.notifications.notifier.send_push_messages", return_value=SUCCESS_RESULT) as send:
            result = run_line_notification(str(ctx_path))

        assert result.status == "stateless_done"
        assert result.sent == 1
        send.assert_called_once()
        mock_release.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# DB commit 失敗
# ──────────────────────────────────────────────────────────────────────────────

class TestDbCommitFailure:
    def _env(self):
        return {"LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN, "LINE_GROUP_ID": DUMMY_GROUP}

    def test_db_commit_failure_logs_warning_without_error_details(self, tmp_path, caplog):
        """LINE 成功但 DB commit 失敗時必須明確記錄可重複推播風險。"""
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
            patch("src.notifications.notifier._get_db_session"), \
            patch("src.notifications.notifier.send_push_messages", return_value=SUCCESS_RESULT), \
            patch("src.notifications.notifier.record_notification",
                   side_effect=_connection_error()), \
             caplog.at_level(logging.WARNING, logger="src.notifications.notifier"):
            result = run_line_notification(str(ctx_path))

        assert result.failed == 1
        warning_messages = " ".join(r.getMessage() for r in caplog.records)
        assert "1001" in warning_messages
        assert "may be sent again" in warning_messages
        assert "DB commit failed" not in warning_messages

    def test_non_connection_db_write_error_propagates(self, tmp_path):
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.send_push_messages", return_value=SUCCESS_RESULT), \
             patch(
                 "src.notifications.notifier.record_notification",
                 side_effect=IntegrityError("INSERT", {}, Exception("constraint failed")),
             ), pytest.raises(IntegrityError):
            run_line_notification(str(ctx_path))


class TestNotificationCaps:
    def _env(self) -> dict[str, str]:
        return {
            "LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN,
            "LINE_GROUP_ID": DUMMY_GROUP,
        }

    @staticmethod
    def _many_activity_context(count: int) -> dict:
        sessions = [
            {
                "activity_id": activity_id,
                "date": f"2026-07-{(activity_id % 28) + 1:02d}",
                "type": "easy",
                "source_activity_type": "running",
                "distance_km": 5.0,
                "duration_min": 30.0,
                "training_load": 50.0,
                "avg_hr": 140,
                "avg_pace": "6:00",
                "segments": [],
                "environment": {},
                "data_quality": {"status": "complete", "missing_fields": []},
            }
            for activity_id in range(1, count + 1)
        ]
        return _make_coach_context([sessions])

    def test_normal_mode_caps_to_twenty_and_defers_remaining(self, tmp_path, caplog):
        ctx_path = _write_context(tmp_path, self._many_activity_context(21))

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch("src.notifications.notifier.record_notification"), \
             patch("src.notifications.notifier.send_push_messages", return_value=SUCCESS_RESULT) as send, \
             caplog.at_level(logging.WARNING, logger="src.notifications.notifier"):
            result = run_line_notification(str(ctx_path))

        assert result.status == "done"
        assert result.sent == 20
        assert send.call_count == 20
        assert any("deferring 1 activities" in record.getMessage() for record in caplog.records)

    def test_normal_mode_stops_after_notification_persistence_connection_failure(self, tmp_path, caplog):
        ctx_path = _write_context(tmp_path, self._many_activity_context(4))

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
             patch("src.notifications.notifier._get_db_session"), \
             patch(
                 "src.notifications.notifier.record_notification",
                 side_effect=_connection_error(),
             ) as record, \
             patch("src.notifications.notifier.send_push_messages", return_value=SUCCESS_RESULT) as send, \
             caplog.at_level(logging.WARNING, logger="src.notifications.notifier"):
            result = run_line_notification(str(ctx_path))

        assert result.status == "done"
        assert result.sent == 0
        assert result.failed == 1
        assert send.call_count == 1
        assert record.call_count == 1
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "stopping delivery" in messages
        assert "3 activities not sent" in messages

    def test_explicit_stateless_mode_caps_to_three_without_lock_or_session(self, tmp_path, caplog):
        ctx_path = _write_context(tmp_path, self._many_activity_context(4))

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier._get_lock_connection") as lock, \
             patch("src.notifications.notifier._get_db_session") as session, \
             patch("src.notifications.notifier.send_push_messages", return_value=SUCCESS_RESULT) as send, \
             caplog.at_level(logging.WARNING, logger="src.notifications.notifier"):
            result = run_daily_line_notification(str(ctx_path), database=None)

        assert result.status == "stateless_done"
        assert result.sent == 3
        assert send.call_count == 3
        lock.assert_not_called()
        session.assert_not_called()
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "Repeated notifications are possible" in messages
        assert "stateless notification capped" in messages


# ──────────────────────────────────────────────────────────────────────────────
# JSON 損壞
# ──────────────────────────────────────────────────────────────────────────────

class TestBadJson:
    def _env(self):
        return {"LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN, "LINE_GROUP_ID": DUMMY_GROUP}

    def test_bad_json_raises_to_fail_workflow(self, tmp_path):
        """非 DB context 資料錯誤不能被 stateless fallback 吞掉。"""
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")

        with patch.dict(os.environ, self._env()), pytest.raises(json.JSONDecodeError):
            run_line_notification(str(p))


# ──────────────────────────────────────────────────────────────────────────────
# NotificationResult 型別
# ──────────────────────────────────────────────────────────────────────────────

class TestNotificationResult:
    def test_result_fields(self):
        r = NotificationResult(status="done", sent=3, failed=1)
        assert r.status == "done"
        assert r.sent == 3
        assert r.failed == 1

    def test_str_representation(self):
        r = NotificationResult(status="done", sent=2, failed=0)
        s = str(r)
        assert "done" in s
        assert "2" in s


# ──────────────────────────────────────────────────────────────────────────────
# Formatter 例外處理 (F8)
# ──────────────────────────────────────────────────────────────────────────────

class TestFormatterException:
    def _env(self):
        return {"LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN, "LINE_GROUP_ID": DUMMY_GROUP}

    def test_formatter_exception_raises_to_fail_workflow(self, tmp_path):
        """非 DB formatter 錯誤不能被 stateless fallback 吞掉。"""
        ctx_path = _write_context(tmp_path, _make_coach_context())

        with patch.dict(os.environ, self._env()), \
             patch("src.notifications.notifier.get_notified_activity_ids", return_value={9999}), \
             patch("src.notifications.notifier._acquire_advisory_lock", return_value=True), \
             patch("src.notifications.notifier._release_advisory_lock"), \
            patch("src.notifications.notifier._get_db_session"), \
            patch("src.notifications.notifier.format_activity_messages", side_effect=Exception("Formatter crash")):
            with pytest.raises(Exception, match="Formatter crash"):
                run_line_notification(str(ctx_path))


class TestCloudDailyRunNotificationPolicy:
    @staticmethod
    def _many_activity_context(count: int) -> dict:
        sessions = [
            {
                "activity_id": activity_id,
                "date": f"2026-07-{activity_id:02d}",
                "type": "easy",
                "source_activity_type": "running",
                "distance_km": 5.0,
                "duration_min": 30.0,
                "training_load": 50.0,
                "avg_hr": 140,
                "avg_pace": "6:00",
                "segments": [],
                "environment": {},
                "data_quality": {"status": "complete", "missing_fields": []},
            }
            for activity_id in range(1, count + 1)
        ]
        return _make_coach_context([sessions])

    @staticmethod
    def _database_access():
        state = {"available": True, "revocations": 0}
        session = MagicMock()
        connection = MagicMock()

        def revoke(_exc):
            if state["available"]:
                state["available"] = False
                state["revocations"] += 1
                session.invalidate()
                connection.invalidate()

        @contextmanager
        def session_context():
            try:
                yield session
            except SQLAlchemyError as exc:
                if is_database_connection_error(exc):
                    revoke(exc)
                raise

        @contextmanager
        def connection_context():
            try:
                yield connection
            except SQLAlchemyError as exc:
                if is_database_connection_error(exc):
                    revoke(exc)
                raise

        access = NotificationDatabaseAccess(
            is_available=lambda: state["available"],
            session=session_context,
            lock_connection=connection_context,
            revoke=revoke,
        )
        return access, state, session, connection

    @staticmethod
    def _env():
        return {
            "LINE_CHANNEL_ACCESS_TOKEN": DUMMY_TOKEN,
            "LINE_GROUP_ID": DUMMY_GROUP,
        }

    def test_degraded_daily_notification_is_stateless_and_capped_at_three(
        self,
        tmp_path,
    ):
        ctx_path = _write_context(tmp_path, self._many_activity_context(4))

        with patch.dict(os.environ, self._env(), clear=True), patch(
            "src.notifications.notifier._acquire_advisory_lock"
        ) as lock, patch(
            "src.notifications.notifier.send_push_messages",
            return_value=SUCCESS_RESULT,
        ) as send:
            result = run_daily_line_notification(str(ctx_path), database=None)

        assert result.status == "stateless_done"
        assert result.sent == 3
        assert send.call_count == 3
        lock.assert_not_called()

    def test_sent_but_unrecorded_consumes_one_stateless_slot_without_resend(
        self,
        tmp_path,
    ):
        ctx_path = _write_context(tmp_path, self._many_activity_context(5))
        access, state, session, _connection = self._database_access()

        with patch.dict(os.environ, self._env(), clear=True), patch(
            "src.notifications.notifier.get_notified_activity_ids",
            return_value={9999},
        ), patch(
            "src.notifications.notifier._acquire_advisory_lock",
            return_value=True,
        ), patch(
            "src.notifications.notifier._release_advisory_lock"
        ) as release, patch(
            "src.notifications.notifier.format_activity_messages",
            side_effect=lambda activity, _week: [str(activity["activity_id"])],
        ), patch(
            "src.notifications.notifier.send_push_messages",
            return_value=SUCCESS_RESULT,
        ) as send, patch(
            "src.notifications.notifier.record_notification",
            side_effect=_connection_error(),
        ) as record:
            result = run_daily_line_notification(str(ctx_path), database=access)

        sent_ids = [call_args.args[2][0] for call_args in send.call_args_list]
        assert result.status == "persistence_loss_done"
        assert result.sent == 3
        assert result.failed == 0
        assert len(sent_ids) == 3
        assert len(set(sent_ids)) == 3
        assert record.call_count == 1
        assert state == {"available": False, "revocations": 1}
        release.assert_not_called()
        session.rollback.assert_not_called()

    def test_connection_loss_before_send_revokes_before_unlock_and_sends_three_stateless(
        self,
        tmp_path,
    ):
        ctx_path = _write_context(tmp_path, self._many_activity_context(4))
        access, state, _session, _connection = self._database_access()

        with patch.dict(os.environ, self._env(), clear=True), patch(
            "src.notifications.notifier._acquire_advisory_lock",
            return_value=True,
        ), patch(
            "src.notifications.notifier._release_advisory_lock"
        ) as release, patch(
            "src.notifications.notifier.get_notified_activity_ids",
            side_effect=_connection_error(),
        ), patch(
            "src.notifications.notifier.send_push_messages",
            return_value=SUCCESS_RESULT,
        ) as send:
            result = run_daily_line_notification(str(ctx_path), database=access)

        assert result.status == "persistence_loss_done"
        assert result.sent == 3
        assert state == {"available": False, "revocations": 1}
        assert send.call_count == 3
        release.assert_not_called()

    def test_release_connection_loss_revokes_without_second_unlock_or_resend(
        self,
        tmp_path,
    ):
        ctx_path = _write_context(tmp_path, self._many_activity_context(1))
        access, state, _session, _connection = self._database_access()

        with patch.dict(os.environ, self._env(), clear=True), patch(
            "src.notifications.notifier._acquire_advisory_lock",
            return_value=True,
        ), patch(
            "src.notifications.notifier._release_advisory_lock",
            side_effect=_connection_error(),
        ) as release, patch(
            "src.notifications.notifier.get_notified_activity_ids",
            return_value={9999},
        ), patch(
            "src.notifications.notifier.record_notification"
        ), patch(
            "src.notifications.notifier.send_push_messages",
            return_value=SUCCESS_RESULT,
        ) as send:
            result = run_daily_line_notification(str(ctx_path), database=access)

        assert result.status == "done"
        assert result.sent == 1
        assert state == {"available": False, "revocations": 1}
        assert release.call_count == 1
        assert send.call_count == 1

    def test_nontransient_persistence_error_fails_closed_without_mode_change(
        self,
        tmp_path,
    ):
        ctx_path = _write_context(tmp_path, self._many_activity_context(1))
        access, state, _session, _connection = self._database_access()

        with patch.dict(os.environ, self._env(), clear=True), patch(
            "src.notifications.notifier._acquire_advisory_lock",
            return_value=True,
        ), patch(
            "src.notifications.notifier._release_advisory_lock"
        ) as release, patch(
            "src.notifications.notifier.get_notified_activity_ids",
            return_value={9999},
        ), patch(
            "src.notifications.notifier.record_notification",
            side_effect=IntegrityError("INSERT", {}, Exception("constraint failed")),
        ), patch(
            "src.notifications.notifier.send_push_messages",
            return_value=SUCCESS_RESULT,
        ), pytest.raises(IntegrityError):
            run_daily_line_notification(str(ctx_path), database=access)

        assert state == {"available": True, "revocations": 0}
        assert release.call_count == 1

    def test_formatter_error_propagates_without_revoking_persistence(
        self,
        tmp_path,
    ):
        ctx_path = _write_context(tmp_path, self._many_activity_context(1))
        access, state, _session, _connection = self._database_access()

        with patch.dict(os.environ, self._env(), clear=True), patch(
            "src.notifications.notifier._acquire_advisory_lock",
            return_value=True,
        ), patch(
            "src.notifications.notifier._release_advisory_lock"
        ) as release, patch(
            "src.notifications.notifier.get_notified_activity_ids",
            return_value={9999},
        ), patch(
            "src.notifications.notifier.format_activity_messages",
            side_effect=ValueError("formatter failed"),
        ), pytest.raises(ValueError, match="formatter failed"):
            run_daily_line_notification(str(ctx_path), database=access)

        assert state == {"available": True, "revocations": 0}
        assert release.call_count == 1
