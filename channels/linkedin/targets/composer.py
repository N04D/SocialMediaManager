from __future__ import annotations

from src.core.browser import BrowserTarget

OPEN_COMPOSER_TARGETS = [
    BrowserTarget(role="button", accessible_name="Start a post"),
    BrowserTarget(role="button", accessible_name="Bijdrage starten"),
    BrowserTarget(css="button:has-text('Start a post')"),
    BrowserTarget(css="button:has-text('Bijdrage starten')"),
    BrowserTarget(css="button[aria-label*='Start a post']"),
    BrowserTarget(css="button[aria-label*='Bijdrage starten']"),
    BrowserTarget(css=".share-box-feed-entry__top-bar button"),
]

COMPOSER_EDITOR = BrowserTarget(
    css="div[role='dialog'] [contenteditable='true']:visible, div[role='dialog'] [role='textbox']:visible, [contenteditable='true']:visible",
)

MEDIA_INPUT = BrowserTarget(css="div[role='dialog'] input[type='file'], input[type='file']")

FINAL_POST_TARGETS = [
    BrowserTarget(role="button", accessible_name="Post", index=0),
    BrowserTarget(role="button", accessible_name="Plaatsen", index=0),
    BrowserTarget(css="div[role='dialog'] button:has-text('Post')", index=0),
    BrowserTarget(css="div[role='dialog'] button:has-text('Plaatsen')", index=0),
]

COOKIE_ACCEPT_TARGETS = [
    BrowserTarget(role="button", accessible_name="Accept"),
    BrowserTarget(css="button:has-text('Accept')"),
    BrowserTarget(css="button[action-type='ACCEPT']"),
]

CONFIRMATION_TARGETS = [
    BrowserTarget(text="post was created"),
    BrowserTarget(text="post is now live"),
    BrowserTarget(text="shared with your network"),
    BrowserTarget(text="uw bericht is gepubliceerd"),
]
