from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from channels.youtube.channel import YouTubeChannelService, asset_checksum
from channels.youtube.models import YouTubePublishPlan
from channels.youtube.transport import HttpYouTubeTransport


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one private YouTube upload smoke.")
    parser.add_argument("--privacy", default="private", choices=("private",))
    parser.add_argument("--notify-subscribers", default="false", choices=("false",))
    parser.parse_args()
    required = ("YOUTUBE_ACCESS_TOKEN", "YOUTUBE_ASSET_PATH")
    if not all(os.environ.get(key) for key in required):
        print("REAL YOUTUBE SHORT UPLOAD SMOKE: NOT CONFIGURED")
        return 0
    path = os.environ["YOUTUBE_ASSET_PATH"]
    plan = YouTubePublishPlan(
        execution_id="phase40-real-smoke",
        asset_id="phase40-managed-smoke-asset",
        asset_path=path,
        asset_checksum=asset_checksum(path),
        title="Social Media Manager Phase 40 Private Upload Test",
        description="Private operational smoke test.",
        privacy="private",
        notify_subscribers=False,
        channel_account_id="youtube:operator",
        duration=float(os.environ.get("YOUTUBE_ASSET_DURATION", "1")),
        width=int(os.environ.get("YOUTUBE_ASSET_WIDTH", "1080")),
        height=int(os.environ.get("YOUTUBE_ASSET_HEIGHT", "1920")),
    )
    service = YouTubeChannelService(transport=HttpYouTubeTransport())
    confirmation = service.prepare(plan)["confirmation_checksum"]
    evidence = service.publish(plan, confirmation=confirmation, access_token=os.environ["YOUTUBE_ACCESS_TOKEN"])
    print("REAL YOUTUBE SHORT UPLOAD SMOKE: PASS")
    print(f"remote video ID: {evidence.remote_video_id}")
    print(f"privacy requested: {evidence.requested_privacy}")
    print(f"privacy observed: {evidence.observed_privacy}")
    print(f"processing status: {evidence.processing_status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
