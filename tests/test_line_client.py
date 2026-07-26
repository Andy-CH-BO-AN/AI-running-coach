"""
LINE Push Message 客戶端測試。

涵蓋：
- 發送成功回傳 LineSendResult(success=True)
- 400/401/403 不重試
- 429/5xx 重試後成功
- timeout / ConnectionError 重試
- 超過最大重試次數後回傳 success=False
- token / Authorization header 不出現在 log
- attempts 計數正確
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.notifications.line_client import LineSendResult, send_push_message


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_response(status_code: int, headers: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


TOKEN = "test_token_secret"
GROUP_ID = "C_group_id_secret"


# ──────────────────────────────────────────────────────────────────────────────
# 成功路徑
# ──────────────────────────────────────────────────────────────────────────────

class TestSendPushMessageSuccess:
    def test_success_returns_true(self):
        resp = _make_response(200)
        resp.raise_for_status = MagicMock()  # no-op on 200

        with patch("src.notifications.line_client.requests.Session") as mock_session_cls:
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            session.post.return_value = resp
            mock_session_cls.return_value = session

            result = send_push_message(TOKEN, GROUP_ID, "測試訊息")

        assert result.success is True
        assert result.status_code == 200
        assert result.attempts == 1
        assert result.error_type is None

    def test_correct_payload_sent(self):
        """確認 payload 含正確 group_id 與訊息文字。"""
        resp = _make_response(200)
        resp.raise_for_status = MagicMock()

        with patch("src.notifications.line_client.requests.Session") as mock_session_cls:
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            session.post.return_value = resp
            mock_session_cls.return_value = session

            send_push_message(TOKEN, GROUP_ID, "Hello")

            call_kwargs = session.post.call_args
            json_body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert json_body["to"] == GROUP_ID
            assert json_body["messages"][0]["text"] == "Hello"


# ──────────────────────────────────────────────────────────────────────────────
# 不重試的錯誤碼
# ──────────────────────────────────────────────────────────────────────────────

class TestNoRetryErrors:
    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 413, 422])
    def test_client_error_no_retry(self, status_code: int):
        resp = _make_response(status_code)

        with patch("src.notifications.line_client.requests.Session") as mock_session_cls:
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            session.post.return_value = resp
            mock_session_cls.return_value = session

            result = send_push_message(TOKEN, GROUP_ID, "msg")

        assert result.success is False
        assert result.status_code == status_code
        assert result.attempts == 1  # 只嘗試一次，不重試
        assert result.error_type == "http_client_error"

    @pytest.mark.parametrize("status_code", [301, 302, 304])
    def test_unexpected_http_status_no_retry(self, status_code: int):
        resp = _make_response(status_code)

        with patch("src.notifications.line_client.requests.Session") as mock_session_cls:
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            session.post.return_value = resp
            mock_session_cls.return_value = session

            result = send_push_message(TOKEN, GROUP_ID, "msg")

        assert result.success is False
        assert result.status_code == status_code
        assert result.attempts == 1  # 3xx 狀態碼只嘗試一次，不重試
        assert result.error_type == "unexpected_http_status"


# ──────────────────────────────────────────────────────────────────────────────
# 可重試的錯誤
# ──────────────────────────────────────────────────────────────────────────────

class TestRetryableErrors:
    def test_429_retries_and_succeeds(self):
        resp_429 = _make_response(429)
        resp_200 = _make_response(200)
        resp_200.raise_for_status = MagicMock()

        with patch("src.notifications.line_client.requests.Session") as mock_session_cls, \
             patch("src.notifications.line_client.time.sleep"):
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            session.post.side_effect = [resp_429, resp_200]
            mock_session_cls.return_value = session

            result = send_push_message(TOKEN, GROUP_ID, "msg")

        assert result.success is True
        assert result.attempts == 2

    def test_429_reads_retry_after_header(self):
        resp_429 = _make_response(429, headers={"Retry-After": "3"})
        resp_200 = _make_response(200)
        resp_200.raise_for_status = MagicMock()

        with patch("src.notifications.line_client.requests.Session") as mock_session_cls, \
             patch("src.notifications.line_client.time.sleep") as mock_sleep:
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            session.post.side_effect = [resp_429, resp_200]
            mock_session_cls.return_value = session

            send_push_message(TOKEN, GROUP_ID, "msg")

        # 第一次重試前應 sleep 至少 3 秒 (Retry-After)
        mock_sleep.assert_called_once_with(3.0)

    @pytest.mark.parametrize("status_code", [500, 502, 503])
    def test_5xx_retries_and_succeeds(self, status_code: int):
        resp_5xx = _make_response(status_code)
        resp_200 = _make_response(200)
        resp_200.raise_for_status = MagicMock()

        with patch("src.notifications.line_client.requests.Session") as mock_session_cls, \
             patch("src.notifications.line_client.time.sleep"):
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            session.post.side_effect = [resp_5xx, resp_200]
            mock_session_cls.return_value = session

            result = send_push_message(TOKEN, GROUP_ID, "msg")

        assert result.success is True
        assert result.attempts == 2

    def test_timeout_retries(self):
        with patch("src.notifications.line_client.requests.Session") as mock_session_cls, \
             patch("src.notifications.line_client.time.sleep"):
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            resp_200 = _make_response(200)
            resp_200.raise_for_status = MagicMock()
            session.post.side_effect = [requests.Timeout(), resp_200]
            mock_session_cls.return_value = session

            result = send_push_message(TOKEN, GROUP_ID, "msg")

        assert result.success is True
        assert result.attempts == 2

    def test_connection_error_retries(self):
        with patch("src.notifications.line_client.requests.Session") as mock_session_cls, \
             patch("src.notifications.line_client.time.sleep"):
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            resp_200 = _make_response(200)
            resp_200.raise_for_status = MagicMock()
            session.post.side_effect = [requests.ConnectionError(), resp_200]
            mock_session_cls.return_value = session

            result = send_push_message(TOKEN, GROUP_ID, "msg")

        assert result.success is True
        assert result.attempts == 2

    def test_max_attempts_exhausted_returns_failure(self):
        """3 次全失敗後回傳 success=False，attempts=3。"""
        with patch("src.notifications.line_client.requests.Session") as mock_session_cls, \
             patch("src.notifications.line_client.time.sleep"):
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            session.post.side_effect = [
                requests.Timeout(),
                requests.Timeout(),
                requests.Timeout(),
            ]
            mock_session_cls.return_value = session

            result = send_push_message(TOKEN, GROUP_ID, "msg")

        assert result.success is False
        assert result.attempts == 3
        assert result.error_type == "timeout"


# ──────────────────────────────────────────────────────────────────────────────
# Token 安全性
# ──────────────────────────────────────────────────────────────────────────────

class TestTokenSecurity:
    def test_token_not_in_log(self, caplog):
        """Token 不得出現在任何 log 訊息中。"""
        resp_500 = _make_response(500)
        resp_200 = _make_response(200)
        resp_200.raise_for_status = MagicMock()

        with patch("src.notifications.line_client.requests.Session") as mock_session_cls, \
             patch("src.notifications.line_client.time.sleep"), \
             caplog.at_level(logging.DEBUG, logger="src.notifications.line_client"):
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            session.post.side_effect = [resp_500, resp_200]
            mock_session_cls.return_value = session

            send_push_message(TOKEN, GROUP_ID, "msg")

        for record in caplog.records:
            assert TOKEN not in record.getMessage(), \
                f"Token leaked in log: {record.getMessage()}"
            assert "Bearer" not in record.getMessage() or TOKEN not in record.getMessage()

    def test_group_id_not_in_error_log(self, caplog):
        """GROUP_ID 不得出現在 error log 中。"""
        with patch("src.notifications.line_client.requests.Session") as mock_session_cls, \
             patch("src.notifications.line_client.time.sleep"), \
             caplog.at_level(logging.ERROR, logger="src.notifications.line_client"):
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            session.post.side_effect = requests.Timeout()
            mock_session_cls.return_value = session

            send_push_message(TOKEN, GROUP_ID, "msg")

        for record in caplog.records:
            assert GROUP_ID not in record.getMessage(), \
                f"Group ID leaked in log: {record.getMessage()}"


# ──────────────────────────────────────────────────────────────────────────────
# LineSendResult 型別
# ──────────────────────────────────────────────────────────────────────────────

class TestLineSendResult:
    def test_result_fields(self):
        r = LineSendResult(success=True, status_code=200, attempts=1, error_type=None)
        assert r.success is True
        assert r.status_code == 200
        assert r.attempts == 1
        assert r.error_type is None
