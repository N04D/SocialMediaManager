from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from channels.mastodon.client import MastodonApiClient  # noqa: E402
from channels.mastodon.instance import MastodonInstanceService, normalize_instance_origin  # noqa: E402
from channels.mastodon.transport import HttpMastodonApiTransport  # noqa: E402


def line(status: str, message: str) -> None:
    print(f"{status} {message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Mastodon channel doctor")
    parser.add_argument("instance_origin")
    parser.add_argument("--allow-localhost-http", action="store_true")
    parser.add_argument("--status-id", default=os.environ.get("MASTODON_STATUS_ID", ""))
    args = parser.parse_args(argv)
    try:
        origin = normalize_instance_origin(args.instance_origin, allow_localhost_http=args.allow_localhost_http)
        line("PASS", f"instance URL accepted: {origin}")
    except Exception as exc:
        line("FAIL", f"instance URL rejected: {getattr(exc, 'code', type(exc).__name__)}")
        return 2
    transport = HttpMastodonApiTransport(allow_localhost_http=args.allow_localhost_http)
    try:
        snapshot = MastodonInstanceService(
            transport=transport, allow_localhost_http=args.allow_localhost_http
        ).discover(origin)
        line(
            "PASS",
            f"discovery status={snapshot.software_status} max_characters={snapshot.max_characters} max_media={snapshot.max_media_attachments}",
        )
    except Exception as exc:
        line("FAIL", f"discovery failed: {getattr(exc, 'code', type(exc).__name__)}")
        return 2
    token = os.environ.get("MASTODON_ACCESS_TOKEN", "")
    if token:
        try:
            account = MastodonApiClient(origin=origin, transport=transport, access_token=token).verify_credentials()
            line("PASS", f"token verifies acct={account.get('acct') or account.get('username')}")
        except Exception as exc:
            line("FAIL", f"token verification failed: {getattr(exc, 'code', type(exc).__name__)}")
            return 2
        if args.status_id:
            try:
                status = MastodonApiClient(origin=origin, transport=transport, access_token=token).get_status(
                    args.status_id
                )
                line(
                    "PASS",
                    f"status metrics available favourites={status.get('favourites_count')} replies={status.get('replies_count')} reblogs={status.get('reblogs_count')}",
                )
            except Exception as exc:
                line("WARN", f"status read failed: {getattr(exc, 'code', type(exc).__name__)}")
                return 1
    else:
        line("WARN", "MASTODON_ACCESS_TOKEN not set; skipped token and metrics reads")
    line("PASS", "redaction policy active; no credential values printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
