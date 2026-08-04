import unittest

from channels.youtube.channel import YouTubeChannelService
from channels.youtube.transport import FakeYouTubeTransport


class YouTubeConnectionTests(unittest.TestCase):
    def test_connection_uses_official_channel_identity(self):
        service = YouTubeChannelService(transport=FakeYouTubeTransport())
        service.config = type(
            "Config",
            (),
            {
                "youtube_client_id": "client",
                "youtube_client_secret_ref": "secretref:youtube/client",
                "youtube_redirect_uri": "https://app.test/callback",
            },
        )()
        service.secret_reader = lambda _ref: "managed-client-secret"
        start = service.start_connect(
            workspace_id="w", channel_account_id="youtube:creator", redirect_uri="https://app.test/callback"
        )
        result = service.complete_connect(
            code="code",
            state=start["state"],
            workspace_id="w",
            channel_account_id="youtube:creator",
            redirect_uri="https://app.test/callback",
        )
        self.assertEqual(result["channel_id"], "channel-test")
        self.assertEqual(service.connection_status("youtube:creator")["status"], "connected")
