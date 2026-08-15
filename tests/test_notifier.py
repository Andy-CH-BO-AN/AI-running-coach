"""Public wrapper contracts for Activity LINE notifications."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.notifications.notifier import run_line_notification


def test_missing_line_configuration_disables_notification_without_reading_context(tmp_path: Path) -> None:
    missing_context = tmp_path / "missing.json"

    with patch.dict(os.environ, {}, clear=True):
        result = run_line_notification(str(missing_context))

    assert (result.status, result.sent, result.failed) == ("disabled", 0, 0)


def test_invalid_context_json_propagates_before_notification_side_effects(tmp_path: Path) -> None:
    context = tmp_path / "invalid.json"
    context.write_text("{invalid", encoding="utf-8")

    with patch.dict(
        os.environ,
        {"LINE_CHANNEL_ACCESS_TOKEN": "test-token", "LINE_GROUP_ID": "test-group"},
        clear=True,
    ), pytest.raises(ValueError):
        run_line_notification(str(context))
