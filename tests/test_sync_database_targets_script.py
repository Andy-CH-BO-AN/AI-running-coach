import json
import sys

import pytest

from src.scripts import sync_database_targets as script


def test_validate_only_compares_without_sync(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["sync_database_targets", "--source", "local", "--target", "cloud", "--validate-only"],
    )
    monkeypatch.setattr(
        script,
        "sync_database_targets",
        lambda *args, **kwargs: pytest.fail("validate-only must not sync"),
    )

    captured = {}

    def _fake_compare(source, target):
        captured["source"] = source
        captured["target"] = target
        return {"ok": True, "mismatches": []}

    monkeypatch.setattr(script, "compare_database_targets", _fake_compare)

    assert script.main() == 0

    assert captured == {"source": "local", "target": "cloud"}
    assert json.loads(capsys.readouterr().out) == {"ok": True, "mismatches": []}


def test_skip_validate_syncs_without_compare(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sync_database_targets",
            "--source",
            "local",
            "--target",
            "cloud",
            "--batch-size",
            "25",
            "--skip-validate",
        ],
    )
    monkeypatch.setattr(
        script,
        "compare_database_targets",
        lambda *args, **kwargs: pytest.fail("skip-validate must not compare"),
    )

    captured = {}

    def _fake_sync(*, source_target, target_target, batch_size):
        captured["source_target"] = source_target
        captured["target_target"] = target_target
        captured["batch_size"] = batch_size
        return {"source": source_target, "target": target_target, "tables": []}

    monkeypatch.setattr(script, "sync_database_targets", _fake_sync)

    assert script.main() == 0

    assert captured == {"source_target": "local", "target_target": "cloud", "batch_size": 25}
    assert json.loads(capsys.readouterr().out) == {"source": "local", "target": "cloud", "tables": []}


def test_cli_rejects_same_source_and_target(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["sync_database_targets", "--source", "local", "--target", "local"],
    )
    monkeypatch.setattr(
        script,
        "sync_database_targets",
        lambda *args, **kwargs: pytest.fail("same-source rejection must happen before sync"),
    )
    monkeypatch.setattr(
        script,
        "compare_database_targets",
        lambda *args, **kwargs: pytest.fail("same-source rejection must happen before compare"),
    )

    with pytest.raises(SystemExit, match="--source and --target must be different"):
        script.main()
