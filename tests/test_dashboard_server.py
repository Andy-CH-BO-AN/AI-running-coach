import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

import src.dashboard.server as dashboard_server
from src.dashboard.server import DashboardPaths, create_handler, discover_reports, read_report, safe_report_path


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_discover_reports_sorts_newest_first_and_reads_meta(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    write_json(
        output_dir / "ai_report_20260510.json",
        {"meta": {"generated_at": "2026-05-10T10:00:00+08:00", "today": "2026-05-10"}},
    )
    write_json(
        output_dir / "ai_report_20260513.json",
        {"meta": {"generated_at": "2026-05-13T10:00:00+08:00", "today": "2026-05-13"}},
    )
    write_json(output_dir / "notes.json", {"ignored": True})

    reports = discover_reports(output_dir)

    assert [report["file"] for report in reports] == [
        "ai_report_20260513.json",
        "ai_report_20260510.json",
    ]
    assert reports[0]["is_latest"] is True
    assert reports[1]["is_latest"] is False
    assert reports[0]["today"] == "2026-05-13"


def test_safe_report_path_rejects_path_traversal_and_wrong_names(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    report_path = output_dir / "ai_report_20260513.json"
    write_json(report_path, {"meta": {}})

    assert safe_report_path(output_dir, "ai_report_20260513.json") == report_path.resolve()
    assert safe_report_path(output_dir, "../ai_report_20260513.json") is None
    assert safe_report_path(output_dir, "ai_report_latest.json") is None
    assert safe_report_path(output_dir, "ai_report_20260514.md") is None


def test_read_report_returns_json_object_only(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    write_json(output_dir / "ai_report_20260513.json", {"meta": {"today": "2026-05-13"}})
    write_json(output_dir / "ai_report_20260514.json", [{"not": "object"}])

    assert read_report(output_dir, "ai_report_20260513.json") == {"meta": {"today": "2026-05-13"}}
    assert read_report(output_dir, "ai_report_20260514.json") is None
    assert read_report(output_dir, "missing.json") is None


def test_read_report_handles_non_object_meta_with_db_trend_enabled(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    payload = {"meta": None, "coaching_summary": {"top_3_actions": ["跑 30 分鐘"]}}
    write_json(output_dir / "ai_report_20260513.json", payload)

    seen = {}

    def fake_build_db_fitness_trend(today):
        seen["today"] = today
        return None

    monkeypatch.setattr(dashboard_server, "_build_db_fitness_trend", fake_build_db_fitness_trend)

    assert read_report(output_dir, "ai_report_20260513.json", include_db_fitness_trend=True) == payload
    assert seen["today"] is None


def test_favicon_returns_no_content_without_console_404(tmp_path):
    dashboard_dir = tmp_path / "dashboard"
    output_dir = tmp_path / "output"
    dashboard_dir.mkdir()
    output_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<!doctype html><title>Dashboard</title>", encoding="utf-8")
    paths = DashboardPaths(repo_root=tmp_path, dashboard_dir=dashboard_dir, output_dir=output_dir)
    server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(paths))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/favicon.ico") as response:
            assert response.status == 204
            assert response.read() == b""
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
