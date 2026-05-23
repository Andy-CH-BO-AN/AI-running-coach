#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
if [[ -x "$ROOT_DIR/.venv/bin/python" && -z "${PYTHON:-}" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

CHROME_BIN="${CHROME_BIN:-}"
if [[ -z "$CHROME_BIN" ]]; then
  if [[ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
    CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  elif command -v google-chrome-stable >/dev/null 2>&1; then
    CHROME_BIN="$(command -v google-chrome-stable)"
  elif command -v google-chrome >/dev/null 2>&1; then
    CHROME_BIN="$(command -v google-chrome)"
  elif command -v chromium >/dev/null 2>&1; then
    CHROME_BIN="$(command -v chromium)"
  else
    echo "Chrome binary not found. Set CHROME_BIN to run dashboard UI smoke." >&2
    exit 2
  fi
fi

HOST="${DASHBOARD_HOST:-127.0.0.1}"
PORT="${DASHBOARD_PORT:-8765}"
TARGET="http://${HOST}:${PORT}/"
REPORT_DATE="$(date +%Y%m%d)"
REPORT_DIR="$ROOT_DIR/tests/reports"
DESKTOP_SCREENSHOT="$REPORT_DIR/dashboard_smoke_desktop_${REPORT_DATE}.png"
MOBILE_SCREENSHOT="$REPORT_DIR/dashboard_smoke_mobile_${REPORT_DATE}.png"
SERVER_LOG="$REPORT_DIR/dashboard_smoke_server_${REPORT_DATE}.log"
CHROME_PROFILE="$(mktemp -d "${TMPDIR:-/tmp}/dashboard-ui-smoke.XXXXXX")"

mkdir -p "$REPORT_DIR"

cd "$ROOT_DIR"
"$PYTHON_BIN" -m src.dashboard.server --host "$HOST" --port "$PORT" >"$SERVER_LOG" 2>&1 &
SERVER_PID="$!"
cleanup() {
  kill "$SERVER_PID" >/dev/null 2>&1 || true
  wait "$SERVER_PID" >/dev/null 2>&1 || true
  rm -rf "$CHROME_PROFILE" || true
}
trap cleanup EXIT

run_chrome_screenshot() {
  local width="$1"
  local height="$2"
  local profile_name="$3"
  local screenshot_path="$4"

  rm -f "$screenshot_path"
  "$CHROME_BIN" \
    --headless --disable-gpu --hide-scrollbars --no-first-run --disable-extensions \
    --disable-background-networking --disable-sync --disable-component-update --disable-default-apps \
    --user-data-dir="$CHROME_PROFILE/$profile_name" \
    --run-all-compositor-stages-before-draw \
    --virtual-time-budget=5000 \
    --window-size="${width},${height}" \
    --screenshot="$screenshot_path" \
    "$TARGET" >>"$SERVER_LOG" 2>&1 &
  local chrome_pid="$!"

  for _ in {1..60}; do
    if [[ -s "$screenshot_path" ]]; then
      sleep 0.5
      if kill -0 "$chrome_pid" >/dev/null 2>&1; then
        kill "$chrome_pid" >/dev/null 2>&1 || true
      fi
      wait "$chrome_pid" >/dev/null 2>&1 || true
      return 0
    fi
    if ! kill -0 "$chrome_pid" >/dev/null 2>&1; then
      wait "$chrome_pid" >/dev/null 2>&1 || true
      break
    fi
    sleep 0.5
  done

  kill "$chrome_pid" >/dev/null 2>&1 || true
  wait "$chrome_pid" >/dev/null 2>&1 || true
  test -s "$screenshot_path"
}

for _ in {1..40}; do
  if curl -fsS "${TARGET}api/reports" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

curl -fsS "${TARGET}api/reports" >/dev/null

run_chrome_screenshot 1440 4200 desktop "$DESKTOP_SCREENSHOT"
run_chrome_screenshot 390 5200 mobile "$MOBILE_SCREENSHOT"

test -s "$DESKTOP_SCREENSHOT"
test -s "$MOBILE_SCREENSHOT"

echo "Dashboard UI smoke passed."
echo "Desktop screenshot: $DESKTOP_SCREENSHOT"
echo "Mobile screenshot: $MOBILE_SCREENSHOT"
echo "Server log: $SERVER_LOG"
