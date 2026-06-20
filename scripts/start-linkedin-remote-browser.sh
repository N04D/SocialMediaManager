#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${REMOTE_DEBUGGING_PORT:-9222}"
PROFILE_DIR="${LINKEDIN_BROWSER_PROFILE_DIR:-$ROOT_DIR/linkedin_session}"
START_URL="${SOCIALMEDIAMANAGER_START_URL:-http://127.0.0.1:8080}"

if command -v google-chrome >/dev/null 2>&1; then
  BROWSER_BIN="$(command -v google-chrome)"
elif command -v chromium >/dev/null 2>&1; then
  BROWSER_BIN="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
  BROWSER_BIN="$(command -v chromium-browser)"
elif command -v brave-browser >/dev/null 2>&1; then
  BROWSER_BIN="$(command -v brave-browser)"
else
  echo "No supported Chromium-based browser found." >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"

nohup "$BROWSER_BIN" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE_DIR" \
  "$START_URL" >/dev/null 2>&1 &

echo "Started remote-debugging browser on http://127.0.0.1:$PORT"
echo "Set linkedin_remote_debugging_url in config.json to http://127.0.0.1:$PORT"
echo "The browser started on: $START_URL"
