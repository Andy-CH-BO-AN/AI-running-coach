from src.db import mirror


def test_sync_shadow_database_returns_none_when_mirror_mode_disabled(monkeypatch):
    monkeypatch.setattr(mirror, "mirror_mode_enabled", lambda: False)

    assert mirror.sync_shadow_database() is None


def test_sync_shadow_database_uses_scoped_table_sync(monkeypatch):
    monkeypatch.setattr(mirror, "mirror_mode_enabled", lambda: True)
    captured = {}

    def _fake_sync(source, target, table_names=None):
        captured["source"] = source
        captured["target"] = target
        captured["table_names"] = table_names
        return {"rows_copied": 1}

    monkeypatch.setattr(mirror, "sync_database_targets", _fake_sync)

    result = mirror.sync_shadow_database()

    assert result == {"rows_copied": 1}
    assert captured["source"] == "local"
    assert captured["target"] == "cloud"
    assert captured["table_names"] == mirror.MIRROR_TABLES


def test_validate_shadow_parity_uses_scoped_table_compare(monkeypatch):
    monkeypatch.setattr(mirror, "mirror_mode_enabled", lambda: True)
    captured = {}

    def _fake_compare(source, target, table_names=None):
        captured["source"] = source
        captured["target"] = target
        captured["table_names"] = table_names
        return {"ok": True}

    monkeypatch.setattr(mirror, "compare_database_targets", _fake_compare)

    result = mirror.validate_shadow_parity()

    assert result == {"ok": True}
    assert captured["source"] == "local"
    assert captured["target"] == "cloud"
    assert captured["table_names"] == mirror.MIRROR_TABLES
