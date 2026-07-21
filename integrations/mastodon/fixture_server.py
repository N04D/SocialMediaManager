from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STATE = {
    "apps": [],
    "tokens": set(),
    "media": {},
    "statuses": {},
    "idempotency": {},
    "next_media": 1,
    "next_status": 1,
}


class MastodonFixtureHandler(BaseHTTPRequestHandler):
    mode = "healthy"

    def log_message(self, fmt, *args):  # noqa: A003
        return

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/v2/instance":
            if self.mode == "malformed response":
                self._raw(b"<html>bad</html>", content_type="text/html")
                return
            self._json(
                {
                    "domain": self.headers.get("Host", "127.0.0.1"),
                    "version": "4.3.0",
                    "api_versions": {"mastodon": 4},
                    "software": {"name": "mastodon", "version": "4.3.0"},
                    "configuration": {
                        "statuses": {
                            "max_characters": 500 if self.mode != "instance limits changed" else 240,
                            "max_media_attachments": 4,
                            "characters_reserved_per_url": 23,
                        },
                        "media_attachments": {
                            "supported_mime_types": ["image/jpeg", "image/png"],
                            "image_size_limit": 8000000,
                            "image_matrix_limit": 16777216,
                            "description_limit": 1500,
                        },
                    },
                },
                headers={
                    "X-RateLimit-Limit": "300",
                    "X-RateLimit-Remaining": "299",
                    "X-RateLimit-Reset": str(int(time.time()) + 60),
                },
            )
            return
        if parsed.path == "/oauth/authorize":
            self._json({"authorization": "fixture", "query": parse_qs(parsed.query)})
            return
        if parsed.path == "/api/v1/accounts/verify_credentials":
            if self.mode == "invalid token" or "Authorization" not in self.headers:
                self._json({"error": "invalid token"}, status=401)
                return
            if self.mode == "insufficient scope":
                self._json({"error": "insufficient scope"}, status=403)
                return
            self._json(
                {
                    "id": "acct-1",
                    "username": "pilot",
                    "acct": "pilot",
                    "display_name": "Pilot",
                    "url": f"{self._origin()}/@pilot",
                }
            )
            return
        if parsed.path.startswith("/api/v1/media/"):
            media_id = parsed.path.rsplit("/", 1)[-1]
            media = STATE["media"].get(media_id)
            if not media:
                self._json({"error": "not found"}, status=404)
                return
            if self.mode == "media processing pending":
                self._json({"id": media_id})
                return
            if self.mode == "media processing failed":
                self._json({"id": media_id, "error": "processing failed"}, status=422)
                return
            self._json(media | {"url": f"{self._origin()}/media/{media_id}"})
            return
        if parsed.path.startswith("/api/v1/statuses/"):
            status_id = parsed.path.rsplit("/", 1)[-1]
            if self.mode == "status not found":
                self._json({"error": "not found"}, status=404)
                return
            status = STATE["statuses"].get(status_id)
            if not status:
                self._json({"error": "not found"}, status=404)
                return
            self._json(status)
            return
        self.send_error(404)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        form = parse_qs(raw.decode("utf-8", errors="ignore"))
        if self.mode == "rate limited":
            self._json({"error": "rate limited"}, status=429, headers={"Retry-After": "60"})
            return
        if parsed.path == "/api/v1/apps":
            app = {
                "id": "app-1",
                "name": form.get("client_name", ["SocialMediaManager"])[0],
                "client_id": "fixture-client-id",
                "client_secret": "fixture-client-secret",
                "redirect_uri": form.get("redirect_uris", [""])[0],
            }
            STATE["apps"].append(app)
            self._json(app)
            return
        if parsed.path == "/oauth/token":
            token = "fixture-access-token"
            STATE["tokens"].add(token)
            self._json(
                {
                    "access_token": token,
                    "token_type": "Bearer",
                    "scope": form.get("scope", ["profile read:statuses write:statuses write:media"])[0],
                    "created_at": int(time.time()),
                }
            )
            return
        if parsed.path == "/oauth/revoke":
            self._json({})
            return
        if parsed.path == "/api/v2/media":
            media_id = str(STATE["next_media"])
            STATE["next_media"] += 1
            media = {"id": media_id, "type": "image", "preview_url": f"{self._origin()}/media/{media_id}/preview"}
            STATE["media"][media_id] = media
            self._json(media)
            return
        if parsed.path == "/api/v1/statuses":
            idem = self.headers.get("Idempotency-Key", "")
            if self.mode == "status create timeout vóór mutation":
                time.sleep(2)
                return
            if idem and idem in STATE["idempotency"]:
                self._json(STATE["idempotency"][idem])
                return
            status_id = str(STATE["next_status"])
            STATE["next_status"] += 1
            status = {
                "id": status_id,
                "uri": f"{self._origin()}/users/pilot/statuses/{status_id}",
                "url": f"{self._origin()}/@pilot/{status_id}",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "account": {"id": "acct-1"},
                "favourites_count": 2,
                "replies_count": 1,
                "reblogs_count": 3,
            }
            STATE["statuses"][status_id] = status
            if idem:
                STATE["idempotency"][idem] = status
            if self.mode == "status create timeout na mutation":
                time.sleep(2)
                return
            self._json(status)
            return
        self.send_error(404)

    def do_DELETE(self):  # noqa: N802
        self._json({})

    def _origin(self) -> str:
        return f"http://{self.headers.get('Host', '127.0.0.1')}"

    def _json(self, payload, *, status=200, headers=None):
        data = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _raw(self, payload: bytes, *, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8916)
    parser.add_argument("--mode", default="healthy")
    args = parser.parse_args()
    MastodonFixtureHandler.mode = args.mode
    ThreadingHTTPServer((args.host, args.port), MastodonFixtureHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
