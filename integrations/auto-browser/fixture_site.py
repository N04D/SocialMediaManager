from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / "fixture_uploads"


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.startswith("/download"):
            data = b"fixture download\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", "attachment; filename=fixture.txt")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith("/second"):
            self._html("Second Page", "<h1>Second page</h1><a href='/'>Back home</a>")
            return
        if self.path.startswith("/login"):
            self._html(
                "Fixture Login",
                """
                <h1>Fixture login</h1>
                <label>Email <input id="email" name="email" autocomplete="username"></label>
                <label>Password <input id="password" name="password" type="password"></label>
                <button role="button" aria-label="Sign in" data-testid="sign-in">Sign in</button>
                """,
            )
            return
        self._html(
            "Auto Browser Fixture",
            """
            <h1 data-stable="fixture-title">Auto Browser Fixture</h1>
            <button aria-label="Primary action" data-testid="primary-button">Primary action</button>
            <button aria-label="Duplicate action">Duplicate</button>
            <button aria-label="Duplicate action">Duplicate</button>
            <button aria-label="Disabled action" disabled>Disabled action</button>
            <label>Message <input id="message" name="message" placeholder="Type message"></label>
            <textarea aria-label="Long text" title="Long text area"></textarea>
            <input type="file" aria-label="Upload image" data-testid="upload-input">
            <p id="visible-text">Visible fixture text</p>
            <p id="hidden-text" hidden>Hidden fixture text</p>
            <a href="/second" title="Second page link">Second page</a>
            <button onclick="setTimeout(()=>{const e=document.createElement('p');e.id='delayed';e.textContent='Delayed ready';document.body.appendChild(e)}, 200)">Show delayed</button>
            <button onclick="window.open('/second','fixture-popup')">Open popup</button>
            <a href="/download">Download fixture</a>
            <script>
              window.fixtureState = {ready: true, count: 1};
            </script>
            """,
        )

    def do_POST(self) -> None:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        (UPLOAD_DIR / "last-upload.bin").write_bytes(body)
        self._json({"ok": True, "bytes": len(body)})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _html(self, title: str, body: str) -> None:
        payload = f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), FixtureHandler)
    print(f"fixture_url=http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
