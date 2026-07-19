from __future__ import annotations

from src.core.browser import BrowserTarget

LOGIN_URL_TOKENS = ("/login", "/checkpoint", "/signup")
POST_BUTTON_PATTERNS = [
    r"^Start a post$",
    r"^Start a post, try writing with AI$",
    r"^Bijdrage starten$",
    r"^Posten$",
    r"^Write article$",
    r"^Write an article$",
    r"^Artikel schrijven$",
    r"^Schrijf een artikel$",
    r"^Write.*article$",
]


def post_button_targets() -> list[BrowserTarget]:
    return [BrowserTarget(role="button", accessible_name=pattern) for pattern in POST_BUTTON_PATTERNS]


AUTHENTICATED_TARGETS = [
    BrowserTarget(css="nav.global-nav"),
    BrowserTarget(css="a[href*='/feed/']"),
    BrowserTarget(css="button[aria-label*='Start a post']"),
    BrowserTarget(css="div.share-box-feed-entry__top-bar"),
]
