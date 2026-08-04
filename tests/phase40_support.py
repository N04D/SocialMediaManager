from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from channels.youtube.channel import YouTubeChannelService
from channels.youtube.models import YouTubePublishPlan
from channels.youtube.transport import FakeYouTubeTransport


def make_plan(tmp: tempfile.TemporaryDirectory, **changes) -> YouTubePublishPlan:
    path = Path(tmp) / "short.mp4"
    path.write_bytes(b"synthetic managed mp4 bytes")
    values = {
        "execution_id": "exec-40",
        "asset_id": "asset-short-1",
        "asset_path": str(path),
        "asset_checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
        "title": "Why Sabr matters",
        "description": "A complete thought from the short.",
        "privacy": "private",
        "notify_subscribers": False,
        "channel_account_id": "youtube:creator",
        "channel_id": "channel-test",
        "variant_id": "variant-1",
        "revision_id": "revision-1",
        "duration": 42.0,
        "width": 1080,
        "height": 1920,
    }
    values.update(changes)
    return YouTubePublishPlan(**values)


def service(transport=None):
    return YouTubeChannelService(transport=transport or FakeYouTubeTransport())
