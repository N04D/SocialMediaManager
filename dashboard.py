from __future__ import annotations

import argparse
import cgi
import html
import json
import mimetypes
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from channel_actions import (
    ChannelActionError,
    approve_derivative,
    create_publish_job_from_derivative,
    generate_derivative_for_document,
    manual_attach_published_url,
    queue_manual_metric_refresh,
    reject_derivative,
    return_derivative_to_draft,
    save_derivative_edit,
    send_derivative_for_review,
)
from channel_dashboard import (
    render_channel_cards,
    render_channel_checkbox_grid,
    render_derivatives_panel,
    render_document_performance_panel,
)
from channel_registry import scan_channel_registry
from channel_store import (
    CHANNEL_SCREENSHOTS_DIR,
    PROFILE_ARCHIVE_DIR,
    begin_channel_connect,
    ensure_channel_connection,
    ensure_channel_store_dirs,
    get_channel_connection,
    get_derivative,
    list_channel_job_logs,
    now_iso,
    save_channel_connection,
)
from content_store import (
    SUBSTACK_IMPORTS_DIRNAME,
    build_content_item_from_form,
    content_paths_for_slug,
    create_revision_snapshot,
    delete_content_item,
    ensure_studio_dirs,
    export_html,
    export_markdown,
    get_content_item,
    list_content_revisions,
    load_content_revision,
    list_content_items,
    list_publications,
    list_stats_snapshots,
    plain_text_from_markdown,
    render_markdown_html,
    save_content_item,
    slugify,
)
from pipeline import CONFIG_PATH, AppConfig, Article, build_prompt, ensure_runtime_dirs, fetch_article, load_config, run_local_ai
from timing import compute_article_schedule_time
from scheduler import append_schedule, build_schedule_record, cache_preview, ensure_outbox_dir, get_schedule_record, load_launch_status, load_preview, load_schedule, load_worker_runs, queue_summary, reset_failed_schedule_records, save_launch_status, update_schedule_record, worker_run_summary
from studio_models import ContentItem


ROOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT_DIR / "assets"
ROUTE_EDITOR = "/editor"
ROUTE_DRAFTS = "/drafts"
ROUTE_LINKEDIN = "/linkedin"
ROUTE_STATS = "/stats"
ROUTE_SCHEDULER = "/scheduler"
ROUTE_INSTAGRAM = "/instagram"
ROUTE_CONFIG = "/config"
VALID_ROUTES = {
    ROUTE_EDITOR,
    ROUTE_DRAFTS,
    ROUTE_LINKEDIN,
    ROUTE_STATS,
    ROUTE_SCHEDULER,
    ROUTE_INSTAGRAM,
    ROUTE_CONFIG,
}

SIDEBAR_ITEMS = [
    (ROUTE_EDITOR, "editor", "Editor", "ED"),
    (ROUTE_DRAFTS, "drafts", "Drafts", "DR"),
    (ROUTE_LINKEDIN, "linkedin", "LinkedIn", "LI"),
    (ROUTE_INSTAGRAM, "instagram", "Instagram", "IG"),
    (ROUTE_SCHEDULER, "scheduler", "Scheduler", "SC"),
    (ROUTE_STATS, "stats", "Stats", "ST"),
    (ROUTE_CONFIG, "config", "Config", "CF"),
]

