"""Fake channel and analytics accounts for deterministic demo mode."""

FAKE_ACCOUNTS = {
    "channel.markdown_website": {
        "id": "demo-markdown-website-account",
        "configured": True,
        "connected": True,
        "ready": True,
        "status": "ready",
    },
    "analytics.plausible": {
        "id": "demo-plausible-account",
        "configured": True,
        "connected": True,
        "ready": True,
        "status": "ready",
    },
    "channel.mastodon": {
        "id": "demo-mastodon-account",
        "configured": True,
        "connected": True,
        "ready": True,
        "status": "ready",
        "test_post_created": False,
    },
    "channel.linkedin": {
        "id": "demo-linkedin-account",
        "configured": True,
        "connected": True,
        "ready": True,
        "status": "ready",
        "test_post_created": False,
    },
}
