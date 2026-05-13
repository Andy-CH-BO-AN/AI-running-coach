"""Serve the local AI running coach dashboard.

The dashboard is intentionally a tiny local tool: static HTML/CSS/JS plus
read-only JSON endpoints for files already written to ``output/``.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


REPORT_RE = re.compile(r"^ai_report_(\d{8})\.json$")


@dataclass(frozen=True)
class DashboardPaths:
    repo_root: Path
    dashboard_dir: Path
    output_dir: Path


def default_paths() -> DashboardPaths:
    repo_root = Path(__file__).resolve().parents[2]
    return DashboardPaths(
        repo_root=repo_root,
        dashboard_dir=repo_root / "dashboard",
        output_dir=repo_root / "output",
    )


def discover_reports(output_dir: Path) -> list[dict[str, Any]]:
    """Return report metadata sorted newest first."""

    if not output_dir.exists():
        return []

    reports: list[dict[str, Any]] = []
    for path in output_dir.iterdir():
        match = REPORT_RE.match(path.name)
        if not match or not path.is_file():
            continue

        generated_at = None
        today = None
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            meta = payload.get("meta") if isinstance(payload, dict) else {}
            if isinstance(meta, dict):
                generated_at = meta.get("generated_at")
                today = meta.get("today")
        except (OSError, json.JSONDecodeError):
            generated_at = None
            today = None

        reports.append(
            {
                "file": path.name,
                "date": match.group(1),
                "generated_at": generated_at,
                "today": today,
                "size_bytes": path.stat().st_size,
            }
        )

    reports.sort(key=lambda item: item["date"], reverse=True)
    for index, report in enumerate(reports):
        report["is_latest"] = index == 0
    return reports


def safe_report_path(output_dir: Path, file_name: str) -> Path | None:
    """Resolve a report filename without allowing path traversal."""

    decoded = unquote(file_name)
    if not REPORT_RE.match(decoded):
        return None

    candidate = (output_dir / decoded).resolve()
    output_root = output_dir.resolve()
    if candidate.parent != output_root or not candidate.is_file():
        return None

    return candidate


def read_report(output_dir: Path, file_name: str) -> dict[str, Any] | None:
    report_path = safe_report_path(output_dir, file_name)
    if report_path is None:
        return None

    with report_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    return payload if isinstance(payload, dict) else None


def content_type_for(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(path.name)
    return content_type or "application/octet-stream"


def create_handler(paths: DashboardPaths) -> type[BaseHTTPRequestHandler]:
    class DashboardRequestHandler(BaseHTTPRequestHandler):
        server_version = "AIRunningCoachDashboard/1.0"

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            parsed = urlparse(self.path)
            request_path = parsed.path

            if request_path in {"", "/"}:
                self._send_file(paths.dashboard_dir / "index.html")
                return

            if request_path == "/api/reports":
                reports = discover_reports(paths.output_dir)
                self._send_json(
                    {
                        "reports": reports,
                        "latest": reports[0] if reports else None,
                    }
                )
                return

            if request_path.startswith("/api/reports/"):
                file_name = request_path.removeprefix("/api/reports/")
                try:
                    payload = read_report(paths.output_dir, file_name)
                except json.JSONDecodeError:
                    self._send_json({"error": "Invalid JSON report"}, HTTPStatus.BAD_REQUEST)
                    return

                if payload is None:
                    self._send_json({"error": "Report not found"}, HTTPStatus.NOT_FOUND)
                    return

                self._send_json(payload)
                return

            if request_path.startswith("/dashboard/"):
                relative = unquote(request_path.removeprefix("/dashboard/"))
                self._send_static(relative)
                return

            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _send_static(self, relative: str) -> None:
            if not relative or Path(relative).is_absolute():
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return

            candidate = (paths.dashboard_dir / relative).resolve()
            dashboard_root = paths.dashboard_dir.resolve()
            if dashboard_root not in candidate.parents or not candidate.is_file():
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return

            self._send_file(candidate)

        def _send_file(self, path: Path) -> None:
            if not path.is_file():
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return

            payload = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type_for(path)}; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

    return DashboardRequestHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the local AI running coach dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind. Defaults to 8765.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_paths().output_dir,
        help="Directory containing ai_report_YYYYMMDD.json files.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    defaults = default_paths()
    paths = DashboardPaths(
        repo_root=defaults.repo_root,
        dashboard_dir=defaults.dashboard_dir,
        output_dir=args.output_dir,
    )
    server = ThreadingHTTPServer((args.host, args.port), create_handler(paths))
    print(f"Dashboard running at http://{args.host}:{args.port}")
    print(f"Reading reports from {paths.output_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