EDITOR_TOOLBAR_BUTTONS = [
    ("bold", "Bold", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5h5.2c2.6 0 4.3 1.4 4.3 3.7 0 1.5-.8 2.7-2.2 3.2 1.8.4 3 1.8 3 3.8 0 2.6-1.9 4.3-5 4.3H8V5zm3 2.4v3.4h2.1c1 0 1.6-.6 1.6-1.7S14.1 7.4 13 7.4H11zm0 5.7v4h2.6c1.2 0 1.9-.7 1.9-1.9s-.7-2-1.9-2H11z"/></svg>'),
    ("italic", "Italic", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 5v2h2.2l-3.4 10H6v2h8v-2h-2.2l3.4-10H18V5z"/></svg>'),
    ("underline", "Underline", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4v7a5 5 0 0 0 10 0V4h-2v7a3 3 0 0 1-6 0V4H7zm-1 15h12v2H6z"/></svg>'),
    ("h2", "Heading 2", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h2v5h5V6h2v12h-2v-5H6v5H4zM17 9.5c0-1.4 1.1-2.5 2.5-2.5S22 8.1 22 9.5c0 1-.5 1.8-1.3 2.4l-1.9 1.4h3.2V15h-6v-1.3l3.3-2.6c.5-.4.7-.8.7-1.3 0-.6-.4-1-.9-1s-.9.4-.9 1V10h-1.8v-.5z"/></svg>'),
    ("h3", "Heading 3", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h2v5h5V6h2v12h-2v-5H6v5H4zM18.4 10.2H17V8.7h4.7v1.1l-1.8 1.7c1 .2 1.7 1 1.7 2.1 0 1.5-1.2 2.5-3 2.5-1.9 0-3-.9-3.1-2.5h1.7c.1.6.5 1 1.3 1 .7 0 1.2-.4 1.2-1.1 0-.7-.5-1.1-1.3-1.1h-.9v-1.3z"/></svg>'),
    ("bulletList", "Bullet list", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6h11v2H9zm0 5h11v2H9zm0 5h11v2H9zM5 7a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zm0 5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zm0 5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0z"/></svg>'),
    ("orderedList", "Ordered list", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 6h10v2H10zm0 5h10v2H10zm0 5h10v2H10zM4 5h1v5H3V8h1zm-1 8h2.2c.4 0 .8.4.8.8 0 .2-.1.4-.3.6L4 16h2v2H2.4v-1.2l2-1.9H3v-2z"/></svg>'),
    ("blockquote", "Blockquote", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 6h5v5H9.6c0 1.7 1 3 2.7 3.8L11 17c-2.7-1-4-3.1-4-6.3V6zm8 0h5v5h-2.4c0 1.7 1 3 2.7 3.8L19 17c-2.7-1-4-3.1-4-6.3V6z"/></svg>'),
    ("codeBlock", "Code block", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8.5 16.5-4.5-4.5 4.5-4.5 1.4 1.4L6.8 12l3.1 3.1zm7 0-1.4-1.4 3.1-3.1-3.1-3.1 1.4-1.4 4.5 4.5zm-4.6 2.1-1.9-.5 4-14 1.9.5z"/></svg>'),
    ("horizontalRule", "Horizontal rule", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11h16v2H4z"/></svg>'),
    ("link", "Link", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.6 13.4a1 1 0 0 0 1.4 1.4l4.2-4.2a3 3 0 0 0-4.2-4.2L9.8 8.6a1 1 0 1 0 1.4 1.4l2.2-2.2a1 1 0 1 1 1.4 1.4zm2.8-2.8a1 1 0 0 0-1.4-1.4L7.8 13.4a3 3 0 1 0 4.2 4.2l2.2-2.2a1 1 0 0 0-1.4-1.4l-2.2 2.2a1 1 0 0 1-1.4-1.4z"/></svg>'),
    ("image-upload", "Upload image", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm0 2v8.2l3.3-3.3a1 1 0 0 1 1.4 0l2 2L15.8 10a1 1 0 0 1 1.4 0L19 11.8V7H5zm14 10v-2.4l-2.5-2.5-4.1 4.1-3-3L5 17h14zM9 8.5A1.5 1.5 0 1 1 6 8.5a1.5 1.5 0 0 1 3 0z"/></svg>'),
]

EDITOR_ACTION_BUTTONS = [
    ("editor-toggle-preview", "Preview mode", "secondary", "button", "", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5c5.5 0 9.3 4.2 10.6 6-1.3 1.8-5.1 6-10.6 6S2.7 12.8 1.4 11C2.7 9.2 6.5 5 12 5zm0 2C8.3 7 5.3 9.5 3.8 11 5.3 12.5 8.3 15 12 15s6.7-2.5 8.2-4C18.7 9.5 15.7 7 12 7zm0 1.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z"/></svg>'),
    ("editor-toggle-focus", "Focus mode", "secondary", "button", "", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5v2H6v3H4zm10-5h5v5h-2V6h-3V4zM4 15h2v3h3v2H4v-5zm13 0h2v5h-5v-2h3v-3z"/></svg>'),
    ("editor-export-markdown", "Export Markdown", "secondary", "button", "", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h10l4 4v12H5V4zm9 1.5V9h3.5L14 5.5zM8 12v4H6v-4h2zm1 4 1.6-4h1.6l1.6 4h-1.7l-.2-.7h-1.4l-.2.7H9zm2.1-1.9h.8l-.4-1.3-.4 1.3zm3.1-2.1h1.7l1 1.6 1-1.6h1.7l-1.8 2.8 1.9 3h-1.7l-1.1-1.7-1.1 1.7h-1.7l1.9-3-1.8-2.8z"/></svg>'),
    ("editor-export-html", "Export HTML", "secondary", "button", "", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h10l4 4v12H5V4zm9 1.5V9h3.5L14 5.5zM8.4 15.8 6 13.4l2.4-2.4 1.1 1.1-1.3 1.3 1.3 1.3-1.1 1.1zm3.2 1.2h-1.4l2.2-8h1.4l-2.2 8zm3-1.2-1.1-1.1 1.3-1.3-1.3-1.3 1.1-1.1 2.4 2.4-2.4 2.4z"/></svg>'),
    ("", "Save draft", "", "submit", "", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h11l3 3v13H5V4zm2 2v12h10V8.5L15.5 7H15v3H9V6H7zm4 0v2h2V6h-2zm1 10.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z"/></svg>'),
    ("", "Save and queue", "secondary", "submit", "/editor/schedule", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h12v2H6V5zm0 6h8v2H6v-2zm0 6h8v2H6v-2zm10-5 5 4-5 4v-3h-3v-2h3v-3z"/></svg>'),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local SocialMediaManager dashboard")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to config.json")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=8080, help="Dashboard port")
    return parser.parse_args()


def normalize_route(path: str) -> str:
    if path in {"", "/"}:
        return ROUTE_EDITOR
    cleaned = path.rstrip("/") or "/"
    return cleaned if cleaned in VALID_ROUTES else ROUTE_EDITOR


def sanitize_return_to(value: str | None, default: str = ROUTE_LINKEDIN) -> str:
    if not value:
        return default
    parsed = urlparse(value)
    route = normalize_route(parsed.path)
    if parsed.path not in {"", "/", route} and parsed.path not in VALID_ROUTES:
        return default
    query = f"?{parsed.query}" if parsed.query else ""
    return route + query


def form_value(form: dict[str, list[str]], key: str, default: str = "") -> str:
    return form.get(key, [default])[0]


def form_values(form: dict[str, list[str]], key: str) -> list[str]:
    return [value for value in form.get(key, []) if value]


def parse_checkbox(form: dict[str, list[str]], key: str) -> bool:
    return form_value(form, key, "").strip().lower() in {"true", "1", "yes", "on"}


def config_path_string(path_value: str) -> str:
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (ROOT_DIR / candidate).resolve()
    try:
        relative = candidate.relative_to(ROOT_DIR)
        return f"./{relative.as_posix()}"
    except ValueError:
        return str(candidate)


def public_asset_url(content_dir: Path, asset_path: str) -> str:
    if not asset_path:
        return ""
    raw = asset_path.strip().replace("\\", "/").lstrip("./")
    content_raw = str(content_dir).replace("\\", "/").lstrip("./")
    prefix = f"{content_raw.rstrip('/')}/"
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
    if raw.startswith("content/drafts/"):
        raw = raw[len("content/drafts/"):]
    return f"/content-files/{raw}" if raw else ""


def render_editor_toolbar() -> str:
    format_buttons: list[str] = []
    for action, label, icon in EDITOR_TOOLBAR_BUTTONS:
        format_buttons.append(
            f'<button type="button" data-action="{html.escape(action)}" title="{html.escape(label)}" aria-label="{html.escape(label)}">{icon}<span class="sr-only">{html.escape(label)}</span></button>'
        )
    action_buttons: list[str] = []
    for button_id, label, variant, button_type, form_action, icon in EDITOR_ACTION_BUTTONS:
        classes = "editor-toolbar-action"
        if variant:
            classes += f" {variant}"
        id_attr = f' id="{html.escape(button_id)}"' if button_id else ""
        formaction_attr = f' formaction="{html.escape(form_action)}"' if form_action else ""
        action_buttons.append(
            f'<button class="{classes}" type="{html.escape(button_type)}"{id_attr}{formaction_attr} title="{html.escape(label)}" aria-label="{html.escape(label)}">{icon}<span class="sr-only action-label">{html.escape(label)}</span></button>'
        )
    return (
        f'<div class="editor-toolbar-group">{"".join(format_buttons)}</div>'
        f'<div class="editor-toolbar-group editor-toolbar-group-actions">{"".join(action_buttons)}</div>'
    )


def render_editor_panel_icon(name: str) -> str:
    icons = {
        "metadata": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm0 2v12h14V6H5zm2 2h6v2H7V8zm0 4h10v2H7v-2zm0 4h8v2H7v-2z"/></svg>',
        "channels": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h7v5H4V6zm9 0h7v5h-7V6zM4 13h7v5H4v-5zm9 2h7v1a2 2 0 0 1-2 2h-5v-3zm1-7h5v1h-5V8zM5 15h5v1H5v-1z"/></svg>',
        "media": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm0 2v8.2l3.3-3.3a1 1 0 0 1 1.4 0l2 2L15.8 10a1 1 0 0 1 1.4 0L19 11.8V7H5zm14 10v-2.4l-2.5-2.5-4.1 4.1-3-3L5 17h14zM9 8.5A1.5 1.5 0 1 1 6 8.5a1.5 1.5 0 0 1 3 0z"/></svg>',
        "revisions": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5a7 7 0 1 1-6.4 9.8H3l3.2-3.8L9 14H6.9A5 5 0 1 0 12 7v3l4-4-4-4v3zm-1 4h2v4h-2zm0 5.5h2v2h-2z"/></svg>',
        "ai": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 8.8 8.8 3 12l5.8 3.2L12 21l3.2-5.8L21 12l-5.8-3.2L12 3zm0 4.4 1.8 3.2L17 12l-3.2 1.4L12 16.6l-1.8-3.2L7 12l3.2-1.4L12 7.4zm-.9 2.8h1.8v3.6h-1.8zm0 4.6h1.8v1.8h-1.8z"/></svg>',
    }
    return icons.get(name, "")


def build_snapshot(config: AppConfig) -> dict[str, Any]:
    article = fetch_article(config.rss_url, config.article_delay_index)
    soup = BeautifulSoup(article.html, "html.parser")
    image_tags = soup.find_all("img")
    image_count = len(image_tags)
    image_sources = [
        str(image.get("src") or image.get("data-src"))
        for image in image_tags
        if image.get("src") or image.get("data-src")
    ]
    return {
        "article": article,
        "image_count": image_count,
        "image_sources": image_sources,
    }


def next_friday_afternoon() -> str:
    now = datetime.now()
    days_ahead = (4 - now.weekday()) % 7
    target = (now + timedelta(days=days_ahead)).replace(hour=15, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=7)
    return target.isoformat(timespec="minutes")


def default_schedule_time(content_type: str, article: Article, config: AppConfig) -> str:
    if content_type == "article":
        publish_time = compute_article_schedule_time(
            config.linkedin_article_schedule_buffer_minutes,
            now=datetime.now().astimezone(),
        )
        return publish_time.isoformat(timespec="minutes")
    return next_friday_afternoon()


def article_from_content_item(item: ContentItem) -> Article:
    title = item.title or "Untitled"
    body = item.markdown_body or ""
    slug = item.slug or slugify(title)
    link = f"local://content/{slug}"
    html_body = render_markdown_html(body)
    text_body = plain_text_from_markdown(body)
    published_at = item.published_at or None
    return Article(title=title, link=link, html=html_body, text=text_body, published_at=published_at)


def teaser_from_markdown(markdown_body: str, max_words: int = 40) -> str:
    text = plain_text_from_markdown(markdown_body)
    if not text:
        return "Draft queued from the local content studio."
    words = text.split()
    excerpt = " ".join(words[:max_words]).strip()
    if len(words) > max_words:
        excerpt += " ..."
    return excerpt


def content_item_has_changes(existing: ContentItem, updated: ContentItem) -> bool:
    fields = (
        "title",
        "subtitle",
        "slug",
        "status",
        "channels",
        "tags",
        "categories",
        "markdown_body",
        "html_body",
        "editor_json",
        "published_at",
        "cover_image_path",
        "linkedin_post_urn",
        "instagram_media_id",
        "substack_post_id",
        "x_post_id",
    )
    return any(getattr(existing, field) != getattr(updated, field) for field in fields)


def maybe_snapshot_revision(content_dir: Path, existing: ContentItem | None, updated: ContentItem, reason: str) -> None:
    if existing and content_item_has_changes(existing, updated):
        create_revision_snapshot(content_dir, existing, reason=reason)


def clean_ai_markdown_response(output: str) -> str:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def build_editor_ai_prompt(title: str, subtitle: str, markdown_body: str, user_prompt: str) -> str:
    return (
        "You are editing a longform draft.\n"
        "Apply the instruction carefully while preserving the author's tone and structure unless the instruction says otherwise.\n"
        "Return only the revised Markdown body.\n"
        "Do not include explanations.\n"
        "Do not include code fences.\n"
        "Do not include TITLE: or BODY: labels.\n\n"
        f"Instruction:\n{user_prompt.strip()}\n\n"
        f"Title:\n{title.strip() or 'Untitled'}\n\n"
        f"Subtitle:\n{subtitle.strip()}\n\n"
        f"Current Markdown body:\n{markdown_body.strip()}\n"
    )


def render_revision_reason(reason: str) -> str:
    return reason.replace("-", " ").replace("_", " ").strip().capitalize() or "Saved revision"


def filter_queue(records: list[dict[str, Any]], status: str | None) -> list[dict[str, Any]]:
    if not status or status == "all":
        return records
    return [record for record in records if str(record.get("status", "")) == status]


def append_queue(record: dict[str, Any]) -> None:
    append_schedule(record)


def build_editor_item_from_request(form: dict[str, list[str]], existing: ContentItem | None = None, *, forced_status: str | None = None, fallback_channels: list[str] | None = None) -> ContentItem:
    channels = form_values(form, "channels")
    if not channels and fallback_channels:
        channels = fallback_channels
    return build_content_item_from_form(
        {
            "title": form_value(form, "title"),
            "subtitle": form_value(form, "subtitle"),
            "slug": form_value(form, "slug"),
            "status": forced_status or form_value(form, "status", "draft"),
            "channels": channels,
            "tags": form_value(form, "tags"),
            "categories": form_value(form, "categories"),
            "published_at": form_value(form, "published_at"),
            "editor_json": form_value(form, "editor_json"),
            "markdown_body": form_value(form, "markdown_body"),
            "html_body": form_value(form, "html_body"),
            "cover_image_path": form_value(form, "cover_image_path"),
        },
        existing=existing,
    )


def save_config_value(config_path: str, updates: dict[str, Any]) -> None:
    path = Path(config_path)
    raw: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            raw = loaded
    raw.update(updates)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(raw, handle, indent=2)
        handle.write("\n")


def render_sidebar_icon(name: str, fallback: str) -> str:
    icons = {
        "editor": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 4h10l4 4v12H5z"></path>
              <path d="M15 4v4h4"></path>
              <path d="M8 12h8M8 16h8"></path>
            </svg>
        """,
        "linkedin": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="4" y="9" width="4" height="11" rx="1.5"></rect>
              <circle cx="6" cy="5.5" r="2"></circle>
              <path d="M12 9h3v1.8c.8-1.1 2-2 4-2 3 0 5 1.9 5 5.7V20h-4v-4.8c0-1.8-.7-2.9-2.3-2.9-1.5 0-2.3 1-2.7 1.9V20h-4z"></path>
            </svg>
        """,
        "workarounds": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6 6h12v4H6z"></path>
              <path d="M9 10h6v8H9z"></path>
              <path d="M4 18h16v2H4z"></path>
            </svg>
        """,
        "sergio": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 3l7 4v5c0 4.2-2.6 7.9-7 9-4.4-1.1-7-4.8-7-9V7z"></path>
              <path d="M9.5 12.2l1.8 1.8 3.4-3.8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
            </svg>
        """,
        "scheduler": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="3" y="5" width="18" height="16" rx="2"></rect>
              <path d="M3 10h18"></path>
              <path d="M8 3v4M16 3v4"></path>
              <circle cx="12" cy="15" r="3"></circle>
            </svg>
        """,
        "stats": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 19V9"></path>
              <path d="M12 19V5"></path>
              <path d="M19 19v-7"></path>
              <path d="M3 19h18"></path>
            </svg>
        """,
        "instagram": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="4" y="4" width="16" height="16" rx="4"></rect>
              <circle cx="12" cy="12" r="3.5"></circle>
              <circle cx="17.2" cy="6.8" r="1.2"></circle>
            </svg>
        """,
        "config": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="3.2"></circle>
              <path d="M12 2.8l1.5 2.4 2.8.4.5 2.8 2.4 1.5-1 2.7 1 2.7-2.4 1.5-.5 2.8-2.8.4L12 21.2l-1.5-2.4-2.8-.4-.5-2.8-2.4-1.5 1-2.7-1-2.7 2.4-1.5.5-2.8 2.8-.4z"></path>
            </svg>
        """,
    }
    svg = icons.get(name)
    if svg:
        return svg
    return f"<span class=\"sidebar-fallback\">{html.escape(fallback)}</span>"


def queue_item_url(record_id: str, route: str) -> str:
    return f"{route}?detail={html.escape(record_id)}"


def status_filter_url(route: str, status: str | None, detail_id: str | None = None) -> str:
    params: list[str] = []
    if status and status != "all":
        params.append(f"status={status}")
    if detail_id:
        params.append(f"detail={detail_id}")
    return route + (("?" + "&".join(params)) if params else "")


def launch_draft_process(config_path: str) -> None:
    log_path = ROOT_DIR / "outbox" / "article_launch.log"
    save_launch_status(
        {
            "action": "article_draft",
            "state": "starting",
            "message": "Launching article draft flow.",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "log_path": str(log_path),
        }
    )
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] Starting article draft flow\n")
        log_file.flush()
        process = subprocess.Popen(
            [sys.executable, str(ROOT_DIR / "pipeline.py"), "--config", config_path, "--save-draft"],
            cwd=str(ROOT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        save_launch_status(
            {
                "action": "article_draft",
                "state": "running",
                "message": "Article draft flow is running.",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "pid": process.pid,
                "log_path": str(log_path),
            }
        )
        return_code = process.wait()
        state = "done" if return_code == 0 else "failed"
        save_launch_status(
            {
                "action": "article_draft",
                "state": state,
                "message": f"Article draft flow exited with code {return_code}.",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "pid": process.pid,
                "return_code": return_code,
                "log_path": str(log_path),
            }
        )


def open_article_editor_process(config_path: str) -> None:
    log_path = ROOT_DIR / "outbox" / "article_editor_open.log"
    save_launch_status(
        {
            "action": "article_draft",
            "state": "starting",
            "message": "Opening and filling LinkedIn article draft.",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "log_path": str(log_path),
        }
    )
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] Opening and filling LinkedIn article draft\n")
        log_file.flush()
        process = subprocess.Popen(
            [sys.executable, str(ROOT_DIR / "pipeline.py"), "--config", config_path, "--save-draft"],
            cwd=str(ROOT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        save_launch_status(
            {
                "action": "article_draft",
                "state": "running",
                "message": "LinkedIn article draft is opening.",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "pid": process.pid,
                "log_path": str(log_path),
            }
        )
        return_code = process.wait()
        state = "done" if return_code == 0 else "failed"
        save_launch_status(
            {
                "action": "article_draft",
                "state": state,
                "message": f"LinkedIn article draft exited with code {return_code}.",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "pid": process.pid,
                "return_code": return_code,
                "log_path": str(log_path),
            }
        )


def spawn_worker_process(config_path: str, *worker_args: str, log_name: str = "channel-worker.log") -> int:
    log_path = ROOT_DIR / "outbox" / log_name
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(
            f"\n[{datetime.now().isoformat(timespec='seconds')}] Starting worker: {' '.join(worker_args)}\n"
        )
        log_file.flush()
        process = subprocess.Popen(
            [sys.executable, str(ROOT_DIR / "worker.py"), "--config", config_path, *worker_args],
            cwd=str(ROOT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return process.pid


def render_placeholder_card(title: str, message: str) -> str:
    return f"""
    <section class=\"card\">
      <h2>{html.escape(title)}</h2>
      <p class=\"meta\">{html.escape(message)}</p>
    </section>
    """


def escape_js_template(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("${", "\\${")
        .replace("</", "<\\/")
    )


def make_empty_content_item() -> ContentItem:
    return ContentItem(
        id="",
        title="",
        subtitle="",
        slug="",
        status="draft",
        channels=[],
        tags=[],
        categories=[],
        editor_json={},
        markdown_body="",
        html_body="",
        cover_image_path="",
        created_at="",
        updated_at="",
        published_at="",
    )

def render_editor_list(items: list[ContentItem], active_identifier: str | None) -> str:
    rows: list[str] = []
    for item in items[:16]:
        active = " active" if active_identifier in {item.id, item.slug} else ""
        updated = item.updated_at or item.created_at or "Unknown time"
        open_href = f"{ROUTE_EDITOR}?content={html.escape(item.id)}"
        rows.append(
            f'<div class="content-link{active}">'
            f'  <a class="content-link-main" href="{open_href}">'
            f"    <strong>{html.escape(item.title)}</strong>"
            f"    <span>{html.escape(item.status.title())} · {html.escape(item.slug)}</span>"
            f"    <span>{html.escape(updated)}</span>"
            f"  </a>"
            f'  <details class="content-link-menu">'
            f'    <summary aria-label="Draft actions" title="Draft actions">...</summary>'
            f'    <div class="content-link-menu-items">'
            f'      <form method="post" action="/drafts/post"><input type="hidden" name="content_id" value="{html.escape(item.id)}" /><input type="hidden" name="return_to" value="{ROUTE_DRAFTS}" /><button type="submit">Post now</button></form>'
            f'      <form method="post" action="/drafts/schedule"><input type="hidden" name="content_id" value="{html.escape(item.id)}" /><input type="hidden" name="return_to" value="{ROUTE_DRAFTS}" /><button type="submit">Schedule</button></form>'
            f'      <form method="post" action="/drafts/delete"><input type="hidden" name="content_id" value="{html.escape(item.id)}" /><input type="hidden" name="return_to" value="{ROUTE_DRAFTS}" /><button type="submit" class="danger">Delete</button></form>'
            f"    </div>"
            f"  </details>"
            f"</div>"
        )
    if not rows:
        rows.append("<p class=\"meta\">No local drafts yet. Create your first content item here.</p>")
    return "".join(rows)


def render_drafts_page(config: AppConfig, content_items: list[ContentItem], selected_item: ContentItem) -> str:
    content_identifier = selected_item.id or selected_item.slug
    detail_panel = ""
    if selected_item.id:
        selected_title = selected_item.title or "Untitled"
        selected_status = selected_item.status.title() if selected_item.status else "Draft"
        selected_updated = selected_item.updated_at or selected_item.created_at or "Unknown time"
        selected_channels = ", ".join(selected_item.channels) or "No channels selected"
        open_link = f"{ROUTE_EDITOR}?content={html.escape(selected_item.id)}"
        detail_panel = f"""
        <section class=\"card\">
          <h2>{html.escape(selected_title)}</h2>
          <p class=\"meta\">{html.escape(selected_status)} · {html.escape(selected_updated)}</p>
          <p class=\"meta\">Channels: <code>{html.escape(selected_channels)}</code></p>
          <div class=\"actions\">
            <a class=\"button\" href=\"{open_link}\">Open in editor</a>
          </div>
        </section>
        """
    return f"""
      <div class=\"stack\">
        <section class=\"card\">
          <div class=\"card-heading\">
            <div>
              <h2>Drafts</h2>
            </div>
          </div>
          <div class=\"content-list\">{render_editor_list(content_items, content_identifier)}</div>
        </section>
        {detail_panel}
      </div>
    """


def render_editor_page(config: AppConfig, content_items: list[ContentItem], selected_item: ContentItem) -> str:
    selected_channels = set(selected_item.channels)
    editor_html_seed = selected_item.html_body or ""
    preview_html = editor_html_seed or render_markdown_html(selected_item.markdown_body)
    last_saved = selected_item.updated_at or "Not saved yet"
    editor_json_seed = json.dumps(selected_item.editor_json or {}, ensure_ascii=False)
    cover_preview_url = public_asset_url(config.content_dir, selected_item.cover_image_path)
    revisions = list_content_revisions(config.content_dir, selected_item.id or selected_item.slug, limit=10) if selected_item.id or selected_item.slug else []
    cover_preview_markup = (
        f'<img src="{html.escape(cover_preview_url)}" alt="Cover preview" class="cover-preview-image" />'
        if cover_preview_url
        else '<div class="cover-preview-empty">No cover selected yet.</div>'
    )
    revision_items = "".join(
        f"""
        <li class="revision-item">
          <div class="revision-copy">
            <strong>{html.escape(str(revision.get('saved_at') or revision.get('id') or 'Unknown revision'))}</strong>
            <span class="meta">{html.escape(render_revision_reason(str(revision.get('reason') or 'manual')))}</span>
          </div>
          <form method="post" action="/editor/restore-revision" class="revision-form">
            <input type="hidden" name="return_to" value="{html.escape(f'{ROUTE_EDITOR}?content={selected_item.id or selected_item.slug}')}" />
            <input type="hidden" name="content_id" value="{html.escape(selected_item.id or selected_item.slug)}" />
            <input type="hidden" name="revision_id" value="{html.escape(str(revision.get('id') or ''))}" />
            <button type="submit" class="editor-panel-button subtle">Restore</button>
          </form>
        </li>
        """
        for revision in revisions
    ) or '<li class="revision-empty meta">No revisions yet. They start appearing after edits and restores.</li>'
    return f"""
      <div class=\"editor-main\">
        <section class=\"card\">
            <form method=\"post\" action=\"/editor/save\" id=\"studio-editor-form\">
              <input type=\"hidden\" name=\"return_to\" value=\"{html.escape(ROUTE_EDITOR)}\" />
              <input type=\"hidden\" name=\"content_id\" value=\"{html.escape(selected_item.id)}\" />
              <input type=\"hidden\" name=\"previous_slug\" value=\"{html.escape(selected_item.slug)}\" />
              <input type=\"hidden\" name=\"editor_json\" id=\"editor-json-input\" value=\"{html.escape(editor_json_seed)}\" />
              <input type=\"hidden\" name=\"markdown_body\" id=\"editor-markdown-input\" value=\"{html.escape(selected_item.markdown_body)}\" />
              <input type=\"hidden\" name=\"html_body\" id=\"editor-html-input\" value=\"{html.escape(editor_html_seed)}\" />
              <input type=\"hidden\" name=\"cover_image_path\" id=\"editor-cover-image-input\" value=\"{html.escape(selected_item.cover_image_path)}\" />
              <input type=\"file\" id=\"editor-image-upload\" accept=\"image/*\" hidden />

              <div class=\"writer-shell\">
                <div class=\"writer-layout\">
                  <div class=\"writer-compose\">
                    <div class=\"editor-workbench\">
                      <div class=\"editor-column\">
                        <div class=\"editor-toolbar\" id=\"editor-toolbar\">{render_editor_toolbar()}</div>
                        <div class=\"editor-writing-surface\">
                          <div class=\"editor-primary-fields editor-primary-fields-inline\">
                            <input id=\"editor-title\" class=\"editor-title-input\" name=\"title\" value=\"{html.escape(selected_item.title)}\" placeholder=\"Title\" />
                            <textarea id=\"editor-subtitle\" class=\"editor-subtitle-input\" name=\"subtitle\" placeholder=\"Subtitle or dek\">{html.escape(selected_item.subtitle)}</textarea>
                          </div>
                          <div class=\"editor-drop-hint\" id=\"editor-drop-hint\">Drop images here to add them to the draft</div>
                          <div id=\"tiptap-editor\" class=\"tiptap-editor\"></div>
                        </div>
                        <div class=\"editor-status-bar\">
                          <span id=\"editor-last-saved\">Last saved: <code>{html.escape(last_saved)}</code></span>
                          <span id=\"editor-autosave-state\" class=\"meta\">Autosave idle</span>
                        </div>
                      </div>
                      <div class=\"preview-column\" id=\"editor-preview-column\">
                        <div class=\"preview-header\">
                          <div>
                            <h3>Preview</h3>
                            <p class=\"meta\">Clean reading preview with exported HTML.</p>
                          </div>
                          <button class=\"editor-preview-back\" id=\"editor-preview-back\" type=\"button\" aria-label=\"Back to editor\" title=\"Back to editor\">
                            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14.7 6.3-1.4-1.4L6.2 12l7.1 7.1 1.4-1.4L10 13h7.8v-2H10z"/></svg>
                            <span class=\"sr-only\">Back to editor</span>
                          </button>
                        </div>
                        <div id=\"editor-preview\" class=\"markdown-preview\">{preview_html}</div>
                        <section class=\"card preview-meta-card\">
                          <h3>Frontmatter Preview</h3>
                          <pre id=\"frontmatter-preview\" class=\"frontmatter-preview\">---\ntitle: {html.escape(selected_item.title)}\nsubtitle: {html.escape(selected_item.subtitle)}\nstatus: {html.escape(selected_item.status)}\nchannels: [{html.escape(', '.join(selected_item.channels))}]\ntags: [{html.escape(', '.join(selected_item.tags))}]\ncreated_at: {html.escape(selected_item.created_at)}\nupdated_at: {html.escape(selected_item.updated_at)}\npublished_at: {html.escape(selected_item.published_at)}\nlinkedin_post_urn: {html.escape(selected_item.linkedin_post_urn)}\ninstagram_media_id: {html.escape(selected_item.instagram_media_id)}\nsubstack_post_id: {html.escape(selected_item.substack_post_id)}\nx_post_id: {html.escape(selected_item.x_post_id)}\n---</pre>
                        </section>
                      </div>
                    </div>
                  </div>

                  <aside class=\"editor-rail\">
                    <div class=\"editor-rail-sticky\">
                      <details class=\"editor-panel\">
                        <summary class=\"editor-panel-summary\">
                          <span class=\"editor-panel-summary-left\"><span class=\"editor-panel-icon\">{render_editor_panel_icon('metadata')}</span><span>Metadata</span></span>
                          <span class=\"editor-panel-chevron\" aria-hidden=\"true\"></span>
                        </summary>
                        <div class=\"editor-panel-body editor-side-fields\">
                          <label for=\"editor-slug\">Slug</label>
                          <input id=\"editor-slug\" name=\"slug\" value=\"{html.escape(selected_item.slug)}\" placeholder=\"auto-generated-from-title\" />
                          <label for=\"editor-status\">Status</label>
                          <select id=\"editor-status\" name=\"status\">
                            <option value=\"draft\" {'selected' if selected_item.status == 'draft' else ''}>Draft</option>
                            <option value=\"scheduled\" {'selected' if selected_item.status == 'scheduled' else ''}>Scheduled</option>
                          </select>
                          <label for=\"editor-tags\">Tags</label>
                          <input id=\"editor-tags\" name=\"tags\" value=\"{html.escape(', '.join(selected_item.tags))}\" placeholder=\"essay, theology, psychology\" />
                          <label for=\"editor-categories\">Categories</label>
                          <input id=\"editor-categories\" name=\"categories\" value=\"{html.escape(', '.join(selected_item.categories))}\" placeholder=\"LinkedIn, Longform\" />
                          <label for=\"editor-published-at\">Published at</label>
                          <input id=\"editor-published-at\" name=\"published_at\" value=\"{html.escape(selected_item.published_at)}\" placeholder=\"2026-06-09T15:00:00+02:00\" />
                        </div>
                      </details>

                      <details class=\"editor-panel\">
                        <summary class=\"editor-panel-summary\">
                          <span class=\"editor-panel-summary-left\"><span class=\"editor-panel-icon\">{render_editor_panel_icon('channels')}</span><span>Channels</span></span>
                          <span class=\"editor-panel-chevron\" aria-hidden=\"true\"></span>
                        </summary>
                        <div class=\"editor-panel-body\">
                          <div class=\"checkbox-grid checkbox-grid-rail\">{render_channel_checkbox_grid(selected_channels)}</div>
                        </div>
                      </details>

                      <details class=\"editor-panel\">
                        <summary class=\"editor-panel-summary\">
                          <span class=\"editor-panel-summary-left\"><span class=\"editor-panel-icon\">{render_editor_panel_icon('media')}</span><span>Media</span></span>
                          <span class=\"editor-panel-chevron\" aria-hidden=\"true\"></span>
                        </summary>
                        <div class=\"editor-panel-body\">
                          <p class=\"meta\">The first image you upload becomes the cover automatically.</p>
                          <div id=\"editor-cover-preview\" class=\"cover-preview\">{cover_preview_markup}</div>
                          <label for=\"editor-cover-image-path\">Cover image path</label>
                          <input id=\"editor-cover-image-path\" value=\"{html.escape(selected_item.cover_image_path)}\" placeholder=\"Auto-filled from first uploaded image\" readonly />
                        </div>
                      </details>

                      <details class=\"editor-panel\">
                        <summary class=\"editor-panel-summary\">
                          <span class=\"editor-panel-summary-left\"><span class=\"editor-panel-icon\">{render_editor_panel_icon('revisions')}</span><span>Revisions</span></span>
                          <span class=\"editor-panel-chevron\" aria-hidden=\"true\"></span>
                        </summary>
                        <div class=\"editor-panel-body\">
                          <ul class=\"revision-list\">{revision_items}</ul>
                        </div>
                      </details>

                      <details class=\"editor-panel\">
                        <summary class=\"editor-panel-summary\">
                          <span class=\"editor-panel-summary-left\"><span class=\"editor-panel-icon\">{render_editor_panel_icon('ai')}</span><span>AI prompt</span></span>
                          <span class=\"editor-panel-chevron\" aria-hidden=\"true\"></span>
                        </summary>
                        <div class=\"editor-panel-body\">
                          <p class=\"meta\">Give one concrete editing instruction. AI edits the body text and leaves title/subtitle alone.</p>
                          <label for=\"editor-ai-prompt\">Edit instruction</label>
                          <textarea id=\"editor-ai-prompt\" class=\"editor-ai-prompt\" placeholder=\"For example: tighten this piece, keep my tone, and make the ending more decisive.\"></textarea>
                          <button id=\"editor-ai-apply\" type=\"button\" class=\"editor-panel-button\">Apply AI edit</button>
                          <p id=\"editor-ai-feedback\" class=\"meta editor-ai-feedback\">The updated text is written back into the editor so you can keep editing.</p>
                        </div>
                      </details>
                    </div>
                  </aside>
                </div>

              </div>
            </form>
        </section>
        {render_document_performance_panel(selected_item)}
        {render_derivatives_panel(selected_item, return_to=f'{ROUTE_EDITOR}?content={selected_item.id or selected_item.slug}')}
      </div>
      <script>
        window.__studioEditorSeed = {json.dumps({
            "id": selected_item.id,
            "title": selected_item.title,
            "subtitle": selected_item.subtitle,
            "slug": selected_item.slug,
            "status": selected_item.status,
            "channels": selected_item.channels,
            "tags": selected_item.tags,
            "categories": selected_item.categories,
            "published_at": selected_item.published_at,
            "markdown_body": selected_item.markdown_body,
            "html_body": editor_html_seed,
            "editor_json": selected_item.editor_json,
            "cover_image_path": selected_item.cover_image_path,
            "created_at": selected_item.created_at,
            "linkedin_post_urn": selected_item.linkedin_post_urn,
            "instagram_media_id": selected_item.instagram_media_id,
            "substack_post_id": selected_item.substack_post_id,
            "x_post_id": selected_item.x_post_id,
            "updated_at": selected_item.updated_at,
        }, ensure_ascii=False)};
      </script>
      <script type=\"module\" src=\"/assets/editor-app.js\"></script>
    """


def render_record_detail(record: dict[str, Any] | None, return_to: str) -> str:
    if not record:
        return """
        <section class="card">
          <h2>Queue Detail</h2>
          <p class="meta">Select an item from the queue to inspect its status and payload.</p>
        </section>
        """

    image_sources = record.get("image_sources", [])
    if not isinstance(image_sources, list):
        image_sources = []

    image_rows = "".join(
        f"<li><a href=\"{html.escape(str(source))}\" target=\"_blank\" rel=\"noreferrer\">{html.escape(str(source))}</a></li>"
        for source in image_sources
    ) or "<li>No image sources stored.</li>"

    result = record.get("result") or "No result yet."
    processed_at = record.get("processed_at") or "Not processed yet."
    content_type = str(record.get("content_type", "post"))
    route = "Article -> Al-Batin Page" if content_type == "article" else "Post -> LinkedIn feed"
    retry_button = ""
    if str(record.get("status", "")) == "failed":
        retry_button = f"""
          <form method="post" action="/retry">
            <input type="hidden" name="id" value="{html.escape(str(record.get('id', '')))}" />
            <input type="hidden" name="return_to" value="{html.escape(return_to)}" />
            <div class="actions">
              <button type="submit">Retry failed item</button>
            </div>
          </form>
        """

    return f"""
        <section class="card">
          <h2>Queue Detail</h2>
          <p><strong>{html.escape(str(record.get('article_title', 'Untitled')))}</strong></p>
          <p class="meta">Platform: <code>{html.escape(str(record.get('platform', '')))}</code></p>
          <p class="meta">Content type: <code>{html.escape(str(record.get('content_type', 'post')))}</code></p>
          <p class="meta">Route: <code>{html.escape(route)}</code></p>
          <p class="meta">Status: <code>{html.escape(str(record.get('status', 'queued')))}</code></p>
          <p class="meta">Scheduled for: <code>{html.escape(str(record.get('scheduled_for', '')))}</code></p>
          <p class="meta">Source published at: <code>{html.escape(str(record.get('source_published_at', '')) or 'Unknown')}</code></p>
          <p class="meta">Created at: <code>{html.escape(str(record.get('created_at', '')))}</code></p>
          <p class="meta">Processed at: <code>{html.escape(str(processed_at))}</code></p>
          <p class="meta">Article link: <a href="{html.escape(str(record.get('article_link', '')))}" target="_blank" rel="noreferrer">{html.escape(str(record.get('article_link', '')))}</a></p>
          <p class="meta">Notes: {html.escape(str(record.get('notes', '')) or 'No notes')}</p>
          <h3>Teaser</h3>
          <div class="teaser">{html.escape(str(record.get('article_teaser', '')))}</div>
          <h3>Media sources</h3>
          <ul>{image_rows}</ul>
          <h3>Result</h3>
          <div class="teaser">{html.escape(str(result))}</div>
          {retry_button}
        </section>
    """


def render_worker_history() -> str:
    records = worker_run_summary(load_worker_runs())
    rows = []
    for record in reversed(records):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(record.get('timestamp', '')))}</td>"
            f"<td>{html.escape(str(record.get('status', '')))}</td>"
            f"<td>{html.escape(str(record.get('message', '')))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='3'>No worker runs yet.</td></tr>")
    return f"""
        <section class="card">
          <h2>Worker Runs</h2>
          <table>
            <thead><tr><th>Time</th><th>Status</th><th>Message</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </section>
    """


def render_launch_status() -> str:
    return """
        <section class="card">
          <h2>Article Launch</h2>
          <div id="launch-status-content">
            <p class="meta">No launch in progress yet.</p>
          </div>
        </section>
    """


def render_browser_session(config: AppConfig, return_to: str) -> str:
    current = config.linkedin_remote_debugging_url or "Local persistent profile"
    timing_summary = f"Schedule +{config.linkedin_article_schedule_buffer_minutes} minute(s)"
    return f"""
        <section class="card">
          <h2>Browser Session</h2>
          <p class="meta">Current mode: <code>{html.escape(current)}</code></p>
          <p class="meta">LinkedIn target: <code>{html.escape(config.linkedin_publish_as_page_name)}</code> · Content mode: <code>{html.escape(config.linkedin_content_mode)}</code></p>
          <p class="meta">Article timing: <code>{html.escape(timing_summary)}</code></p>
          <p class="meta">Cover image: <code>{'enabled' if config.linkedin_article_use_cover_image else 'disabled'}</code></p>
          <p class="meta">Article admin URL: <code>{html.escape(config.linkedin_company_admin_url)}</code></p>
          <p class="meta">Article new URL: <code>{html.escape(config.linkedin_article_new_url)}</code></p>
          <p class="meta">Substack archive: <code>{html.escape(config.substack_archive_url)}</code></p>
          <p class="meta">Use a remote-debugging Chrome session if you want Playwright to attach to your already logged-in browser.</p>
          <form method="post" action="/browser-session">
            <input type="hidden" name="return_to" value="{html.escape(return_to)}" />
            <label for="remote_debugging_url">Remote debugging URL</label>
            <input id="remote_debugging_url" name="remote_debugging_url" value="{html.escape(config.linkedin_remote_debugging_url)}" placeholder="http://127.0.0.1:9222" />
            <div class="actions">
              <button type="submit">Save browser mode</button>
            </div>
          </form>
          <div class="actions">
            <a class="button secondary" href="{html.escape(config.linkedin_company_admin_url)}" target="_blank" rel="noreferrer">Open Al-Batin admin</a>
            <form method="post" action="/open-article-editor" class="inline-form">
              <input type="hidden" name="return_to" value="{html.escape(return_to)}" />
              <button class="secondary" type="submit">Open and fill article draft</button>
            </form>
          </div>
          <form class="inline-form" method="post" action="/browser-session">
            <input type="hidden" name="return_to" value="{html.escape(return_to)}" />
            <input type="hidden" name="remote_debugging_url" value="" />
            <div class="actions">
              <button class="secondary" type="submit">Use local profile only</button>
            </div>
          </form>
        </section>
    """


def render_article_timing(config: AppConfig, return_to: str) -> str:
    return f"""
        <section class="card">
          <h2>Article Timing</h2>
          <form method="post" action="/article-settings">
            <input type="hidden" name="return_to" value="{html.escape(return_to)}" />
            <label for="article_schedule_buffer_minutes">Schedule buffer minutes</label>
            <input id="article_schedule_buffer_minutes" name="article_schedule_buffer_minutes" type="number" min="10" value="{html.escape(str(config.linkedin_article_schedule_buffer_minutes))}" />
            <label>
              <input type="checkbox" name="article_use_cover_image" value="true" {"checked" if config.linkedin_article_use_cover_image else ""} />
              Use cover image upload
            </label>
            <div class="actions">
              <button type="submit">Save article timing</button>
            </div>
          </form>
        </section>
    """


def render_status_filters(route: str, records: list[dict[str, Any]], selected_status: str | None) -> str:
    counts: dict[str, int] = {"all": len(records)}
    for status in ["queued", "processing", "done", "failed"]:
        counts[status] = sum(1 for record in records if str(record.get("status", "")) == status)

    chips = []
    active_status = selected_status or "all"
    for status in ["all", "queued", "processing", "done", "failed"]:
        active = " active" if active_status == status else ""
        chips.append(
            f"<a href=\"{status_filter_url(route, status)}\" class=\"button nav-chip{active}\">{html.escape(status.title())} ({counts[status]})</a>"
        )
    chips.append(
        f'<form class="inline-form" method="post" action="/retry-all"><input type="hidden" name="return_to" value="{html.escape(route)}" /><button type="submit">Retry all failed</button></form>'
    )
    return f"<div class='actions'>{''.join(chips)}</div>"


def render_scheduler_summary(records: list[dict[str, Any]]) -> str:
    total = len(records)
    failed = sum(1 for record in records if str(record.get('status', '')) == 'failed')
    processing = sum(1 for record in records if str(record.get('status', '')) == 'processing')
    queued = sum(1 for record in records if str(record.get('status', '')) == 'queued')
    done = sum(1 for record in records if str(record.get('status', '')) == 'done')
    latest_run = ""
    worker_runs = worker_run_summary(load_worker_runs())
    if worker_runs:
        latest = worker_runs[-1]
        latest_run = (
            f"<p class=\"meta\">Last worker run: "
            f"<strong>{html.escape(str(latest.get('status', 'unknown')))}</strong> · "
            f"{html.escape(str(latest.get('timestamp', 'unknown time')))}</p>"
        )
    return f"""
      <section class="card compact-card scheduler-summary-card">
        <div class="card-heading">
          <div>
            <h3>Scheduler Summary</h3>
            <p class="meta">Queue and worker history live on the Scheduler tab.</p>
          </div>
          <a class="button secondary" href="{ROUTE_SCHEDULER}">Open Scheduler</a>
        </div>
        <div class="summary-metrics">
          <a class="summary-pill" href="{status_filter_url(ROUTE_SCHEDULER, 'all')}"><strong>{total}</strong><span>Total</span></a>
          <a class="summary-pill" href="{status_filter_url(ROUTE_SCHEDULER, 'queued')}"><strong>{queued}</strong><span>Queued</span></a>
          <a class="summary-pill" href="{status_filter_url(ROUTE_SCHEDULER, 'processing')}"><strong>{processing}</strong><span>Processing</span></a>
          <a class="summary-pill" href="{status_filter_url(ROUTE_SCHEDULER, 'done')}"><strong>{done}</strong><span>Done</span></a>
          <a class="summary-pill" href="{status_filter_url(ROUTE_SCHEDULER, 'failed')}"><strong>{failed}</strong><span>Failed</span></a>
        </div>
        {latest_run}
      </section>
    """


def render_queue_table(queue: list[dict[str, Any]], route: str) -> str:
    queue_rows = []
    for item in reversed(queue):
        record_id = str(item.get("id", ""))
        queue_rows.append(
            f"<tr><td><a href=\"{queue_item_url(record_id, route)}\">{html.escape(str(item.get('scheduled_for', '')))}</a></td>"
            f"<td>{html.escape(str(item.get('platform', '')))}</td>"
            f"<td>{html.escape(str(item.get('content_type', 'article')))}</td>"
            f"<td>{html.escape(str(item.get('source_published_at', '') or 'Unknown'))}</td>"
            f"<td>{html.escape(str(item.get('article_title', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', 'queued')))}</td></tr>"
        )
    if not queue_rows:
        queue_rows.append("<tr><td colspan='6'>No scheduled items yet.</td></tr>")
    return f"""
      <section class="card">
        <h2>Schedule Queue</h2>
        <table>
          <thead><tr><th>Scheduled for</th><th>Platform</th><th>Type</th><th>Source published</th><th>Article</th><th>Status</th></tr></thead>
          <tbody>{''.join(queue_rows)}</tbody>
        </table>
      </section>
    """


def render_current_article(article: Article, image_count: int, teaser: str, teaser_meta: str) -> str:
    return f"""
    <section class=\"card\">
      <h2>Current Article</h2>
      <p><strong>{html.escape(article.title)}</strong></p>
      <p class=\"meta\"><a href=\"{html.escape(article.link)}\" class=\"inline-link\" target=\"_blank\" rel=\"noreferrer\">Open source article</a> · {image_count} images found</p>
      <p class=\"meta\">{html.escape(teaser_meta)}</p>
      <div class=\"teaser\">{html.escape(teaser) if teaser else 'Click Generate Preview to create the teaser.'}</div>
    </section>
    """


def render_create_schedule(article: Article, config: AppConfig, return_to: str) -> str:
    return f"""
    <section class=\"card\">
      <h2>Create Schedule</h2>
      <form method=\"post\" action=\"/schedule\">
        <input type=\"hidden\" name=\"return_to\" value=\"{html.escape(return_to)}\" />
        <label for=\"platform\">Platform</label>
        <select id=\"platform\" name=\"platform\">
          <option value=\"linkedin\">LinkedIn</option>
          <option value=\"x\">X</option>
          <option value=\"instagram\">Instagram</option>
          <option value=\"tiktok\">TikTok</option>
        </select>
        <label for=\"content_type\">Content type</label>
        <select id=\"content_type\" name=\"content_type\">
          <option value=\"article\" selected>Article</option>
          <option value=\"post\">Post</option>
        </select>
        <label for=\"scheduled_for\">Scheduled for</label>
        <input id=\"scheduled_for\" name=\"scheduled_for\" value=\"{html.escape(default_schedule_time('article', article, config))}\" />
        <label for=\"notes\">Notes</label>
        <textarea id=\"notes\" name=\"notes\" placeholder=\"Optional editorial notes\"></textarea>
        <div class=\"actions\"><button type=\"submit\">Save schedule</button></div>
      </form>
    </section>
    """


def render_linkedin_actions(config: AppConfig, return_to: str) -> str:
    return f"""
    <section class=\"card\">
      <h2>Stage LinkedIn Article Draft</h2>
      <p class=\"meta\">Launches the Playwright flow in the background. First goal: fill the article teaser in the \"Tell your network\" box, then fill title, body, and cover image for Al-Batin, and finally schedule the post using the saved buffer delay.</p>
      <form method=\"post\" action=\"/preview\">
        <input type=\"hidden\" name=\"return_to\" value=\"{html.escape(return_to)}\" />
        <div class=\"actions\"><button type=\"submit\">Generate preview</button></div>
      </form>
      <form method=\"post\" action=\"/launch\">
        <input type=\"hidden\" name=\"return_to\" value=\"{html.escape(return_to)}\" />
        <div class=\"actions\"><button class=\"secondary\" type=\"submit\">Open Al-Batin article flow</button></div>
      </form>
      <div class=\"actions\"><a class=\"button secondary\" href=\"{html.escape(config.linkedin_feed_url)}\" target=\"_blank\" rel=\"noreferrer\">Open LinkedIn in new tab</a></div>
    </section>
    """


def render_linkedin_page(config: AppConfig, snapshot: dict[str, Any], preview: dict[str, Any] | None, all_records: list[dict[str, Any]]) -> str:
    article: Article = snapshot["article"]
    image_count = snapshot["image_count"]
    teaser = ""
    teaser_meta = "No teaser generated yet."
    if preview and preview.get("article_link") == article.link:
        teaser = str(preview.get("teaser", ""))
        teaser_meta = f"Cached preview generated at {preview.get('generated_at', 'unknown time')}."
    return f"""
      <div class=\"page-grid\">
        <div class=\"stack\">
          {render_current_article(article, image_count, teaser, teaser_meta)}
          {render_create_schedule(article, config, ROUTE_LINKEDIN)}
          {render_linkedin_actions(config, ROUTE_LINKEDIN)}
        </div>
        <div class=\"stack\">
          {render_launch_status()}
          {render_scheduler_summary(all_records)}
        </div>
      </div>
    """


def render_scheduler_page(all_records: list[dict[str, Any]], queue: list[dict[str, Any]], selected_record: dict[str, Any] | None, selected_status: str | None) -> str:
    publish_queue_count = sum(1 for record in all_records if str(record.get("status", "")) in {"queued", "processing"})
    failed_count = sum(1 for record in all_records if str(record.get("status", "")) == "failed")
    return f"""
      <div class=\"page-grid\">
        <div class=\"stack\">
          <section class=\"card compact-card\">
            <div class=\"card-heading\">
              <div>
                <h2>Future Job Lanes</h2>
                <p class=\"meta\">This tab stays compatible with the current worker while making room for more job types.</p>
              </div>
            </div>
            <div class=\"summary-metrics\">
              <div class=\"summary-pill static\"><strong>{publish_queue_count}</strong><span>Publish Queue</span></div>
              <div class=\"summary-pill static\"><strong>0</strong><span>Stats Sync Queue</span></div>
              <div class=\"summary-pill static\"><strong>{failed_count}</strong><span>Failed Jobs</span></div>
            </div>
          </section>
          {render_status_filters(ROUTE_SCHEDULER, all_records, selected_status)}
          {render_queue_table(queue, ROUTE_SCHEDULER)}
          {render_worker_history()}
        </div>
        <div class=\"stack\">
          {render_record_detail(selected_record, ROUTE_SCHEDULER)}
        </div>
      </div>
    """


def render_config_page(config: AppConfig) -> str:
    return f"""
      <div class=\"page-grid\">
        <div class=\"stack\">
          <section class=\"card\">
            <h2>Config</h2>
            <p class=\"meta\">System and workflow configuration is managed here.</p>
            <div class=\"config-summary\">
              <div class=\"config-item\"><span class=\"config-label\">Config file</span><code>{html.escape(str(CONFIG_PATH))}</code></div>
              <div class=\"config-item\"><span class=\"config-label\">Local content directory</span><code>{html.escape(str(config.content_dir))}</code></div>
              <div class=\"config-item\"><span class=\"config-label\">RSS feed</span><code>{html.escape(config.rss_url)}</code></div>
              <div class=\"config-item\"><span class=\"config-label\">Substack archive</span><code>{html.escape(config.substack_archive_url)}</code></div>
              <div class=\"config-item\"><span class=\"config-label\">Substack imports</span><code>{html.escape(str(config.substack_import_dir))}</code></div>
              <div class=\"config-item\"><span class=\"config-label\">LinkedIn feed</span><code>{html.escape(config.linkedin_feed_url)}</code></div>
              <div class=\"config-item\"><span class=\"config-label\">Article editor</span><code>{html.escape(config.linkedin_article_new_url)}</code></div>
              <div class=\"config-item\"><span class=\"config-label\">Publish as</span><code>{html.escape(config.linkedin_publish_as_page_name)}</code></div>
              <div class=\"config-item\"><span class=\"config-label\">Content mode</span><code>{html.escape(config.linkedin_content_mode)}</code></div>
              <div class=\"config-item\"><span class=\"config-label\">Schedule buffer</span><code>{html.escape(str(config.linkedin_article_schedule_buffer_minutes))} minutes</code></div>
              <div class=\"config-item\"><span class=\"config-label\">Stats sync interval</span><code>{html.escape(str(config.stats_sync_interval_minutes))} minutes</code></div>
              <div class=\"config-item\"><span class=\"config-label\">Cover upload</span><code>{'enabled' if config.linkedin_article_use_cover_image else 'disabled'}</code></div>
            </div>
          </section>
          <section class=\"card\">
            <h2>Platform Configuration</h2>
            <p class=\"meta\">Safe frontend fields only. Secrets should stay in environment variables or server-side config files.</p>
            <form method=\"post\" action=\"/system-config\">
              <input type=\"hidden\" name=\"return_to\" value=\"{html.escape(ROUTE_CONFIG)}\" />
              <label for=\"content_dir\">Local content directory</label>
              <input id=\"content_dir\" name=\"content_dir\" value=\"{html.escape(str(config.content_dir))}\" />
              <label for=\"substack_import_dir\">Substack export/import directory</label>
              <input id=\"substack_import_dir\" name=\"substack_import_dir\" value=\"{html.escape(str(config.substack_import_dir))}\" />
              <label for=\"stats_sync_interval_minutes\">Stats sync interval (minutes)</label>
              <input id=\"stats_sync_interval_minutes\" name=\"stats_sync_interval_minutes\" type=\"number\" min=\"15\" value=\"{html.escape(str(config.stats_sync_interval_minutes))}\" />
              <div class=\"editor-two-up\">
                <div>
                  <label><input type=\"checkbox\" name=\"linkedin_api_enabled\" value=\"true\" {'checked' if config.linkedin_api_enabled else ''} /> LinkedIn API enabled</label>
                  <label for=\"linkedin_api_org_urn\">LinkedIn org/page URN</label>
                  <input id=\"linkedin_api_org_urn\" name=\"linkedin_api_org_urn\" value=\"{html.escape(config.linkedin_api_org_urn)}\" placeholder=\"urn:li:organization:123\" />
                </div>
                <div>
                  <label><input type=\"checkbox\" name=\"instagram_api_enabled\" value=\"true\" {'checked' if config.instagram_api_enabled else ''} /> Instagram/Meta API enabled</label>
                  <label for=\"instagram_business_account_id\">Instagram business account ID</label>
                  <input id=\"instagram_business_account_id\" name=\"instagram_business_account_id\" value=\"{html.escape(config.instagram_business_account_id)}\" placeholder=\"1784...\" />
                </div>
              </div>
              <div class=\"editor-two-up\">
                <div>
                  <label><input type=\"checkbox\" name=\"substack_import_enabled\" value=\"true\" {'checked' if config.substack_import_enabled else ''} /> Substack import enabled</label>
                  <p class=\"meta\">Manual ZIP/CSV import is the default stats path for Substack.</p>
                </div>
                <div>
                  <label><input type=\"checkbox\" name=\"x_api_enabled\" value=\"true\" {'checked' if config.x_api_enabled else ''} /> X API enabled</label>
                  <label for=\"x_account_id\">X account ID</label>
                  <input id=\"x_account_id\" name=\"x_account_id\" value=\"{html.escape(config.x_account_id)}\" placeholder=\"account id\" />
                </div>
              </div>
              <div class=\"actions\"><button type=\"submit\">Save system config</button></div>
            </form>
          </section>
          {render_browser_session(config, ROUTE_CONFIG)}
          {render_article_timing(config, ROUTE_CONFIG)}
          {render_channel_cards(return_to=ROUTE_CONFIG)}
        </div>
      </div>
    """

def render_instagram_page() -> str:
    return f"""
      <div class=\"page-grid\"><div class=\"stack\">{render_placeholder_card('Instagram', 'Instagram workflow will be configured here later.')}</div></div>
    """


def render_stats_page(content_items: list[ContentItem]) -> str:
    publications = list_publications()
    snapshots = list_stats_snapshots()
    platform_counts = {
        "linkedin": sum(1 for publication in publications if publication.platform == "linkedin"),
        "instagram": sum(1 for publication in publications if publication.platform == "instagram"),
        "substack": sum(1 for publication in publications if publication.platform == "substack"),
        "x": sum(1 for publication in publications if publication.platform == "x"),
    }
    recent_items = "".join(
        f"<tr><td>{html.escape(item.title)}</td><td>{html.escape(item.status)}</td><td>{html.escape(', '.join(item.channels) or '—')}</td><td>{html.escape(item.updated_at or item.created_at or 'Unknown')}</td></tr>"
        for item in content_items[:8]
    ) or "<tr><td colspan='4'>No local content items yet.</td></tr>"
    return f"""
      <div class=\"page-grid\">
        <div class=\"stack\">
          <section class=\"card\">
            <h2>Stats Dashboard</h2>
            <p class=\"meta\">Official APIs, exports, or manual imports should feed these cards later. Web scraping is intentionally not the default path.</p>
            <div class=\"summary-metrics\">
              <div class=\"summary-pill static\"><strong>{platform_counts['linkedin']}</strong><span>LinkedIn publications</span></div>
              <div class=\"summary-pill static\"><strong>{platform_counts['instagram']}</strong><span>Instagram publications</span></div>
              <div class=\"summary-pill static\"><strong>{platform_counts['substack']}</strong><span>Substack publications</span></div>
              <div class=\"summary-pill static\"><strong>{platform_counts['x']}</strong><span>X publications</span></div>
              <div class=\"summary-pill static\"><strong>{len(snapshots)}</strong><span>Stats snapshots</span></div>
            </div>
          </section>
          <section class=\"card\">
            <h2>Content to Stats Mapping</h2>
            <table>
              <thead><tr><th>Content item</th><th>Status</th><th>Channels</th><th>Updated</th></tr></thead>
              <tbody>{recent_items}</tbody>
            </table>
          </section>
        </div>
        <div class=\"stack\">
          {render_placeholder_card('LinkedIn post stats', 'Impressions, reach, reactions, comments, shares, saves, clicks, and follower lift will appear here when the adapter is connected.')}
          {render_placeholder_card('Instagram insights', 'Professional account and media insights will be surfaced here through the Meta API when configured.')}
          {render_placeholder_card('Substack import stats', f'Manual ZIP/CSV imports from {SUBSTACK_IMPORTS_DIRNAME} will be associated to local content by title, slug, or URL.')}
          {render_placeholder_card('X post stats', 'X analytics can be attached here later if the account and API access are configured.')}
        </div>
      </div>
    """


def render_sidebar(active_route: str) -> str:
    items = []
    for route, icon_name, label, fallback in SIDEBAR_ITEMS:
        active = ' active' if route == active_route else ''
        items.append(
            f'<a class="sidebar-link{active}" href="{route}"><span class="sidebar-icon">{render_sidebar_icon(icon_name, fallback)}</span><span class="sidebar-label">{html.escape(label)}</span></a>'
        )
    return f"""
      <aside class=\"sidebar\" id=\"sidebar\">
        <div class=\"sidebar-top\">
          <button class=\"sidebar-toggle\" id=\"sidebar-toggle\" type=\"button\" aria-label=\"Toggle navigation\">≡</button>
        </div>
        <nav class=\"sidebar-nav\">{''.join(items)}</nav>
      </aside>
    """


def render_main_content(route: str, config: AppConfig, snapshot: dict[str, Any] | None, all_records: list[dict[str, Any]], queue: list[dict[str, Any]], preview: dict[str, Any] | None, selected_record: dict[str, Any] | None, selected_status: str | None, content_items: list[ContentItem], selected_content_item: ContentItem) -> tuple[str, str, str]:
    if route == ROUTE_EDITOR:
        return '', '', render_editor_page(config, content_items, selected_content_item)
    if route == ROUTE_DRAFTS:
        return '', '', render_drafts_page(config, content_items, selected_content_item)
    if route == ROUTE_SCHEDULER:
        return 'Scheduler', 'Schedule Queue and Worker Runs', render_scheduler_page(all_records, queue, selected_record, selected_status)
    if route == ROUTE_STATS:
        return 'Stats', 'Central analytics workspace for local content items', render_stats_page(content_items)
    if route == ROUTE_INSTAGRAM:
        return 'Instagram', 'Instagram workflow placeholder', render_instagram_page()
    if route == ROUTE_CONFIG:
        return 'Config', 'System and workflow configuration', render_config_page(config)
    assert snapshot is not None
    return 'LinkedIn', 'Current LinkedIn workflow and article drafting tools', render_linkedin_page(config, snapshot, preview, all_records)


def render_page(
    route: str,
    config: AppConfig,
    snapshot: dict[str, Any] | None,
    all_records: list[dict[str, Any]],
    queue: list[dict[str, Any]],
    preview: dict[str, Any] | None,
    selected_record: dict[str, Any] | None,
    selected_status: str | None,
    content_items: list[ContentItem],
    selected_content_item: ContentItem,
) -> str:
    page_title, page_intro, page_content = render_main_content(route, config, snapshot, all_records, queue, preview, selected_record, selected_status, content_items, selected_content_item)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>SocialMediaManager</title>
  <style>
    :root {{
      --bg: #0f172a;
      --panel: #111827;
      --line: #1f2937;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-2: #22c55e;
      --sidebar-width: 252px;
      --sidebar-collapsed-width: 72px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at top, #1e293b, var(--bg));
      color: var(--text);
    }}
    a {{ color: inherit; }}
    .app-shell {{ display: flex; min-height: 100vh; }}
    .sidebar {{
      width: var(--sidebar-width);
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.98), rgba(15, 23, 42, 0.92));
      border-right: 1px solid rgba(148, 163, 184, 0.12);
      padding: 14px 12px;
      position: sticky;
      top: 0;
      height: 100vh;
      transition: width 0.2s ease, transform 0.2s ease;
      z-index: 20;
    }}
    .sidebar-top {{ display: flex; justify-content: flex-end; align-items: center; margin-bottom: 14px; }}
    .sidebar-toggle {{
      border: 1px solid rgba(148, 163, 184, 0.14); border-radius: 12px;
      background: rgba(30, 41, 59, 0.72); color: var(--text);
      width: 40px; height: 40px; cursor: pointer; font-size: 17px;
      transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
    }}
    .sidebar-toggle:hover {{
      background: rgba(51, 65, 85, 0.88);
      border-color: rgba(56, 189, 248, 0.22);
      transform: translateY(-1px);
    }}
    .sidebar-nav {{ display: grid; gap: 6px; }}
    .sidebar-link {{
      display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 8px 10px;
      border: 1px solid transparent; border-radius: 14px; text-decoration: none;
      color: var(--muted); transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
    }}
    .sidebar-link:hover {{ background: rgba(148, 163, 184, 0.06); border-color: rgba(148, 163, 184, 0.08); color: var(--text); }}
    .sidebar-link.active {{
      background: linear-gradient(180deg, rgba(56, 189, 248, 0.16), rgba(56, 189, 248, 0.1));
      color: var(--text); border-color: rgba(56, 189, 248, 0.22);
    }}
    .sidebar-icon {{
      width: 32px; height: 32px; border-radius: 10px; background: rgba(148, 163, 184, 0.07);
      display: inline-flex; align-items: center; justify-content: center; font-weight: 700; flex-shrink: 0;
      color: currentColor;
    }}
    .sidebar-icon svg {{ width: 18px; height: 18px; fill: currentColor; stroke: currentColor; stroke-width: 1.7; }}
    .sidebar-fallback {{ font-size: 11px; letter-spacing: 0.08em; }}
    .sidebar-label {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 14px; font-weight: 600; }}
    .main-shell {{ flex: 1; min-width: 0; transition: margin 0.2s ease, width 0.2s ease; }}
    .wrap {{ max-width: 1360px; margin: 0 auto; padding: 28px 24px 40px; }}
    .page-header {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; margin-bottom: 24px; }}
    .page-title {{ margin: 0; font-size: 32px; }}
    .page-subtitle {{ margin: 8px 0 0; color: var(--muted); }}
    .page-grid {{ display: grid; gap: 20px; grid-template-columns: minmax(0, 1.15fr) minmax(320px, .85fr); }}
    .stack {{ display: grid; gap: 20px; align-content: start; }}
    .card {{
      background: rgba(17, 24, 39, 0.9);
      border: 1px solid rgba(148, 163, 184, 0.14);
      border-radius: 18px;
      padding: 20px;
      box-shadow: 0 18px 60px rgba(15, 23, 42, 0.45);
      min-width: 0;
    }}
    .compact-card {{ padding: 18px 20px; }}
    .card-heading {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .meta {{ color: var(--muted); font-size: 14px; }}
    .teaser {{ white-space: pre-wrap; line-height: 1.6; word-break: break-word; }}
    .inline-link {{ color: var(--accent); text-decoration: none; }}
    label {{ display: block; margin: 14px 0 6px; color: var(--muted); font-size: 14px; }}
    input, select, textarea {{
      width: 100%; border-radius: 12px; border: 1px solid var(--line); background: #0b1120; color: var(--text); padding: 12px; font: inherit;
    }}
    textarea {{ min-height: 180px; resize: vertical; }}
    .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; }}
    .inline-form {{ margin: 0; }}
    button, .button {{
      border: 0; border-radius: 999px; background: var(--accent); color: #00111f; padding: 11px 16px; font-weight: 700; cursor: pointer; text-decoration: none;
    }}
    .secondary {{ background: var(--accent-2); }}
    .nav-chip {{ background: rgba(56, 189, 248, 0.16); color: var(--text); }}
    .nav-chip.active {{ outline: 1px solid rgba(56, 189, 248, 0.35); }}
    .summary-metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 10px; margin: 16px 0 6px; }}
    .summary-pill {{
      display: grid; gap: 4px; text-decoration: none; padding: 12px; border-radius: 14px;
      background: rgba(148, 163, 184, 0.08); border: 1px solid rgba(148, 163, 184, 0.12);
    }}
    .summary-pill.static {{ cursor: default; }}
    .summary-pill strong {{ font-size: 20px; }}
    .summary-pill span {{ color: var(--muted); font-size: 13px; }}
    .config-summary {{ display: grid; gap: 10px; }}
    .config-item {{
      display: grid; gap: 6px; padding: 12px 14px; border-radius: 14px;
      background: rgba(148, 163, 184, 0.06); border: 1px solid rgba(148, 163, 184, 0.10);
    }}
    .config-label {{ color: var(--muted); font-size: 13px; }}
    .editor-grid {{ grid-template-columns: minmax(0, 1.2fr) minmax(340px, .8fr); }}
    .editor-two-up {{ display: grid; gap: 14px; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .editor-textarea {{ min-height: 420px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .editor-studio {{
      display: grid;
      grid-template-columns: minmax(260px, 300px) minmax(0, 1fr);
      gap: 28px;
      align-items: start;
    }}
    .editor-sidebar-panel {{
      position: sticky;
      top: 24px;
      align-self: start;
    }}
    .editor-main {{ min-width: 0; }}
    body.route-editor .wrap {{
      max-width: 100%;
      padding: 18px 28px 40px;
    }}
    body.route-editor .page-header {{
      margin-bottom: 16px;
    }}
    body.route-editor .page-title {{
      font-size: 24px;
    }}
    body.route-editor .editor-main > .card {{
      background: transparent;
      border: 0;
      box-shadow: none;
      padding: 0;
    }}
    .writer-shell {{
      display: grid;
      gap: 12px;
    }}
    .sr-only {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    .writer-layout {{
      display: grid;
      gap: 32px;
      grid-template-columns: minmax(0, 1fr) minmax(220px, 252px);
      align-items: start;
    }}
    .writer-compose {{
      display: grid;
      gap: 10px;
      min-width: 0;
    }}
    .editor-primary-fields,
    .editor-side-fields {{
      display: grid;
      gap: 6px;
    }}
    .editor-primary-fields {{
      width: 100%;
      max-width: 860px;
      margin: 0 auto;
    }}
    .editor-writing-surface {{
      width: 100%;
      max-width: 860px;
      margin: 0 auto;
      display: grid;
      gap: 0;
      border-radius: 28px;
      background: rgba(8, 15, 30, 0.76);
      border: 1px solid rgba(148, 163, 184, 0.10);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 22px 60px rgba(2, 6, 23, 0.28);
    }}
    .editor-primary-fields-inline {{
      max-width: none;
      margin: 0;
      padding: 18px 24px 8px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.08);
    }}
    .editor-title-input {{
      border: 0;
      padding: 0;
      border-radius: 0;
      background: transparent;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2rem, 3.2vw, 3rem);
      line-height: 1.06;
      font-weight: 700;
      color: #f8fafc;
      letter-spacing: -0.03em;
    }}
    .editor-title-input:focus,
    .editor-subtitle-input:focus {{
      outline: none;
      box-shadow: none;
    }}
    .editor-subtitle-input {{
      border: 0;
      padding: 0;
      border-radius: 0;
      background: transparent;
      min-height: 48px;
      resize: none;
      color: #cbd5e1;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.08rem;
      line-height: 1.45;
    }}
    .editor-rail {{
      align-self: start;
      min-width: 0;
      position: sticky;
      top: 12px;
    }}
    .editor-rail-sticky {{
      display: grid;
      gap: 10px;
      align-content: start;
    }}
    .editor-panel {{
      background: rgba(11, 17, 32, 0.82);
      border: 1px solid rgba(148, 163, 184, 0.10);
      border-radius: 16px;
      overflow: hidden;
    }}
    .editor-panel-summary {{
      list-style: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 11px 12px;
      cursor: pointer;
      user-select: none;
    }}
    .editor-panel-summary::-webkit-details-marker {{
      display: none;
    }}
    .editor-panel-summary-left {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-weight: 700;
      font-size: 13px;
      color: #e2e8f0;
    }}
    .editor-panel-icon {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 26px;
      height: 26px;
      border-radius: 8px;
      background: rgba(30, 41, 59, 0.82);
      color: #cbd5e1;
      border: 1px solid rgba(51, 65, 85, 0.9);
      flex-shrink: 0;
    }}
    .editor-panel-icon svg {{
      width: 14px;
      height: 14px;
      fill: currentColor;
      stroke: currentColor;
      stroke-width: 0.7;
      flex-shrink: 0;
    }}
    .editor-panel-chevron {{
      width: 10px;
      height: 10px;
      border-right: 2px solid #94a3b8;
      border-bottom: 2px solid #94a3b8;
      transform: rotate(45deg);
      transition: transform 0.2s ease;
      margin-right: 4px;
      flex-shrink: 0;
    }}
    .editor-panel[open] .editor-panel-chevron {{
      transform: rotate(225deg);
      margin-top: 6px;
    }}
    .editor-panel-body {{
      display: grid;
      gap: 5px;
      padding: 0 12px 12px;
    }}
    .editor-panel-body .meta {{
      font-size: 12px;
      line-height: 1.4;
    }}
    .editor-panel-body label {{
      margin: 8px 0 4px;
      font-size: 12px;
    }}
    .editor-panel-body input,
    .editor-panel-body select,
    .editor-panel-body textarea {{
      padding: 10px 11px;
      border-radius: 10px;
      font-size: 13px;
    }}
    .editor-ai-prompt {{
      min-height: 92px;
      resize: vertical;
      border-radius: 14px;
      border: 1px solid rgba(51, 65, 85, 0.9);
      background: rgba(15, 23, 42, 0.88);
      color: #dbe4f0;
      padding: 10px 11px;
      font: inherit;
      line-height: 1.45;
    }}
    .editor-panel-button {{
      justify-self: start;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border-radius: 10px;
      border: 1px solid rgba(56, 189, 248, 0.28);
      background: rgba(14, 116, 144, 0.16);
      color: #dbeafe;
      font-size: 12px;
      font-weight: 700;
      transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
    }}
    .editor-panel-button:hover {{
      background: rgba(14, 116, 144, 0.24);
      border-color: rgba(56, 189, 248, 0.44);
      color: #f8fafc;
    }}
    .editor-panel-button.subtle {{
      min-height: 30px;
      padding: 0 10px;
      border-color: rgba(71, 85, 105, 0.9);
      background: rgba(30, 41, 59, 0.82);
      color: #dbe4f0;
      font-weight: 600;
    }}
    .editor-ai-feedback {{
      margin: 2px 0 0;
      min-height: 18px;
    }}
    .revision-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 3px;
    }}
    .revision-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      padding: 5px 0;
      border-top: 1px solid rgba(51, 65, 85, 0.5);
    }}
    .revision-item:first-child {{
      border-top: 0;
      padding-top: 0;
    }}
    .revision-copy {{
      min-width: 0;
      display: grid;
      gap: 1px;
    }}
    .revision-copy strong {{
      color: #e2e8f0;
      font-size: 11px;
      line-height: 1.25;
      word-break: break-word;
    }}
    .revision-copy .meta {{
      font-size: 11px;
      line-height: 1.2;
    }}
    .revision-empty {{
      padding: 1px 0;
    }}
    .revision-form {{
      margin: 0;
      flex-shrink: 0;
    }}
    .revision-form .editor-panel-button.subtle {{
      min-height: 26px;
      padding: 0 8px;
      font-size: 11px;
      border-radius: 9px;
    }}
    .editor-status-bar {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      color: var(--muted);
      font-size: 13px;
      border-top: 1px solid rgba(148, 163, 184, 0.10);
      padding: 10px 2px 0;
    }}
    .editor-workbench {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 14px;
      align-items: start;
    }}
    .editor-column {{
      min-width: 0;
      display: grid;
      gap: 14px;
      max-width: 860px;
      width: 100%;
      margin: 0 auto;
    }}
    .editor-toolbar {{
      position: sticky;
      top: 12px;
      z-index: 5;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      padding: 8px 10px;
      border-radius: 18px;
      background: rgba(5, 10, 20, 0.94);
      border: 1px solid rgba(51, 65, 85, 0.9);
      backdrop-filter: blur(12px);
      box-shadow: 0 16px 40px rgba(2, 6, 23, 0.3);
    }}
    .editor-toolbar-group {{
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .editor-toolbar-group-actions {{
      margin-left: auto;
      padding-left: 12px;
      border-left: 1px solid rgba(51, 65, 85, 0.9);
    }}
    .editor-toolbar button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      background: rgba(30, 41, 59, 0.82);
      color: #dbe4f0;
      padding: 0;
      border-radius: 10px;
      border: 1px solid rgba(51, 65, 85, 0.9);
      font-weight: 600;
      transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
    }}
    .editor-toolbar button:hover {{
      background: rgba(51, 65, 85, 0.95);
      border-color: rgba(71, 85, 105, 0.95);
      color: #f8fafc;
      transform: translateY(-1px);
    }}
    .editor-toolbar button svg {{
      width: 17px;
      height: 17px;
      fill: currentColor;
      stroke: currentColor;
      stroke-width: 0.6;
      flex-shrink: 0;
    }}
    .editor-toolbar button.is-active {{
      background: rgba(15, 23, 42, 0.98);
      color: #7dd3fc;
      border-color: rgba(56, 189, 248, 0.38);
      box-shadow: inset 0 0 0 1px rgba(56, 189, 248, 0.18);
    }}
    .editor-toolbar-action {{
      background: rgba(17, 24, 39, 0.96);
    }}
    .editor-toolbar-action.secondary {{
      background: rgba(30, 41, 59, 0.82);
    }}
    .editor-drop-hint {{
      display: none;
      align-items: center;
      justify-content: center;
      padding: 16px;
      border-radius: 18px;
      border: 1px dashed rgba(56, 189, 248, 0.45);
      background: rgba(56, 189, 248, 0.08);
      color: #bae6fd;
      font-size: 14px;
      font-weight: 600;
    }}
    .editor-column.drag-over .editor-drop-hint {{
      display: flex;
    }}
    .editor-column.drag-over .editor-writing-surface {{
      border-color: rgba(56, 189, 248, 0.38);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 0 0 3px rgba(56, 189, 248, 0.12), 0 22px 60px rgba(2, 6, 23, 0.28);
    }}
    .tiptap-editor {{
      min-height: 760px;
      border-radius: 0 0 28px 28px;
      background: transparent;
      border: 0;
      padding: 8px 24px 18px;
      box-shadow: none;
    }}
    .tiptap-editor .ProseMirror {{
      min-height: 700px;
      max-width: 680px;
      margin: 0 auto;
      padding: 30px 18px 120px;
      outline: none;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.22rem;
      line-height: 1.95;
      color: #f8fafc;
    }}
    .tiptap-editor .ProseMirror p.is-editor-empty:first-child::before {{
      color: #64748b;
      content: attr(data-placeholder);
      float: left;
      height: 0;
      pointer-events: none;
    }}
    .tiptap-editor .ProseMirror h1,
    .tiptap-editor .ProseMirror h2,
    .tiptap-editor .ProseMirror h3 {{
      font-family: Georgia, "Times New Roman", serif;
      line-height: 1.18;
      margin: 1.4em 0 0.45em;
      color: #ffffff;
    }}
    .tiptap-editor .ProseMirror h1 {{ font-size: 2.2rem; }}
    .tiptap-editor .ProseMirror h2 {{ font-size: 1.75rem; }}
    .tiptap-editor .ProseMirror h3 {{ font-size: 1.4rem; }}
    .tiptap-editor .ProseMirror blockquote {{
      margin: 1.5em 0;
      padding-left: 1.1rem;
      border-left: 3px solid rgba(56, 189, 248, 0.5);
      color: #cbd5e1;
    }}
    .tiptap-editor .ProseMirror pre {{
      background: #020617;
      border: 1px solid rgba(148, 163, 184, 0.14);
      color: #dbeafe;
      padding: 16px 18px;
      border-radius: 16px;
      overflow-x: auto;
      font-size: 0.95rem;
      line-height: 1.65;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .tiptap-editor .ProseMirror code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      background: rgba(148, 163, 184, 0.12);
      border-radius: 6px;
      padding: 0.15em 0.35em;
      color: #bfdbfe;
    }}
    .tiptap-editor .ProseMirror pre code {{
      background: transparent;
      padding: 0;
      color: inherit;
    }}
    .tiptap-editor .ProseMirror hr {{
      border: 0;
      border-top: 1px solid rgba(148, 163, 184, 0.20);
      margin: 2.2rem 0;
    }}
    .tiptap-editor .ProseMirror img {{
      display: block;
      max-width: min(100%, 720px);
      border-radius: 18px;
      margin: 2rem auto;
      box-shadow: 0 20px 45px rgba(2, 6, 23, 0.42);
      border: 1px solid rgba(148, 163, 184, 0.14);
      background: rgba(15, 23, 42, 0.9);
    }}
    .tiptap-editor .ProseMirror img.ProseMirror-selectednode {{
      outline: 3px solid rgba(56, 189, 248, 0.45);
      outline-offset: 3px;
    }}
    .tiptap-editor .ProseMirror a {{
      color: #7dd3fc;
      text-decoration: underline;
      text-decoration-thickness: 1px;
      text-underline-offset: 3px;
    }}
    body.editor-focus-mode .page-header,
    body.editor-focus-mode .editor-sidebar-panel,
    body.editor-focus-mode .editor-rail,
    body.editor-focus-mode .editor-toolbar-group-actions button:not(#editor-toggle-focus):not(#editor-toggle-preview) {{
      display: none;
    }}
    body.editor-focus-mode .writer-layout {{
      grid-template-columns: 1fr;
    }}
    body.editor-focus-mode .wrap {{
      max-width: 860px;
      padding-top: 28px;
    }}
    body.editor-focus-mode .tiptap-editor {{
      padding-left: 20px;
      padding-right: 20px;
    }}
    body.editor-focus-mode .tiptap-editor .ProseMirror {{
      max-width: 640px;
    }}
    .preview-column {{
      min-width: 0;
      display: none;
      gap: 16px;
      align-content: start;
    }}
    .preview-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .editor-preview-back {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 38px;
      height: 38px;
      padding: 0;
      border-radius: 12px;
      border: 1px solid rgba(51, 65, 85, 0.9);
      background: rgba(5, 10, 20, 0.94);
      color: #dbe4f0;
      transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
    }}
    .editor-preview-back:hover {{
      background: rgba(30, 41, 59, 0.95);
      border-color: rgba(71, 85, 105, 0.95);
      color: #f8fafc;
      transform: translateY(-1px);
    }}
    .editor-preview-back svg {{
      width: 18px;
      height: 18px;
      fill: currentColor;
      stroke: currentColor;
      stroke-width: 0.6;
      flex-shrink: 0;
    }}
    .preview-meta-card {{ padding: 18px; }}
    .writer-shell.preview-mode .editor-column {{ display: none; }}
    .writer-shell.preview-mode .editor-workbench {{
      grid-template-columns: 1fr;
    }}
    .writer-shell.preview-mode .preview-column {{
      display: grid;
      max-width: 820px;
    }}
    .writer-shell.preview-mode .markdown-preview {{
      min-height: 740px;
    }}
    .checkbox-grid-rail {{
      grid-template-columns: 1fr;
      margin-top: 0;
    }}
    .checkbox-grid-rail label {{
      margin: 0;
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(15, 23, 42, 0.55);
      border: 1px solid rgba(51, 65, 85, 0.7);
      color: #cbd5e1;
    }}
    .cover-preview {{
      border-radius: 16px;
      overflow: hidden;
      background: rgba(15, 23, 42, 0.78);
      border: 1px solid rgba(148, 163, 184, 0.12);
      min-height: 160px;
      display: grid;
      place-items: center;
      margin-bottom: 12px;
    }}
    .cover-preview-image {{
      width: 100%;
      max-height: 260px;
      object-fit: cover;
      display: block;
    }}
    .cover-preview-empty {{
      color: var(--muted);
      font-size: 14px;
      padding: 24px;
      text-align: center;
    }}
    .checkbox-grid {{ display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 10px; }}
    .checkbox-grid label {{ margin: 0; padding: 10px 12px; border: 1px solid rgba(148, 163, 184, 0.14); border-radius: 12px; background: rgba(148, 163, 184, 0.04); }}
    .content-list {{ display: grid; gap: 10px; }}
    .content-link {{
      display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 12px; border-radius: 14px;
      background: rgba(148, 163, 184, 0.05); border: 1px solid rgba(148, 163, 184, 0.10);
    }}
    .content-link-main {{ display: grid; gap: 4px; min-width: 0; flex: 1; text-decoration: none; }}
    .content-link span {{ color: var(--muted); font-size: 13px; }}
    .content-link.active {{ border-color: rgba(56, 189, 248, 0.45); background: rgba(56, 189, 248, 0.10); }}
    .content-link-menu {{ position: relative; flex-shrink: 0; align-self: flex-start; margin-top: -2px; }}
    .content-link-menu summary {{
      list-style: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 28px;
      min-height: 28px;
      padding: 0 2px;
      border: 0;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      user-select: none;
      font-size: 28px;
      font-weight: 700;
      line-height: 1;
    }}
    .content-link-menu summary:hover {{ color: var(--text); }}
    .content-link-menu summary::-webkit-details-marker {{ display: none; }}
    .content-link-menu-items {{
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      min-width: 160px;
      display: grid;
      gap: 6px;
      padding: 8px;
      border-radius: 14px;
      background: rgba(11, 17, 32, 0.98);
      border: 1px solid rgba(148, 163, 184, 0.12);
      box-shadow: 0 18px 50px rgba(2, 6, 23, 0.45);
      z-index: 5;
    }}
    .content-link-menu-items form {{ margin: 0; }}
    .content-link-menu-items button {{
      width: 100%;
      padding: 10px 12px;
      border-radius: 10px;
      background: rgba(30, 41, 59, 0.9);
      color: var(--text);
      text-align: left;
      font-weight: 600;
    }}
    .content-link-menu-items button.danger {{
      background: rgba(127, 29, 29, 0.85);
      color: #fee2e2;
    }}
    .markdown-preview {{
      border: 1px solid rgba(148, 163, 184, 0.14); border-radius: 16px; padding: 18px;
      background: rgba(11, 17, 32, 0.72); min-height: 320px;
    }}
    .markdown-preview h1, .markdown-preview h2, .markdown-preview h3 {{ margin-top: 0; }}
    .markdown-preview p, .markdown-preview li {{ line-height: 1.7; }}
    .markdown-preview pre, .frontmatter-preview {{
      overflow-x: auto; padding: 16px; border-radius: 14px; background: rgba(11, 17, 32, 0.9);
      border: 1px solid rgba(148, 163, 184, 0.10); color: #cbd5e1; white-space: pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid rgba(148,163,184,0.14); vertical-align: top; }}
    th {{ color: var(--muted); font-size: 13px; }}
    code {{ color: #93c5fd; }}
    .status-ok {{ color: #86efac; }}
    .status-warn {{ color: #fbbf24; }}
    .status-bad {{ color: #fca5a5; }}
    body.sidebar-collapsed .sidebar {{ width: var(--sidebar-collapsed-width); }}
    body.sidebar-collapsed .sidebar-label {{ display: none; }}
    body.sidebar-collapsed .sidebar-top {{ justify-content: center; }}
    body.sidebar-collapsed .sidebar-link {{ justify-content: center; padding-left: 0; padding-right: 0; }}
    @media (max-width: 980px) {{
      .page-grid {{ grid-template-columns: 1fr; }}
      .editor-two-up, .checkbox-grid, .editor-studio, .writer-layout, .editor-workbench {{ grid-template-columns: 1fr; }}
      .editor-sidebar-panel, .editor-rail {{ position: static; }}
      .editor-status-bar {{ flex-direction: column; align-items: flex-start; }}
      .editor-toolbar {{ align-items: flex-start; }}
      .editor-toolbar-group-actions {{ margin-left: 0; padding-left: 0; border-left: 0; }}
      .tiptap-editor .ProseMirror {{ padding-left: 0; padding-right: 0; }}
    }}
    @media (max-width: 840px) {{
      .sidebar {{ position: fixed; left: 0; transform: translateX(0); }}
      body.sidebar-collapsed .sidebar {{ transform: translateX(calc(-1 * var(--sidebar-width) + var(--sidebar-collapsed-width))); width: var(--sidebar-width); }}
      .main-shell {{ margin-left: var(--sidebar-width); }}
      body.sidebar-collapsed .main-shell {{ margin-left: var(--sidebar-collapsed-width); }}
      .wrap {{ padding: 20px 16px 32px; }}
    }}
  </style>
</head>
<body class="route-{html.escape(route.strip('/') or 'root')}">
  <div class=\"app-shell\">
    {render_sidebar(route)}
    <main class=\"main-shell\">
      <div class=\"wrap\">
        {"<header class=\"page-header\"><div><h1 class=\"page-title\">%s</h1><p class=\"page-subtitle\">%s</p></div><p class=\"meta\">RSS feed: <code>%s</code></p></header>" % (html.escape(page_title), html.escape(page_intro), html.escape(config.rss_url)) if page_title or page_intro else ""}
        {page_content}
      </div>
    </main>
  </div>
  <script>
    const sidebarKey = 'socialmediamanager.sidebar.collapsed';
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const savedState = localStorage.getItem(sidebarKey);
    if (savedState === 'true') document.body.classList.add('sidebar-collapsed');
    sidebarToggle?.addEventListener('click', () => {{
      document.body.classList.toggle('sidebar-collapsed');
      localStorage.setItem(sidebarKey, document.body.classList.contains('sidebar-collapsed') ? 'true' : 'false');
    }});

    async function refreshLaunchStatus() {{
      const target = document.getElementById('launch-status-content');
      if (!target) return;
      try {{
        const response = await fetch('/launch-status', {{ cache: 'no-store' }});
        if (!response.ok) return;
        const status = await response.json();
        if (!status || !status.state) {{
          target.innerHTML = '<p class="meta">No launch in progress yet.</p>';
          return;
        }}
        const cls = status.state === 'done' ? 'status-ok' : (status.state === 'failed' ? 'status-bad' : 'status-warn');
        target.innerHTML = `
          <p class="meta">State: <code class="${{cls}}">${{status.state}}</code></p>
          <p class="meta">${{status.message || ''}}</p>
          <p class="meta">Updated: <code>${{status.updated_at || ''}}</code></p>
          <p class="meta">Log: <code>${{status.log_path || ''}}</code></p>
        `;
      }} catch (error) {{
        target.innerHTML = '<p class="meta">Launch status unavailable.</p>';
      }}
    }}
    refreshLaunchStatus();
    setInterval(refreshLaunchStatus, 2000);

  </script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    config: AppConfig
    config_path: str

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/assets/"):
            relative = parsed.path.removeprefix("/assets/")
            asset_path = (ASSETS_DIR / relative).resolve()
            try:
                asset_path.relative_to(ASSETS_DIR.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not asset_path.exists() or not asset_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime_type, _ = mimetypes.guess_type(asset_path.name)
            payload = asset_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", (mime_type or "application/octet-stream") + ("; charset=utf-8" if (mime_type or "").startswith(("text/", "application/javascript")) else ""))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path.startswith("/content-files/"):
            relative = parsed.path.removeprefix("/content-files/")
            asset_path = (self.config.content_dir / relative).resolve()
            try:
                asset_path.relative_to(self.config.content_dir.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not asset_path.exists() or not asset_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime_type, _ = mimetypes.guess_type(asset_path.name)
            payload = asset_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/channel-artifact":
            query = parse_qs(parsed.query)
            requested = query.get("path", [""])[0]
            if not requested:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            artifact_path = Path(requested).expanduser().resolve()
            try:
                artifact_path.relative_to(CHANNEL_SCREENSHOTS_DIR.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not artifact_path.exists() or not artifact_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime_type, _ = mimetypes.guess_type(artifact_path.name)
            payload = artifact_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/channel-job-log":
            query = parse_qs(parsed.query)
            channel_id = query.get("channel_id", [""])[0].strip()
            payload = json.dumps(
                {
                    "channel_id": channel_id,
                    "logs": [record.__dict__ for record in list_channel_job_logs(channel_id=channel_id or None, limit=40)],
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/launch-status":
            payload = load_launch_status()
            body = json.dumps(payload or {}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/channels":
            ensure_channel_store_dirs()
            body = json.dumps(
                {"channels": [entry.to_dict() for entry in scan_channel_registry(rescan=True)]},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/derivatives/export":
            query = parse_qs(parsed.query)
            derivative_id = query.get("derivative_id", [""])[0]
            export_format = query.get("format", ["markdown"])[0]
            derivative = get_derivative(derivative_id) if derivative_id else None
            if derivative is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if export_format == "text":
                payload = derivative.body.encode("utf-8")
                content_type = "text/plain; charset=utf-8"
                filename = f"{derivative.channel_id}-{derivative.id}.txt"
            else:
                markdown_payload = f"# {derivative.title}\n\n{derivative.body}\n"
                payload = markdown_payload.encode("utf-8")
                content_type = "text/markdown; charset=utf-8"
                filename = f"{derivative.channel_id}-{derivative.id}.md"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(payload)
            return
        route = normalize_route(parsed.path)
        if parsed.path not in {"/", route} and parsed.path != route:
            if parsed.path not in VALID_ROUTES:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

        try:
            ensure_studio_dirs(self.config.content_dir)
            content_items = list_content_items(self.config.content_dir)
            content_identifier = parse_qs(parsed.query).get("content", [None])[0]
            selected_content_item = get_content_item(self.config.content_dir, content_identifier) if content_identifier else None
            if selected_content_item is None:
                selected_content_item = make_empty_content_item()
            snapshot = build_snapshot(self.config) if route == ROUTE_LINKEDIN else None
            all_queue = load_schedule()
            preview = load_preview()
            selected_status = parse_qs(parsed.query).get("status", [None])[0]
            detail_id = parse_qs(parsed.query).get("detail", [None])[0]
            selected_record = get_schedule_record(detail_id) if detail_id else None
            queue = queue_summary(filter_queue(all_queue, selected_status))
            payload = render_page(route, self.config, snapshot, all_queue, queue, preview, selected_record, selected_status, content_items, selected_content_item).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, explain=str(exc))

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/assets/"):
            relative = parsed.path.removeprefix("/assets/")
            asset_path = (ASSETS_DIR / relative).resolve()
            try:
                asset_path.relative_to(ASSETS_DIR.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not asset_path.exists() or not asset_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime_type, _ = mimetypes.guess_type(asset_path.name)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", (mime_type or "application/octet-stream") + ("; charset=utf-8" if (mime_type or "").startswith(("text/", "application/javascript")) else ""))
            self.end_headers()
            return
        if parsed.path.startswith("/content-files/"):
            relative = parsed.path.removeprefix("/content-files/")
            asset_path = (self.config.content_dir / relative).resolve()
            try:
                asset_path.relative_to(self.config.content_dir.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not asset_path.exists() or not asset_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime_type, _ = mimetypes.guess_type(asset_path.name)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime_type or "application/octet-stream")
            self.end_headers()
            return
        route = normalize_route(parsed.path)
        if parsed.path not in {"/", route} and parsed.path not in VALID_ROUTES:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        content_type_header = self.headers.get("Content-Type", "")
        if path == "/editor/upload-image" and content_type_header.startswith("multipart/form-data"):
            try:
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": content_type_header,
                    },
                )
                raw_slug = str(form.getfirst("slug", "") or "")
                title = str(form.getfirst("title", "") or "")
                slug = slugify(raw_slug or title or "untitled")
                upload = form["image"] if "image" in form else None
                if upload is None or not getattr(upload, "filename", ""):
                    self.send_error(HTTPStatus.BAD_REQUEST, explain="Missing image file")
                    return
                filename = Path(str(upload.filename)).name
                safe_name = slugify(Path(filename).stem) + Path(filename).suffix.lower()
                paths = content_paths_for_slug(self.config.content_dir, slug)
                paths["assets"].mkdir(parents=True, exist_ok=True)
                target = paths["assets"] / safe_name
                with target.open("wb") as handle:
                    handle.write(upload.file.read())
                local_path = f"{config_path_string(str(self.config.content_dir))}/{slug}/assets/{safe_name}"
                payload = json.dumps(
                    {
                        "ok": True,
                        "slug": slug,
                        "filename": safe_name,
                        "local_path": local_path,
                        "public_url": f"/content-files/{slug}/assets/{safe_name}",
                    }
                ).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            except Exception as exc:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, explain=str(exc))
                return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(body)
        return_to = sanitize_return_to(form.get("return_to", [ROUTE_LINKEDIN])[0])

        try:
            ensure_studio_dirs(self.config.content_dir)
            if path == "/preview":
                snapshot = build_snapshot(self.config)
                article: Article = snapshot["article"]
                teaser = run_local_ai(build_prompt(article, self.config.max_teaser_words), self.config, article.link)
                cache_preview(
                    {
                        "generated_at": datetime.now().isoformat(timespec="seconds"),
                        "article_link": article.link,
                        "article_title": article.title,
                        "teaser": teaser,
                    }
                )
            elif path == "/schedule":
                snapshot = build_snapshot(self.config)
                article: Article = snapshot["article"]
                content_type = form_value(form, "content_type", "article")
                scheduled_for = form_value(form, "scheduled_for", default_schedule_time(content_type, article, self.config))
                teaser = run_local_ai(build_prompt(article, self.config.max_teaser_words), self.config, article.link)
                record = build_schedule_record(
                    article=article,
                    teaser=teaser,
                    platform=form_value(form, "platform", "linkedin"),
                    content_type=content_type,
                    scheduled_for=scheduled_for,
                    notes=form_value(form, "notes"),
                    image_sources=snapshot["image_sources"],
                )
                append_queue(record.to_dict())
            elif path == "/editor/save":
                existing = get_content_item(self.config.content_dir, form_value(form, "content_id")) if form_value(form, "content_id") else None
                item = build_editor_item_from_request(form, existing=existing)
                maybe_snapshot_revision(self.config.content_dir, existing, item, reason="save")
                save_content_item(self.config.content_dir, item, previous_slug=form_value(form, "previous_slug") or None)
                return_to = f"{ROUTE_EDITOR}?content={item.id}"
            elif path == "/editor/schedule":
                existing = get_content_item(self.config.content_dir, form_value(form, "content_id")) if form_value(form, "content_id") else None
                item = build_editor_item_from_request(form, existing=existing, forced_status="scheduled", fallback_channels=["linkedin"])
                maybe_snapshot_revision(self.config.content_dir, existing, item, reason="schedule")
                save_content_item(self.config.content_dir, item, previous_slug=form_value(form, "previous_slug") or None)
                article = article_from_content_item(item)
                teaser = teaser_from_markdown(item.markdown_body, max_words=min(self.config.max_teaser_words, 40))
                channels = item.channels or ["linkedin"]
                platform = channels[0]
                scheduled_for = default_schedule_time("article", article, self.config)
                record = build_schedule_record(
                    article=article,
                    teaser=teaser,
                    platform=platform,
                    content_type="article",
                    scheduled_for=scheduled_for,
                    notes=f"Queued from local editor draft {item.slug}",
                    image_sources=[],
                    content_item_id=item.id,
                    content_item_slug=item.slug,
                )
                append_queue(record.to_dict())
                return_to = f"{ROUTE_EDITOR}?content={item.id}"
            elif path == "/editor/autosave":
                existing = get_content_item(self.config.content_dir, form_value(form, "content_id")) if form_value(form, "content_id") else None
                item = build_editor_item_from_request(form, existing=existing)
                maybe_snapshot_revision(self.config.content_dir, existing, item, reason="autosave")
                save_content_item(self.config.content_dir, item, previous_slug=form_value(form, "previous_slug") or None)
                payload = json.dumps(
                    {
                        "ok": True,
                        "content_id": item.id,
                        "slug": item.slug,
                        "updated_at": item.updated_at,
                    }
                ).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            elif path == "/editor/ai-edit":
                prompt = form_value(form, "ai_prompt").strip()
                if not prompt:
                    payload = json.dumps({"ok": False, "error": "Add an AI instruction first."}).encode("utf-8")
                    self.send_response(HTTPStatus.BAD_REQUEST)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                existing = get_content_item(self.config.content_dir, form_value(form, "content_id")) if form_value(form, "content_id") else None
                current_item = build_editor_item_from_request(form, existing=existing)
                create_revision_snapshot(self.config.content_dir, current_item, reason="ai-before-edit")
                ai_output = run_local_ai(
                    build_editor_ai_prompt(
                        current_item.title,
                        current_item.subtitle,
                        current_item.markdown_body,
                        prompt,
                    ),
                    self.config,
                    f"local://editor/{current_item.slug}",
                )
                markdown_body = clean_ai_markdown_response(ai_output)
                if not markdown_body:
                    payload = json.dumps({"ok": False, "error": "AI returned an empty draft."}).encode("utf-8")
                    self.send_response(HTTPStatus.BAD_GATEWAY)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                html_body = render_markdown_html(markdown_body)
                payload = json.dumps(
                    {
                        "ok": True,
                        "markdown_body": markdown_body,
                        "html_body": html_body,
                    }
                ).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            elif path == "/editor/restore-revision":
                content_id = form_value(form, "content_id")
                revision_id = form_value(form, "revision_id")
                current_item = get_content_item(self.config.content_dir, content_id) if content_id else None
                revision = load_content_revision(self.config.content_dir, content_id, revision_id) if content_id and revision_id else None
                if not current_item or not revision:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                create_revision_snapshot(self.config.content_dir, current_item, reason="restore-before-revision")
                revision_item = revision.get("item") if isinstance(revision.get("item"), dict) else {}
                restored = build_content_item_from_form(
                    {
                        "title": str(revision_item.get("title") or current_item.title),
                        "subtitle": str(revision_item.get("subtitle") or ""),
                        "slug": str(revision_item.get("slug") or current_item.slug),
                        "status": str(revision_item.get("status") or "draft"),
                        "channels": revision_item.get("channels") or current_item.channels,
                        "tags": revision_item.get("tags") or [],
                        "categories": revision_item.get("categories") or [],
                        "published_at": str(revision_item.get("published_at") or ""),
                        "editor_json": revision.get("editor_json") or current_item.editor_json,
                        "markdown_body": str(revision.get("markdown_body") or current_item.markdown_body),
                        "html_body": str(revision.get("html_body") or current_item.html_body),
                        "cover_image_path": str(revision_item.get("cover_image_path") or ""),
                        "linkedin_post_urn": str(revision_item.get("linkedin_post_urn") or ""),
                        "instagram_media_id": str(revision_item.get("instagram_media_id") or ""),
                        "substack_post_id": str(revision_item.get("substack_post_id") or ""),
                        "x_post_id": str(revision_item.get("x_post_id") or ""),
                    },
                    existing=current_item,
                )
                save_content_item(self.config.content_dir, restored, previous_slug=current_item.slug)
                return_to = f"{ROUTE_EDITOR}?content={restored.id}"
            elif path in {"/drafts/post", "/drafts/schedule"}:
                content_id = form_value(form, "content_id")
                if not content_id:
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                item = get_content_item(self.config.content_dir, content_id)
                if not item:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if not item.channels:
                    item.channels = ["linkedin"]
                previous_item = ContentItem(**item.__dict__)
                item.status = "scheduled"
                maybe_snapshot_revision(self.config.content_dir, previous_item, item, reason="queue-from-draft")
                save_content_item(self.config.content_dir, item)
                article = article_from_content_item(item)
                teaser = teaser_from_markdown(item.markdown_body, max_words=min(self.config.max_teaser_words, 40))
                platform = item.channels[0]
                scheduled_for = (
                    datetime.now().isoformat(timespec="seconds")
                    if path == "/drafts/post"
                    else default_schedule_time("article", article, self.config)
                )
                record = build_schedule_record(
                    article=article,
                    teaser=teaser,
                    platform=platform,
                    content_type="article",
                    scheduled_for=scheduled_for,
                    notes=f"{'Post now' if path == '/drafts/post' else 'Scheduled'} from draft {item.slug}",
                    image_sources=[],
                    content_item_id=item.id,
                    content_item_slug=item.slug,
                )
                append_queue(record.to_dict())
            elif path == "/drafts/delete":
                content_id = form_value(form, "content_id")
                if not content_id:
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                deleted = delete_content_item(self.config.content_dir, content_id)
                if not deleted:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
            elif path == "/retry":
                record_id = form_value(form, "id")
                if not record_id:
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                record = get_schedule_record(record_id)
                if not record:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                update_schedule_record(
                    record_id,
                    {
                        "status": "queued",
                        "processed_at": None,
                        "result": None,
                    },
                )
            elif path == "/retry-all":
                reset_failed_schedule_records()
            elif path == "/channels/rescan":
                scan_channel_registry(rescan=True)
            elif path == "/channels/connect":
                channel_id = form_value(form, "channel_id").strip()
                entry = next((item for item in scan_channel_registry(rescan=True) if item.id == channel_id), None)
                if entry is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                connection, should_spawn = begin_channel_connect(
                    channel_id,
                    mode=entry.mode or str(entry.manifest.get("mode") or "playwright_local"),
                    local_profile_path=str(self.config.linkedin_user_data_dir.resolve()) if channel_id == "linkedin" else "",
                    capabilities_snapshot_json=dict(entry.manifest.get("capabilities") or {}),
                )
                if should_spawn:
                    spawn_worker_process(
                        self.config_path,
                        "--channel-id",
                        channel_id,
                        "--channel-action",
                        "connect",
                        "--channel-action-id",
                        connection.active_job_id,
                        log_name=f"{channel_id}-connect.log",
                    )
            elif path == "/channels/check":
                channel_id = form_value(form, "channel_id").strip()
                entry = next((item for item in scan_channel_registry(rescan=True) if item.id == channel_id), None)
                if entry is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                spawn_worker_process(
                    self.config_path,
                    "--channel-id",
                    channel_id,
                    "--channel-action",
                    "check_session",
                    log_name=f"{channel_id}-session-check.log",
                )
            elif path == "/channels/disconnect":
                channel_id = form_value(form, "channel_id").strip()
                entry = next((item for item in scan_channel_registry(rescan=True) if item.id == channel_id), None)
                if entry is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                connection = get_channel_connection(channel_id)
                profile_path = None
                if connection and connection.local_profile_path:
                    profile_path = Path(connection.local_profile_path).expanduser()
                elif channel_id == "linkedin":
                    profile_path = self.config.linkedin_user_data_dir.resolve()
                if profile_path and profile_path.exists():
                    PROFILE_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
                    archive_target = PROFILE_ARCHIVE_DIR / f"{channel_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                    shutil.move(str(profile_path), str(archive_target))
                connection = connection or ensure_channel_connection(
                    channel_id,
                    mode=entry.mode or str(entry.manifest.get("mode") or "playwright_local"),
                    status="not_configured",
                    local_profile_path=str(self.config.linkedin_user_data_dir.resolve()) if channel_id == "linkedin" else "",
                    capabilities_snapshot_json=dict(entry.manifest.get("capabilities") or {}),
                )
                connection.status = "not_configured"
                connection.connected_at = ""
                connection.last_checked_at = now_iso()
                connection.updated_at = now_iso()
                connection.last_error = ""
                save_channel_connection(connection)
            elif path == "/derivatives/generate":
                content_id = form_value(form, "content_id").strip()
                channel_id = form_value(form, "channel_id").strip()
                output_type = form_value(form, "output_type").strip()
                source_item = get_content_item(self.config.content_dir, content_id) if content_id else None
                if source_item is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                generate_derivative_for_document(
                    config=self.config,
                    source_item=source_item,
                    channel_id=channel_id,
                    output_type=output_type,
                )
            elif path in {"/derivatives/save", "/derivatives/review", "/derivatives/approve", "/derivatives/reject", "/derivatives/return-draft"}:
                derivative_id = form_value(form, "derivative_id").strip()
                title = form_value(form, "title")
                body_value = form_value(form, "body")
                if derivative_id:
                    save_derivative_edit(derivative_id, title=title, body=body_value)
                if path == "/derivatives/review":
                    send_derivative_for_review(derivative_id)
                elif path == "/derivatives/approve":
                    approve_derivative(derivative_id, approved_by="local_dashboard")
                elif path == "/derivatives/reject":
                    reject_derivative(derivative_id, approved_by="local_dashboard")
                elif path == "/derivatives/return-draft":
                    return_derivative_to_draft(derivative_id)
            elif path == "/publish-jobs/create":
                derivative_id = form_value(form, "derivative_id").strip()
                channel_id = form_value(form, "channel_id").strip()
                run_mode = form_value(form, "run_mode", "dry_run").strip() or "dry_run"
                create_publish_job_from_derivative(
                    derivative_id,
                    channel_id=channel_id,
                    run_mode=run_mode,
                )
                spawn_worker_process(
                    self.config_path,
                    "--once",
                    "--channel-jobs-only",
                    "--channel-id",
                    channel_id,
                    log_name=f"{channel_id}-publish.log",
                )
            elif path == "/derivatives/attach-url":
                derivative_id = form_value(form, "derivative_id").strip()
                channel_id = form_value(form, "channel_id").strip()
                external_url = form_value(form, "external_url").strip()
                manual_attach_published_url(derivative_id, channel_id=channel_id, external_url=external_url)
            elif path == "/metrics/refresh":
                published_post_id = form_value(form, "published_post_id").strip()
                metric_job = queue_manual_metric_refresh(published_post_id)
                spawn_worker_process(
                    self.config_path,
                    "--once",
                    "--channel-jobs-only",
                    "--channel-id",
                    metric_job.channel_id,
                    log_name=f"{metric_job.channel_id}-metrics.log",
                )
            elif path == "/browser-session":
                remote_url = form_value(form, "remote_debugging_url").strip()
                save_config_value(
                    self.config_path,
                    {
                        "linkedin_remote_debugging_url": remote_url,
                    },
                )
                self.config.linkedin_remote_debugging_url = remote_url
            elif path == "/article-settings":
                buffer_minutes_value = form_value(form, "article_schedule_buffer_minutes", str(self.config.linkedin_article_schedule_buffer_minutes)).strip()
                use_cover_image = parse_checkbox(form, "article_use_cover_image")
                try:
                    buffer_minutes = max(10, int(buffer_minutes_value))
                except ValueError:
                    buffer_minutes = self.config.linkedin_article_schedule_buffer_minutes
                save_config_value(
                    self.config_path,
                    {
                        "linkedin_article_schedule_buffer_minutes": buffer_minutes,
                        "linkedin_article_use_cover_image": use_cover_image,
                    },
                )
                self.config.linkedin_article_schedule_buffer_minutes = buffer_minutes
                self.config.linkedin_article_use_cover_image = use_cover_image
            elif path == "/system-config":
                content_dir_value = form_value(form, "content_dir", str(self.config.content_dir)).strip() or str(self.config.content_dir)
                substack_import_dir_value = form_value(form, "substack_import_dir", str(self.config.substack_import_dir)).strip() or str(self.config.substack_import_dir)
                try:
                    stats_sync_interval = max(15, int(form_value(form, "stats_sync_interval_minutes", str(self.config.stats_sync_interval_minutes))))
                except ValueError:
                    stats_sync_interval = self.config.stats_sync_interval_minutes
                updates = {
                    "content_dir": config_path_string(content_dir_value),
                    "substack_import_dir": config_path_string(substack_import_dir_value),
                    "stats_sync_interval_minutes": stats_sync_interval,
                    "linkedin_api_enabled": parse_checkbox(form, "linkedin_api_enabled"),
                    "linkedin_api_org_urn": form_value(form, "linkedin_api_org_urn").strip(),
                    "instagram_api_enabled": parse_checkbox(form, "instagram_api_enabled"),
                    "instagram_business_account_id": form_value(form, "instagram_business_account_id").strip(),
                    "substack_import_enabled": parse_checkbox(form, "substack_import_enabled"),
                    "x_api_enabled": parse_checkbox(form, "x_api_enabled"),
                    "x_account_id": form_value(form, "x_account_id").strip(),
                }
                save_config_value(self.config_path, updates)
                self.config = load_config(self.config_path)
            elif path == "/launch":
                save_launch_status(
                    {
                        "action": "article_draft",
                        "state": "starting",
                        "message": "Launch requested from dashboard.",
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                thread = threading.Thread(target=launch_draft_process, args=(self.config_path,), daemon=True)
                thread.start()
            elif path == "/open-article-editor":
                save_launch_status(
                    {
                        "action": "article_draft",
                        "state": "starting",
                        "message": "Dashboard requested article draft fill.",
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                thread = threading.Thread(target=open_article_editor_process, args=(self.config_path,), daemon=True)
                thread.start()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", return_to)
            self.end_headers()
        except ChannelActionError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, explain=str(exc))
        except Exception as exc:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, explain=str(exc))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    ensure_runtime_dirs(config)
    ensure_outbox_dir()
    ensure_channel_store_dirs()

    DashboardHandler.config = config
    DashboardHandler.config_path = args.config
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
