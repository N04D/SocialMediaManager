from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape as html_escape
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from timing import compute_article_schedule_time

ROOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ROOT_DIR / "config.json"
DEFAULT_CONFIG = {
    "rss_url": "https://albatin.substack.com/feed",
    "substack_archive_url": "https://albatin.substack.com/archive",
    "linkedin_feed_url": "https://www.linkedin.com/feed/",
    "linkedin_company_admin_url": "https://www.linkedin.com/company/128603920/admin/dashboard/",
    "linkedin_article_new_url": "https://www.linkedin.com/article/new/?author=urn%3Ali%3Afsd_company%3A128603920",
    "linkedin_publish_as_page_name": "Al-Batin",
    "linkedin_content_mode": "article",
    "linkedin_article_publish_mode": "delay",
    "linkedin_article_delay_days": 7,
    "linkedin_article_publish_time": "15:00",
    "linkedin_article_use_cover_image": True,
    "linkedin_article_schedule_buffer_minutes": 10080,
    "linkedin_user_data_dir": "./linkedin_session",
    "linkedin_remote_debugging_url": "",
    "linkedin_browser_provider_id": "",
    "browser_provider_default_id": "provider.browser.legacy",
    "auto_browser_enabled": False,
    "auto_browser_base_url": "",
    "auto_browser_bearer_token_env": "AUTO_BROWSER_BEARER_TOKEN",
    "auto_browser_operator_id": "social-media-manager",
    "auto_browser_request_timeout": 15,
    "auto_browser_readiness_timeout": 5,
    "auto_browser_verify_tls": True,
    "auto_browser_auth_profile_prefix": "smm",
    "auto_browser_artifact_policy": "remote_reference",
    "auto_browser_takeover_public_base_url": "",
    "auto_browser_max_session_seconds": 1800,
    "auto_browser_expected_server_version": "1.3.1",
    "auto_browser_global_kill_switch": False,
    "auto_browser_account_kill_switches": [],
    "auto_browser_shared_upload_host_dir": "./studio_data/auto_browser_uploads",
    "auto_browser_shared_upload_controller_dir": "/shared/uploads/incoming",
    "auto_browser_auth_profile_delete_enabled": False,
    "auto_browser_pilot_accounts": [],
    "auto_browser_doctor_last_passed_at": "",
    "auto_browser_integration_last_passed_at": "",
    "auto_browser_chaos_last_passed_at": "",
    "media_dir": "./tmp_media",
    "media_storage_root": "./studio_data/media",
    "ai_cli_command": "auto",
    "ai_cli_args": [],
    "ai_cli_mode": "stdin",
    "headless": False,
    "article_delay_index": 1,
    "max_teaser_words": 150,
    "cleanup_media_after_run": True,
    "linkedin_wait_after_open_seconds": 2.0,
    "content_dir": "./content/drafts",
    "substack_import_dir": "./imports/substack",
    "stats_sync_interval_minutes": 1440,
    "linkedin_api_enabled": False,
    "linkedin_api_org_urn": "",
    "instagram_api_enabled": False,
    "instagram_business_account_id": "",
    "substack_import_enabled": True,
    "x_api_enabled": False,
    "x_account_id": "",
}

LEGACY_LINKEDIN_PIPELINE_DEPRECATION = {
    "deprecated": True,
    "deprecated_since": "browser-framework-v1.0.0",
    "replacement": "LinkedInChannelRuntime article capability in a future browser framework version",
    "removal_target": "phase-10-or-dedicated-article-migration",
    "reason": "Legacy/manual article staging can bypass provider-managed browser ownership.",
}

POST_BUTTON_PATTERNS = [
    r"^Start a post$",
    r"^Create a post$",
    r"^Bijdrage starten$",
    r"^Post starten$",
    r"^Bericht starten$",
]

ARTICLE_BUTTON_PATTERNS = [
    r"^Write article$",
    r"^Write an article$",
    r"^Schrijf artikel$",
    r"^Artikel schrijven$",
    r"^Write.*article$",
]

PUBLISH_AS_PATTERNS = [
    r"^Publish as$",
    r"^Publiceren als$",
    r"^Dropdown$",
]


@dataclass
class AppConfig:
    rss_url: str
    substack_archive_url: str
    linkedin_feed_url: str
    linkedin_company_admin_url: str
    linkedin_article_new_url: str
    linkedin_publish_as_page_name: str
    linkedin_content_mode: str
    linkedin_article_publish_mode: str
    linkedin_article_delay_days: int
    linkedin_article_publish_time: str
    linkedin_article_use_cover_image: bool
    linkedin_article_schedule_buffer_minutes: int
    linkedin_user_data_dir: Path
    linkedin_remote_debugging_url: str
    linkedin_browser_provider_id: str
    browser_provider_default_id: str
    auto_browser_enabled: bool
    auto_browser_base_url: str
    auto_browser_bearer_token_env: str
    auto_browser_operator_id: str
    auto_browser_request_timeout: int
    auto_browser_readiness_timeout: int
    auto_browser_verify_tls: bool
    auto_browser_auth_profile_prefix: str
    auto_browser_artifact_policy: str
    auto_browser_takeover_public_base_url: str
    auto_browser_max_session_seconds: int
    auto_browser_expected_server_version: str
    auto_browser_global_kill_switch: bool
    auto_browser_account_kill_switches: list[str]
    auto_browser_shared_upload_host_dir: str
    auto_browser_shared_upload_controller_dir: str
    auto_browser_auth_profile_delete_enabled: bool
    auto_browser_pilot_accounts: list[str]
    auto_browser_doctor_last_passed_at: str
    auto_browser_integration_last_passed_at: str
    auto_browser_chaos_last_passed_at: str
    media_dir: Path
    media_storage_root: Path
    ai_cli_command: str
    ai_cli_args: list[str] = field(default_factory=list)
    ai_cli_mode: str = "stdin"
    headless: bool = False
    article_delay_index: int = 1
    max_teaser_words: int = 150
    cleanup_media_after_run: bool = True
    linkedin_wait_after_open_seconds: float = 2.0
    content_dir: Path = field(default_factory=Path)
    substack_import_dir: Path = field(default_factory=Path)
    stats_sync_interval_minutes: int = 1440
    linkedin_api_enabled: bool = False
    linkedin_api_org_urn: str = ""
    instagram_api_enabled: bool = False
    instagram_business_account_id: str = ""
    substack_import_enabled: bool = True
    x_api_enabled: bool = False
    x_account_id: str = ""


@dataclass
class Article:
    title: str
    link: str
    html: str
    text: str
    published_at: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Substack to LinkedIn pipeline")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to config.json")
    parser.add_argument("--dry-run", action="store_true", help="Print output without opening LinkedIn")
    parser.add_argument(
        "--open-linkedin", action="store_true", help="Open LinkedIn feed in the configured browser session and exit"
    )
    parser.add_argument(
        "--open-article-editor",
        action="store_true",
        help="Open the LinkedIn article editor in the configured browser session and exit",
    )
    parser.add_argument(
        "--article-body-only",
        action="store_true",
        help="Open the LinkedIn article editor, fill only title and body, wait for save, and exit before teaser/schedule",
    )
    parser.add_argument("--no-cleanup", action="store_true", help="Keep downloaded media after the run")
    parser.add_argument(
        "--save-draft",
        action="store_true",
        help="Stage the LinkedIn draft and close after a short pause instead of waiting for Enter",
    )
    return parser.parse_args()


def load_config(config_path: str) -> AppConfig:
    path = Path(config_path)
    raw: dict[str, object] = dict(DEFAULT_CONFIG)
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("config.json must contain a JSON object")
        raw.update(loaded)

    ai_args = raw.get("ai_cli_args", [])
    if isinstance(ai_args, str):
        ai_args = [ai_args]
    if not isinstance(ai_args, list):
        ai_args = []

    return AppConfig(
        rss_url=str(raw["rss_url"]),
        substack_archive_url=str(raw.get("substack_archive_url", "https://albatin.substack.com/archive")),
        linkedin_feed_url=str(raw["linkedin_feed_url"]),
        linkedin_company_admin_url=str(
            raw.get("linkedin_company_admin_url", "https://www.linkedin.com/company/128603920/admin/dashboard/")
        ),
        linkedin_article_new_url=str(
            raw.get(
                "linkedin_article_new_url",
                "https://www.linkedin.com/article/new/?author=urn%3Ali%3Afsd_company%3A128603920",
            )
        ),
        linkedin_publish_as_page_name=str(raw.get("linkedin_publish_as_page_name", "Al-Batin")),
        linkedin_content_mode=str(raw.get("linkedin_content_mode", "article")),
        linkedin_article_publish_mode=str(raw.get("linkedin_article_publish_mode", "delay")),
        linkedin_article_delay_days=int(raw.get("linkedin_article_delay_days", 7)),
        linkedin_article_publish_time=str(raw.get("linkedin_article_publish_time", "15:00")),
        linkedin_article_use_cover_image=bool(raw.get("linkedin_article_use_cover_image", False)),
        linkedin_article_schedule_buffer_minutes=int(raw.get("linkedin_article_schedule_buffer_minutes", 1)),
        linkedin_user_data_dir=ROOT_DIR / str(raw["linkedin_user_data_dir"]),
        linkedin_remote_debugging_url=str(raw.get("linkedin_remote_debugging_url", "")),
        linkedin_browser_provider_id=str(raw.get("linkedin_browser_provider_id", "")),
        browser_provider_default_id=str(raw.get("browser_provider_default_id", "provider.browser.legacy")),
        auto_browser_enabled=bool(raw.get("auto_browser_enabled", False)),
        auto_browser_base_url=str(raw.get("auto_browser_base_url", "")),
        auto_browser_bearer_token_env=str(raw.get("auto_browser_bearer_token_env", "AUTO_BROWSER_BEARER_TOKEN")),
        auto_browser_operator_id=str(raw.get("auto_browser_operator_id", "social-media-manager")),
        auto_browser_request_timeout=int(raw.get("auto_browser_request_timeout", 15)),
        auto_browser_readiness_timeout=int(raw.get("auto_browser_readiness_timeout", 5)),
        auto_browser_verify_tls=bool(raw.get("auto_browser_verify_tls", True)),
        auto_browser_auth_profile_prefix=str(raw.get("auto_browser_auth_profile_prefix", "smm")),
        auto_browser_artifact_policy=str(raw.get("auto_browser_artifact_policy", "remote_reference")),
        auto_browser_takeover_public_base_url=str(raw.get("auto_browser_takeover_public_base_url", "")),
        auto_browser_max_session_seconds=int(raw.get("auto_browser_max_session_seconds", 1800)),
        auto_browser_expected_server_version=str(raw.get("auto_browser_expected_server_version", "1.3.1")),
        auto_browser_global_kill_switch=bool(raw.get("auto_browser_global_kill_switch", False)),
        auto_browser_account_kill_switches=[
            str(item) for item in raw.get("auto_browser_account_kill_switches", []) if str(item)
        ],
        auto_browser_shared_upload_host_dir=str(
            raw.get("auto_browser_shared_upload_host_dir", "./studio_data/auto_browser_uploads")
        ),
        auto_browser_shared_upload_controller_dir=str(
            raw.get("auto_browser_shared_upload_controller_dir", "/shared/uploads/incoming")
        ),
        auto_browser_auth_profile_delete_enabled=bool(raw.get("auto_browser_auth_profile_delete_enabled", False)),
        auto_browser_pilot_accounts=[str(item) for item in raw.get("auto_browser_pilot_accounts", []) if str(item)],
        auto_browser_doctor_last_passed_at=str(raw.get("auto_browser_doctor_last_passed_at", "")),
        auto_browser_integration_last_passed_at=str(raw.get("auto_browser_integration_last_passed_at", "")),
        auto_browser_chaos_last_passed_at=str(raw.get("auto_browser_chaos_last_passed_at", "")),
        media_dir=ROOT_DIR / str(raw["media_dir"]),
        media_storage_root=ROOT_DIR / str(raw.get("media_storage_root", "./studio_data/media")),
        ai_cli_command=str(raw["ai_cli_command"]),
        ai_cli_args=[str(item) for item in ai_args],
        ai_cli_mode=str(raw["ai_cli_mode"]),
        headless=bool(raw["headless"]),
        article_delay_index=int(raw["article_delay_index"]),
        max_teaser_words=int(raw["max_teaser_words"]),
        cleanup_media_after_run=bool(raw["cleanup_media_after_run"]),
        linkedin_wait_after_open_seconds=float(raw["linkedin_wait_after_open_seconds"]),
        content_dir=ROOT_DIR / str(raw.get("content_dir", "./content")),
        substack_import_dir=ROOT_DIR / str(raw.get("substack_import_dir", "./imports/substack")),
        stats_sync_interval_minutes=int(raw.get("stats_sync_interval_minutes", 1440)),
        linkedin_api_enabled=bool(raw.get("linkedin_api_enabled", False)),
        linkedin_api_org_urn=str(raw.get("linkedin_api_org_urn", "")),
        instagram_api_enabled=bool(raw.get("instagram_api_enabled", False)),
        instagram_business_account_id=str(raw.get("instagram_business_account_id", "")),
        substack_import_enabled=bool(raw.get("substack_import_enabled", True)),
        x_api_enabled=bool(raw.get("x_api_enabled", False)),
        x_account_id=str(raw.get("x_account_id", "")),
    )


def ensure_runtime_dirs(config: AppConfig) -> None:
    config.linkedin_user_data_dir.mkdir(parents=True, exist_ok=True)
    config.media_dir.mkdir(parents=True, exist_ok=True)
    config.content_dir.mkdir(parents=True, exist_ok=True)
    config.substack_import_dir.mkdir(parents=True, exist_ok=True)


def ensure_legacy_pipeline_linkedin_allowed(config: AppConfig) -> None:
    configured_provider = str(getattr(config, "linkedin_browser_provider_id", "") or "")
    try:
        from channel_store import get_channel_connection

        connection = get_channel_connection("linkedin")
        if connection is not None and connection.browser_provider_id:
            configured_provider = connection.browser_provider_id
    except Exception:
        configured_provider = str(getattr(config, "linkedin_browser_provider_id", "") or "")
    if configured_provider == "provider.browser.autobrowser":
        raise RuntimeError(
            "The legacy/manual pipeline LinkedIn article or staging flow does not support Auto Browser. "
            "Use the LinkedIn channel runtime for provider-managed operations."
        )


def fetch_article(feed_url: str, delay_index: int) -> Article:
    print(f"Reading RSS feed: {feed_url}")
    response = requests.get(feed_url, timeout=30)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if len(feed.entries) <= delay_index:
        raise RuntimeError(
            f"Not enough feed entries for N-1 selection. Found {len(feed.entries)}, need at least {delay_index + 1}."
        )

    entry = feed.entries[delay_index]
    html = entry.get("content", [{}])[0].get("value") or entry.get("summary", "") or ""
    title = str(entry.get("title", "Untitled"))
    link = str(entry.get("link", ""))
    published_at = None
    published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if published_struct:
        published_at = datetime(*published_struct[:6], tzinfo=UTC).isoformat()
    return Article(title=title, link=link, html=html, text=extract_text(html), published_at=published_at)


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n\n", strip=True)


def text_to_html_paragraphs(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""

    blocks = [block.strip() for block in cleaned.split("\n\n") if block.strip()]
    if not blocks:
        blocks = [cleaned]

    paragraphs: list[str] = []
    for block in blocks:
        escaped = html_escape(block).replace("\n", "<br>")
        paragraphs.append(f"<p>{escaped}</p>")
    return "".join(paragraphs)


def sanitize_substack_article_html(source_html: str) -> str:
    if not source_html.strip():
        return ""

    soup = BeautifulSoup(source_html, "html.parser")
    allowed_tags = {
        "a",
        "blockquote",
        "br",
        "code",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "sub",
        "sup",
        "u",
        "ul",
        "s",
    }
    drop_tags = {
        "audio",
        "button",
        "canvas",
        "figcaption",
        "iframe",
        "noscript",
        "script",
        "source",
        "style",
        "svg",
        "video",
    }

    for tag in list(soup.find_all(True)):
        name = tag.name.lower()
        if name in drop_tags:
            try:
                tag.decompose()
            except ValueError:
                continue
            continue

        if name in {"div", "figure", "section", "article", "main", "header", "footer", "picture"}:
            try:
                tag.unwrap()
            except ValueError:
                continue
            continue

        if name not in allowed_tags:
            try:
                tag.unwrap()
            except ValueError:
                continue
            continue

        if name == "a":
            href = tag.get("href")
            tag.attrs = {}
            if href:
                tag["href"] = href
                tag["target"] = "_blank"
                tag["rel"] = "noreferrer noopener"
            continue

        if name == "img":
            src = tag.get("src") or tag.get("data-src")
            alt = tag.get("alt")
            width = tag.get("width")
            height = tag.get("height")
            tag.attrs = {}
            if src:
                tag["src"] = src
            if alt:
                tag["alt"] = alt
            if width:
                tag["width"] = width
            if height:
                tag["height"] = height
            continue

        if name == "br" or name == "hr":
            tag.attrs = {}
            continue

        tag.attrs = {}

    return soup.decode_contents().strip()


def remove_first_image_from_html(source_html: str) -> str:
    if not source_html.strip():
        return ""

    soup = BeautifulSoup(source_html, "html.parser")
    first_image = soup.find("img")
    if first_image:
        try:
            first_image.decompose()
        except Exception:
            pass
    return str(soup)


def build_linkedin_article_body_html(article_html: str, fallback_text: str, drop_first_image: bool = False) -> str:
    source_html = remove_first_image_from_html(article_html) if drop_first_image else article_html
    sanitized = sanitize_substack_article_html(source_html)
    if sanitized:
        return sanitized
    return text_to_html_paragraphs(fallback_text)


def normalize_page_url(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


def get_or_open_page_for_url(context, target_url: str):
    target_normalized = normalize_page_url(target_url)
    for page in reversed(context.pages):
        try:
            if normalize_page_url(page.url) == target_normalized:
                return page
        except Exception:
            continue

    return context.new_page()


def close_stale_linkedin_article_tabs(context, keep_url: str | None = None) -> int:
    keep_normalized = normalize_page_url(keep_url) if keep_url else None
    closed = 0
    for page in list(context.pages):
        try:
            url = page.url
        except Exception:
            continue
        if "linkedin.com/article/" not in url:
            continue
        if keep_normalized and normalize_page_url(url) == keep_normalized:
            continue
        try:
            page.close(run_before_unload=False)
            closed += 1
        except Exception:
            continue
    return closed


def download_images(html: str, media_dir: Path) -> list[Path]:
    soup = BeautifulSoup(html, "html.parser")
    sources = [image.get("src") or image.get("data-src") for image in soup.find_all("img")]
    return download_images_from_urls([source for source in sources if source], media_dir)


def download_images_from_urls(image_urls: Iterable[str], media_dir: Path, prefix: str = "img") -> list[Path]:
    image_paths: list[Path] = []

    for index, source in enumerate(image_urls):
        extension = Path(urlparse(source).path).suffix.lower().lstrip(".")
        if extension not in {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"}:
            extension = "jpg"

        target_path = media_dir / f"{prefix}_{index}.{extension}"
        try:
            response = requests.get(source, timeout=30, stream=True)
            response.raise_for_status()
            with target_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        handle.write(chunk)
            image_paths.append(target_path)
            print(f"Downloaded image: {target_path.name}")
        except requests.RequestException as exc:
            print(f"Skipping image {source}: {exc}")

    return image_paths


def build_prompt(article: Article, max_words: int) -> str:
    return textwrap.dedent(
        f"""
        You are a sharp, intellectual social media manager.
        Analyze this Substack article and write a raw LinkedIn teaser of max {max_words} words.
        Cut through religious ego and social masks.
        Stop at a high-stakes psychological cliffhanger.
        End with the exact text: 'Lees het volledige essay op Substack: {article.link}'.

        Title:
        {article.title}

        Article text:
        {article.text}
        """
    ).strip()


def build_article_prompt(article: Article, page_name: str, max_words: int = 850) -> str:
    return textwrap.dedent(
        f"""
        You are a sharp, intellectual editorial strategist for the LinkedIn Page "{page_name}".
        Turn the Substack article below into a polished LinkedIn article draft for a company page.
        Keep the voice raw, psychologically deep, and direct.
        Aim for roughly {max_words} words.

        Return exactly this structure:
        TITLE: <one concise, high-impact article title>
        BODY:
        <the full article body>

        Substack title:
        {article.title}

        Substack link:
        {article.link}

        Substack published at:
        {article.published_at or "unknown"}

        Substack text:
        {article.text}
        """
    ).strip()


def format_linkedin_schedule_datetime(publish_time: datetime) -> tuple[str, str]:
    local_time = publish_time.astimezone()
    return local_time.strftime("%m/%d/%Y"), local_time.strftime("%I:%M %p")


def resolve_cli_candidates(command: str) -> list[list[str]]:
    if command and command != "auto":
        return [[command]]
    return [["codex"], ["gemini"], ["gemini-cli"], ["genai-cli"]]


def run_local_ai(prompt: str, config: AppConfig, fallback_link: str) -> str:
    for candidate in resolve_cli_candidates(config.ai_cli_command):
        binary = shutil.which(candidate[0])
        if not binary:
            continue

        command = [binary, *config.ai_cli_args]
        try:
            if config.ai_cli_mode == "argument":
                result = subprocess.run(
                    [*command, prompt],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=60,
                )
            else:
                result = subprocess.run(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=60,
                )
            output = result.stdout.strip()
            if output:
                return output
        except (subprocess.SubprocessError, OSError) as exc:
            print(f"AI CLI attempt failed for {candidate[0]}: {exc}")

    return build_prompt_fallback_teaser(prompt, fallback_link)


def build_prompt_fallback_teaser(prompt: str, fallback_link: str) -> str:
    body = prompt
    if "Substack text:" in prompt:
        body = prompt.split("Substack text:", 1)[1].strip()

    body = re.sub(r"\s+", " ", body).strip()
    if not body:
        body = "Lees het volledige essay op Substack."

    sentence_chunks = re.split(r"(?<=[.!?])\s+", body)
    teaser = " ".join(chunk.strip() for chunk in sentence_chunks[:4] if chunk.strip())
    if not teaser:
        teaser = body[:600]
    teaser = teaser[:900].rsplit(" ", 1)[0] if len(teaser) > 900 else teaser
    closing = f"Lees het volledige essay op Substack: {fallback_link or '(link unavailable)'}"
    if closing.lower() not in teaser.lower():
        teaser = f"{teaser}\n\n{closing}"
    return teaser.strip()


def parse_article_draft(output: str, fallback_title: str, fallback_body: str) -> tuple[str, str]:
    text = output.strip()
    if not text:
        return fallback_title, fallback_body

    title = fallback_title
    body = text

    title_match = re.search(r"^TITLE:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    body_match = re.search(r"^BODY:\s*(.*)$", text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()
    if body_match:
        body = body_match.group(1).strip()
    elif "\n" in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            title = lines[0]
            body = "\n".join(lines[1:]).strip() if len(lines) > 1 else fallback_body

    if not body:
        body = fallback_body
    return title, body


def generate_linkedin_article(article: Article, config: AppConfig) -> tuple[str, str]:
    prompt = build_article_prompt(article, config.linkedin_publish_as_page_name)
    raw_output = run_local_ai(prompt, config, article.link)
    return parse_article_draft(raw_output, fallback_title=article.title, fallback_body=raw_output)


def open_linkedin_post_composer(page) -> None:
    candidates = []
    for pattern in POST_BUTTON_PATTERNS:
        candidates.append(page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first)
    candidates.extend(
        [
            page.locator("button:has-text('Start a post')").first,
            page.locator("button:has-text('Bijdrage starten')").first,
            page.locator("button[aria-label*='Start a post']").first,
            page.locator("button[aria-label*='Bijdrage starten']").first,
            page.locator(".share-box-feed-entry__top-bar button").first,
        ]
    )
    for candidate in candidates:
        try:
            candidate.wait_for(state="visible", timeout=6000)
            candidate.click(timeout=6000)
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    raise RuntimeError("Could not find the LinkedIn post button.")


def open_linkedin_newsletters_entry(page) -> None:
    for pattern in ["Newsletters", "Nieuwsbrieven", "Newsletter", "Articles", "Artikelen", "Page posts", "Paginaposts"]:
        for role in ["link", "button", "tab"]:
            try:
                page.get_by_role(role, name=re.compile(pattern, re.IGNORECASE)).first.click(timeout=3000)
                return
            except Exception:
                pass
    raise RuntimeError("Could not find the LinkedIn Page admin Newsletters/Articles entry.")


def open_linkedin_write_article(page) -> None:
    for pattern in ARTICLE_BUTTON_PATTERNS:
        try:
            page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first.click(timeout=3000)
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    raise RuntimeError("Could not find the LinkedIn write article button.")


def open_linkedin_article_composer(page) -> None:
    for pattern in ARTICLE_BUTTON_PATTERNS:
        try:
            page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first.click(timeout=3000)
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    raise RuntimeError("Could not find the LinkedIn article button.")


def find_composer_editor(dialog):
    candidates = [
        dialog.locator("[contenteditable='true']:visible").first,
        dialog.locator("[role='textbox']:visible").first,
        dialog.get_by_role("textbox").first,
        dialog.locator("textarea:visible").first,
        dialog.locator("textarea").first,
    ]
    for candidate in candidates:
        try:
            candidate.wait_for(state="visible", timeout=6000)
            return candidate
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    raise RuntimeError("Could not find the LinkedIn composer editor.")


def find_article_title_input(page):
    candidates = [
        page.locator("textarea.article-editor-headline__textarea").first,
        page.locator("input[placeholder='Title']").first,
        page.get_by_role("textbox", name=re.compile("Title", re.IGNORECASE)).first,
    ]
    for candidate in candidates:
        try:
            candidate.wait_for(state="visible", timeout=5000)
            return candidate
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    raise RuntimeError("Could not find the LinkedIn article title input.")


def find_article_body_editor(page):
    candidates = [
        page.locator("div[role='textbox'][aria-label='Article editor content']").first,
        page.locator("[contenteditable='true'][aria-label='Article editor content']").first,
        page.get_by_role("textbox").last,
        page.locator("textarea").last,
    ]
    for candidate in candidates:
        try:
            candidate.wait_for(state="visible", timeout=5000)
            return candidate
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    raise RuntimeError("Could not find the LinkedIn article body editor.")


def find_article_teaser_editor(page):
    candidates = [
        page.locator("div[role='textbox'][data-placeholder*='Tell your network']").first,
        page.locator("div[role='textbox'][data-placeholder*='Tell your network what your article is about']").first,
        page.locator("div[role='textbox'][aria-label='Text editor for creating content']").first,
        page.locator("div[role='textbox'][aria-label*='Text editor for creating content']").first,
        page.locator("div[role='textbox'][aria-label*='Tell your network']").first,
        page.locator("[contenteditable='true'][data-placeholder*='Tell your network']").first,
        page.locator(
            "[contenteditable='true'][data-placeholder*='Tell your network what your article is about']"
        ).first,
        page.get_by_role("textbox", name=re.compile("Text editor for creating content", re.IGNORECASE)).first,
        page.get_by_role("textbox", name=re.compile("Tell your network", re.IGNORECASE)).first,
    ]
    for candidate in candidates:
        try:
            candidate.wait_for(state="visible", timeout=5000)
            return candidate
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    raise RuntimeError("Could not find the LinkedIn article teaser editor.")


def find_article_teaser_editor_in_context(context, timeout_seconds: int = 30):
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    selectors = [
        "div[role='textbox'][data-placeholder*='Tell your network']",
        "div[role='textbox'][data-placeholder*='Tell your network what your article is about']",
        "div[role='textbox'][aria-label='Text editor for creating content']",
        "div[role='textbox'][aria-label*='Text editor for creating content']",
        "div[role='textbox'][aria-label*='Tell your network']",
        "[contenteditable='true'][data-placeholder*='Tell your network']",
        "[contenteditable='true'][data-placeholder*='Tell your network what your article is about']",
    ]
    while time.monotonic() < deadline:
        pages = list(reversed(context.pages))
        for page in pages:
            try:
                if "linkedin.com/article/" not in page.url:
                    continue
                for selector in selectors:
                    try:
                        locator = page.locator(selector)
                        if locator.count() == 0:
                            continue
                        candidate = locator.first
                        if candidate.is_visible():
                            return page, candidate
                    except Exception as exc:
                        last_error = exc
                        continue
            except Exception as exc:
                last_error = exc
                continue
        try:
            if pages:
                pages[0].wait_for_timeout(500)
            else:
                time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(
        f"Could not find the LinkedIn article teaser editor after {timeout_seconds}s."
        + (f" Last error: {last_error}" if last_error else "")
    )


def fill_textbox_like(page, locator, text: str) -> None:
    cleaned = text.strip()
    try:
        locator.evaluate(
            """
            (el, value) => {
                el.focus();
                if ("value" in el) {
                    el.value = value;
                } else {
                    el.textContent = value;
                }
                el.dispatchEvent(new InputEvent("input", {
                    bubbles: true,
                    cancelable: true,
                    inputType: "insertText",
                    data: value,
                }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                el.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "Enter" }));
            }
            """,
            cleaned,
        )
        page.wait_for_timeout(500)
        current = ""
        try:
            current = locator.input_value().strip()
        except Exception:
            try:
                current = locator.inner_text().strip()
            except Exception:
                current = ""
        if not current or cleaned not in current:
            raise RuntimeError("Direct textbox write did not stick.")
        return
    except Exception:
        pass

    locator.click()
    try:
        locator.press("Control+A")
    except Exception:
        try:
            locator.press("Meta+A")
        except Exception:
            pass
    page.keyboard.insert_text(text)


def type_into_contenteditable(page, locator, text: str) -> None:
    cleaned = text.strip()
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass

    try:
        locator.click(force=True)
    except Exception:
        pass

    try:
        blocks = [block.strip() for block in cleaned.split("\n\n") if block.strip()]
        if not blocks:
            blocks = [cleaned]
        locator.evaluate(
            """
            (el, blocks) => {
                el.focus();
                el.innerHTML = "";
                for (const block of blocks) {
                    const p = document.createElement("p");
                    if (block) {
                        p.textContent = block;
                    } else {
                        p.innerHTML = "<br>";
                    }
                    el.appendChild(p);
                }
                el.dispatchEvent(new InputEvent("input", {
                    bubbles: true,
                    cancelable: true,
                    inputType: "insertText",
                    data: blocks.join("\\n\\n"),
                }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
            }
            """,
            blocks,
        )
        page.wait_for_timeout(500)
        rendered = locator.inner_text().strip()
        if cleaned and cleaned[: min(len(cleaned), 40)] not in rendered:
            raise RuntimeError("Direct rich-text write did not stick.")
        return
    except Exception:
        pass

    try:
        locator.click(force=True)
    except Exception:
        pass
    try:
        page.keyboard.press("Control+A")
    except Exception:
        try:
            page.keyboard.press("Meta+A")
        except Exception:
            pass
    page.keyboard.insert_text(text)


def set_contenteditable_html(page, locator, html_content: str, fallback_text: str = "") -> None:
    cleaned_html = html_content.strip()
    if not cleaned_html and fallback_text.strip():
        cleaned_html = text_to_html_paragraphs(fallback_text)

    try:
        locator.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass

    try:
        locator.click(force=True)
    except Exception:
        pass

    if cleaned_html:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                locator.evaluate(
                    """
                    (el, html) => {
                        el.focus();
                        const selection = window.getSelection();
                        const range = document.createRange();
                        range.selectNodeContents(el);
                        range.collapse(false);
                        selection.removeAllRanges();
                        selection.addRange(range);
                        document.execCommand("selectAll", false, null);
                        document.execCommand("insertHTML", false, html);
                        el.dispatchEvent(new InputEvent("input", {
                            bubbles: true,
                            cancelable: true,
                            inputType: "insertFromPaste",
                            data: html,
                        }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                        el.blur();
                    }
                    """,
                    cleaned_html,
                )
                page.wait_for_timeout(750 + (attempt * 250))
                rendered = locator.inner_text().strip()
                rendered_html = locator.evaluate("(el) => el.innerHTML")
                if rendered and "<p" in str(rendered_html).lower():
                    return
            except Exception as exc:
                last_error = exc
                page.wait_for_timeout(500)
                continue

        raise RuntimeError(
            "Could not reliably persist rich HTML in the LinkedIn article editor."
            + (f" Last error: {last_error}" if last_error else "")
        )

    if fallback_text.strip():
        type_into_contenteditable(page, locator, fallback_text)


def wait_for_enabled(locator, description: str, timeout_seconds: int = 30) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if locator.count() and locator.is_visible() and locator.is_enabled():
                print(f"LinkedIn {description} is enabled.")
                return True
        except Exception:
            pass
        time.sleep(0.5)
    print(f"LinkedIn {description} was still not enabled after waiting; continuing carefully.")
    return False


def dismiss_linkedin_cookie_banner(page) -> bool:
    candidates = [
        page.get_by_role("button", name=re.compile("^Accept$", re.IGNORECASE)).first,
        page.locator("button:has-text('Accept')").first,
        page.locator("button[action-type='ACCEPT']").first,
    ]
    for candidate in candidates:
        try:
            if not candidate.count():
                continue
            if not candidate.is_visible():
                continue
            try:
                candidate.click(timeout=3000, force=True)
            except Exception:
                candidate.evaluate("(el) => el.click()")
            page.wait_for_timeout(1000)
            print("LinkedIn cookie banner dismissed.")
            return True
        except Exception:
            continue
    return False


def dismiss_linkedin_article_saving_warning(page) -> bool:
    warning = page.get_by_text(re.compile(r"article is still saving", re.IGNORECASE)).first
    try:
        if not warning.count() or not warning.is_visible():
            return False
    except Exception:
        return False

    dismiss_candidates = [
        page.locator("button:has-text('Dismiss')").first,
        page.locator("button[aria-label='Dismiss']").first,
    ]
    for candidate in dismiss_candidates:
        try:
            if not candidate.count() or not candidate.is_visible():
                continue
            try:
                candidate.click(timeout=5000, force=True)
            except Exception:
                candidate.evaluate("(el) => el.click()")
            page.wait_for_timeout(1500)
            print("LinkedIn article saving warning dismissed.")
            return True
        except Exception:
            continue
    return False


def linkedin_article_schedule_dialog_visible(page) -> bool:
    try:
        date_visible = page.locator("input[aria-label='Date']").first.is_visible(timeout=1000)
        time_visible = page.locator("input[aria-label='Time']").first.is_visible(timeout=1000)
        return bool(date_visible and time_visible)
    except Exception:
        return False


def dismiss_linkedin_discard_dialog(page) -> bool:
    overlay = page.locator("div[data-test-modal-id='discard-draft-dialog']").first
    try:
        if not overlay.count():
            return False
        if not overlay.is_visible():
            return False
    except Exception:
        return False

    print("LinkedIn discard draft dialog detected; dismissing it before continuing.")
    dismiss_candidates = [
        overlay.get_by_role("button", name=re.compile("^Go back$", re.IGNORECASE)).first,
        overlay.locator("button:has-text('Go back')").first,
        overlay.get_by_role("button", name=re.compile("^Dismiss$", re.IGNORECASE)).first,
        overlay.locator("button[aria-label='Dismiss']").first,
    ]
    for candidate in dismiss_candidates:
        try:
            wait_for_enabled(candidate, "discard draft dialog button", timeout_seconds=10)
            try:
                candidate.click(timeout=5000, force=True)
                page.wait_for_timeout(1500)
                print("LinkedIn discard draft dialog dismissed with native click.")
                return True
            except Exception as exc:
                print(f"LinkedIn discard dialog native click failed: {exc}")
                candidate.evaluate("(el) => el.click()")
                page.wait_for_timeout(1500)
                print("LinkedIn discard draft dialog dismissed with DOM click.")
                return True
        except Exception:
            continue
    raise RuntimeError("Could not dismiss the LinkedIn discard draft dialog.")


def click_linkedin_button_with_retry(
    page, candidates, description: str, timeout_seconds: int = 30, retries: int = 3
) -> bool:
    dismiss_linkedin_cookie_banner(page)
    dismiss_linkedin_article_saving_warning(page)
    dismiss_linkedin_discard_dialog(page)
    for candidate in candidates:
        try:
            for attempt in range(1, retries + 1):
                print(f"Waiting for LinkedIn {description} to unlock (attempt {attempt}/{retries})...")
                wait_for_enabled(candidate, description, timeout_seconds=timeout_seconds)
                try:
                    candidate.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                try:
                    candidate.click(timeout=7000, force=True)
                    print(f"Clicked LinkedIn {description}.")
                    page.wait_for_timeout(2000)
                    return True
                except Exception as exc:
                    print(f"LinkedIn {description} native click failed on attempt {attempt}: {exc}")
                    try:
                        candidate.evaluate("(el) => el.click()")
                        print(f"Clicked LinkedIn {description} via DOM click.")
                        page.wait_for_timeout(2000)
                        return True
                    except Exception as dom_exc:
                        print(f"LinkedIn {description} DOM click failed on attempt {attempt}: {dom_exc}")
                        page.wait_for_timeout(1500)
                dismiss_linkedin_cookie_banner(page)
                dismiss_linkedin_article_saving_warning(page)
                dismiss_linkedin_discard_dialog(page)
        except Exception:
            continue
    return False


def select_publish_as_page(page, page_name: str) -> None:
    if not page_name:
        return

    page_pattern = re.compile(re.escape(page_name), re.IGNORECASE)
    current_title_candidates = [
        page.locator(".article-editor-actor-toggle__author-lockup-title").first,
        page.locator(".artdeco-entity-lockup__title").first,
    ]
    for candidate in current_title_candidates:
        try:
            if candidate.count() and candidate.is_visible():
                current_title = candidate.inner_text().strip()
                if page_pattern.search(current_title):
                    print(f"Publish-as page already selected: {current_title}")
                    return
        except Exception:
            continue

    trigger_candidates = [
        page.locator(".article-editor-actor-toggle__dropdown .artdeco-dropdown__trigger").first,
        page.get_by_role("button", name=re.compile("Publish as", re.IGNORECASE)).first,
        page.get_by_role("button", name=page_pattern).first,
        page.locator("button:has-text('Individual article')").first,
        page.locator("button:has-text('Al-Batin')").first,
    ]
    opened = False
    for candidate in trigger_candidates:
        try:
            if not candidate.count() or not candidate.is_visible():
                continue
            candidate.click(timeout=3000, force=True)
            page.wait_for_timeout(1000)
            dropdown = page.locator(".article-editor-actor-toggle__dropdown .artdeco-dropdown__content").first
            if dropdown.count() and dropdown.is_visible():
                opened = True
                break
        except Exception:
            continue

    if not opened:
        print(f"Could not open Publish as selector for {page_name}; continuing with current identity.")
        return

    radio_candidates = [
        page.locator(".article-editor-entity-selector__title--group button[role='radio']")
        .filter(has_text=page_pattern)
        .first,
        page.locator(".article-editor-actor-toggle__dropdown button[role='radio']").filter(has_text=page_pattern).first,
        page.get_by_role("radio", name=page_pattern).first,
    ]
    for candidate in radio_candidates:
        try:
            if not candidate.count() or not candidate.is_visible():
                continue
            checked = candidate.get_attribute("aria-checked")
            if checked == "true":
                print(f"Publish-as page confirmed: {page_name}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                return
            candidate.click(timeout=3000, force=True)
            page.wait_for_timeout(1000)
            checked = candidate.get_attribute("aria-checked")
            if checked == "true":
                print(f"Publish-as page selected: {page_name}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                return
        except Exception:
            continue

    print(f"Could not confirm publish-as page selection for {page_name}; continuing with current identity.")


def upload_article_cover_image(page, image_path: Path | None) -> bool:
    if image_path is None:
        return False

    def click_cover_next() -> None:
        next_candidates = [
            page.locator("div[role='dialog'] button:has-text('Next')").first,
            page.locator("div[role='dialog'] button[aria-label='Next']").first,
            page.get_by_role("button", name=re.compile("^Next$", re.IGNORECASE)).first,
        ]
        for candidate in next_candidates:
            try:
                wait_for_enabled(candidate, "cover dialog Next button", timeout_seconds=30)
                try:
                    candidate.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                try:
                    candidate.click(timeout=7000, force=True)
                except Exception:
                    candidate.evaluate("(el) => el.click()")
                page.wait_for_timeout(2000)
                return True
            except Exception:
                continue

    try:
        upload_button = page.locator(
            "button[aria-label='Upload from computer'], div.media-editor-file-selector__upload-media-button"
        ).first
        upload_button.wait_for(state="visible", timeout=10000)
        try:
            upload_button.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        with page.expect_file_chooser(timeout=10000) as chooser_info:
            upload_button.click(timeout=7000, force=True)
        chooser = chooser_info.value
        chooser.set_files(str(image_path))
        page.wait_for_timeout(2000)
        print("Article cover image selected via file chooser.")
        click_cover_next()
        return True
    except Exception as exc:
        print(f"Direct cover upload via file chooser failed: {exc}")
    try:
        for locator in [
            page.locator("div[role='dialog'] input[type='file']").first,
            page.locator("input#media-editor-file-selector__file-input").first,
            page.locator("input[type='file']").first,
        ]:
            if locator.count():
                locator.set_input_files(str(image_path))
                page.wait_for_timeout(2000)
                print("Article cover image uploaded via file input fallback.")
                click_cover_next()
                return True
    except Exception as exc:
        print(f"Fallback cover upload via file input failed: {exc}")
    print("Skipping article cover upload because no stable file input was available.")
    return False


def remove_first_inline_article_image(page) -> bool:
    try:
        body_editor = find_article_body_editor(page)
        removed = body_editor.evaluate(
            """
            (el) => {
                const container =
                    el.querySelector('.article-editor-inline-image__container') ||
                    el.querySelector('img')?.closest('.article-editor-inline-image__container') ||
                    el.querySelector('img');
                if (!container) return false;
                container.remove();
                el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward', data: null }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.blur();
                return true;
            }
            """
        )
        page.wait_for_timeout(1500)
        remaining_images = body_editor.evaluate("(el) => el.querySelectorAll('img').length")
        if removed and int(remaining_images) == 0:
            print("Removed the first inline article image from the editor.")
            return True
    except Exception as exc:
        print(f"Inline article image DOM removal failed: {exc}")

    delete_button = page.locator("button[aria-label='Delete image']").first
    try:
        if not delete_button.count():
            return False
        wait_for_enabled(delete_button, "inline article image delete button", timeout_seconds=10)
        try:
            delete_button.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        try:
            delete_button.click(timeout=5000, force=True)
        except Exception:
            delete_button.evaluate("(el) => el.click()")
        page.wait_for_timeout(1500)
        body_editor = find_article_body_editor(page)
        remaining_images = body_editor.evaluate("(el) => el.querySelectorAll('img').length")
        if int(remaining_images) == 0:
            print("Removed the first inline article image from the editor.")
            return True
        print("Inline article image delete button ran, but an image is still present.")
        return False
    except Exception as exc:
        print(f"Could not remove the inline article image from the editor: {exc}")
        return False


def schedule_linkedin_article_post(page, publish_time: datetime, teaser: str = "") -> None:
    date_str, time_str = format_linkedin_schedule_datetime(publish_time)
    print(f"Scheduling LinkedIn article post for {date_str} {time_str}.")
    dismiss_linkedin_cookie_banner(page)
    dismiss_linkedin_discard_dialog(page)

    def click_when_ready(candidates: list, description: str, timeout_seconds: int = 30) -> bool:
        dismiss_linkedin_cookie_banner(page)
        dismiss_linkedin_discard_dialog(page)
        for candidate in candidates:
            try:
                wait_for_enabled(candidate, description, timeout_seconds=timeout_seconds)
                try:
                    candidate.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                try:
                    candidate.click(timeout=5000)
                    print(f"Clicked LinkedIn {description}.")
                    page.wait_for_timeout(1500)
                    return True
                except Exception as exc:
                    print(f"LinkedIn {description} native click failed: {exc}")
                    try:
                        candidate.evaluate("(el) => el.click()")
                        print(f"Clicked LinkedIn {description} via DOM click.")
                        page.wait_for_timeout(1500)
                        return True
                    except Exception as dom_exc:
                        print(f"LinkedIn {description} DOM click failed: {dom_exc}")
                        dismiss_linkedin_cookie_banner(page)
                        continue
            except Exception:
                continue
        return False

    def click_article_next() -> bool:
        next_candidates = [
            page.locator("button:has-text('Next')").first,
            page.get_by_role("button", name=re.compile("^Next$", re.IGNORECASE)).first,
            page.locator("button[aria-label='Next']").first,
            page.locator("button:has-text('Individual article')").first,
            page.locator("button:has-text('Al-Batin')").first,
        ]
        return click_when_ready(next_candidates, "article launch button", timeout_seconds=45)

    def click_schedule_post() -> bool:
        schedule_candidates = [
            page.locator("button[aria-label='Schedule post']").first,
            page.get_by_role("button", name=re.compile("^Schedule post$", re.IGNORECASE)).first,
            page.locator("button:has-text('Schedule post')").first,
        ]
        return click_when_ready(schedule_candidates, "Schedule post button", timeout_seconds=30)

    if not linkedin_article_schedule_dialog_visible(page):
        if not click_schedule_post():
            if not click_article_next():
                raise RuntimeError("Could not reach the LinkedIn scheduling UI.")
            page.wait_for_timeout(1500)
            dismiss_linkedin_cookie_banner(page)
            dismiss_linkedin_article_saving_warning(page)
            dismiss_linkedin_discard_dialog(page)
            if not linkedin_article_schedule_dialog_visible(page) and not click_schedule_post():
                raise RuntimeError("Could not open the LinkedIn schedule dialog.")
    dismiss_linkedin_discard_dialog(page)
    page.wait_for_timeout(1000)

    date_input = page.locator("input[aria-label='Date']").first
    time_input = page.locator("input[aria-label='Time']").first
    date_input.wait_for(state="visible", timeout=5000)
    time_input.wait_for(state="visible", timeout=5000)
    date_input.fill(date_str)
    time_input.fill(time_str)
    # LinkedIn keeps the date/time picker "active" after fills. Blur both fields
    # and click the dialog shell so the values are actually committed before Next.
    try:
        date_input.evaluate(
            """
            (el) => {
                el.blur();
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
            }
            """
        )
    except Exception:
        pass
    try:
        time_input.evaluate(
            """
            (el) => {
                el.blur();
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
            }
            """
        )
    except Exception:
        pass
    try:
        page.locator("div[role='dialog']").first.evaluate("(el) => el.click()")
    except Exception:
        pass
    page.wait_for_timeout(3000)

    dialog_next_candidates = [
        page.locator("div[role='dialog'] button:has-text('Next')").first,
        page.locator("div[role='dialog'] button[aria-label='Next']").first,
        page.get_by_role("button", name=re.compile("^Next$", re.IGNORECASE)).first,
    ]
    dialog_next_clicked = False
    for candidate in dialog_next_candidates:
        try:
            dismiss_linkedin_cookie_banner(page)
            dismiss_linkedin_discard_dialog(page)
            for attempt in range(3):
                print(f"Waiting for LinkedIn schedule dialog Next to unlock (attempt {attempt + 1}/3)...")
                wait_for_enabled(candidate, "schedule dialog Next button", timeout_seconds=20)
                try:
                    candidate.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                try:
                    candidate.click(timeout=7000, force=True)
                    print("Clicked LinkedIn schedule dialog Next.")
                    page.wait_for_timeout(2000)
                    dialog_next_clicked = True
                    break
                except Exception as exc:
                    print(f"LinkedIn schedule dialog Next click failed on attempt {attempt + 1}: {exc}")
                    try:
                        candidate.evaluate("(el) => el.click()")
                        print("Clicked LinkedIn schedule dialog Next via DOM click.")
                        page.wait_for_timeout(2000)
                        dialog_next_clicked = True
                        break
                    except Exception as dom_exc:
                        print(f"LinkedIn schedule dialog Next DOM click failed on attempt {attempt + 1}: {dom_exc}")
                    page.wait_for_timeout(1500)
            if dialog_next_clicked:
                break
        except Exception:
            continue
    if not dialog_next_clicked:
        raise RuntimeError("Could not advance LinkedIn schedule dialog after entering date and time.")
    try:
        page.locator("div[role='dialog']").first.wait_for(state="visible", timeout=10000)
        page.wait_for_timeout(1500)
    except Exception:
        pass

    if teaser.strip():
        try:
            teaser_editor = find_article_teaser_editor(page)
            type_into_contenteditable(page, teaser_editor, teaser)
            rendered_teaser = teaser_editor.inner_text().strip()
            print(
                f"Tell your network teaser inserted in final schedule modal ({len(rendered_teaser)} chars visible in editor)."
            )
        except Exception as exc:
            print(f"Could not fill the Tell your network teaser in the final schedule modal automatically: {exc}")

    final_schedule_candidates = [
        page.locator("div[role='dialog'] button.share-actions__primary-action").first,
        page.locator("div[role='dialog'] button[aria-label='Schedule']").first,
        page.locator("div[role='dialog'] button").filter(has_text=re.compile(r"^Schedule$", re.IGNORECASE)).first,
        page.locator("div[role='dialog'] button:has-text('Schedule')").first,
    ]
    final_clicked = False
    for candidate in final_schedule_candidates:
        try:
            dismiss_linkedin_discard_dialog(page)
            print("Waiting for LinkedIn final Schedule button to unlock...")
            wait_for_enabled(candidate, "final Schedule button", timeout_seconds=30)
            try:
                candidate.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            try:
                candidate.click(timeout=7000, force=True)
                print("Clicked LinkedIn final Schedule button.")
                page.wait_for_timeout(2000)
                final_clicked = True
                break
            except Exception as exc:
                print(f"LinkedIn final Schedule native click failed: {exc}")
                candidate.evaluate("(el) => el.click()")
                print("Clicked LinkedIn final Schedule button via DOM click.")
                page.wait_for_timeout(2000)
                final_clicked = True
                break
        except Exception:
            continue
    if not final_clicked:
        raise RuntimeError("Could not click the final LinkedIn Schedule button.")

    confirmation = page.get_by_text(re.compile("article post has been scheduled", re.IGNORECASE))
    try:
        confirmation.wait_for(state="visible", timeout=5000)
    except Exception:
        pass
    return


def publish_linkedin_article_post(page) -> None:
    print("Clicking LinkedIn Publish...")
    publish_button_candidates = [
        page.locator("button[aria-label='Publish']").first,
        page.get_by_role("button", name=re.compile("^Publish$", re.IGNORECASE)).first,
        page.locator("button:has-text('Publish')").first,
    ]
    opened = False
    for candidate in publish_button_candidates:
        try:
            candidate.click(timeout=5000)
            opened = True
            break
        except Exception:
            continue
    if not opened:
        raise RuntimeError("Could not open the LinkedIn publish action.")

    page.wait_for_timeout(2000)
    confirmation = page.get_by_text(re.compile(r"published|your article has been published", re.IGNORECASE))
    try:
        confirmation.wait_for(state="visible", timeout=5000)
    except Exception:
        pass


def attach_images(dialog, image_paths: Iterable[Path]) -> None:
    images = [str(path) for path in image_paths]
    if not images:
        return

    file_inputs = dialog.locator("input[type='file']")
    if file_inputs.count():
        file_inputs.first.set_input_files(images)
        return

    for pattern in ["Add media", "Voeg media toe", "Media toevoegen", "Documenten toevoegen"]:
        try:
            dialog.get_by_role("button", name=re.compile(pattern, re.IGNORECASE)).first.click(timeout=3000)
            dialog.locator("input[type='file']").first.set_input_files(images)
            return
        except Exception:
            continue

    print("LinkedIn media input not found; continuing without upload.")


def open_linkedin_session(config: AppConfig):
    print("Opening LinkedIn browser session...")
    playwright = sync_playwright().start()

    if config.linkedin_remote_debugging_url:
        try:
            browser = playwright.chromium.connect_over_cdp(config.linkedin_remote_debugging_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            return playwright, browser, context, page, False, "remote debugging session"
        except Exception as exc:
            print(f"Could not attach to remote debugging browser: {exc}. Falling back to the persistent profile.")

    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(config.linkedin_user_data_dir),
        headless=config.headless,
        viewport={"width": 1440, "height": 1200},
    )
    page = context.pages[0] if context.pages else context.new_page()
    return playwright, None, context, page, True, "persistent profile"


def stage_linkedin_post_impl(config: AppConfig, teaser: str, image_paths: list[Path], interactive: bool = True) -> None:
    ensure_legacy_pipeline_linkedin_allowed(config)
    playwright, browser, context, page, owns_session, session_label = open_linkedin_session(config)
    try:
        print(f"Using {session_label}.")

        page = get_or_open_page_for_url(context, config.linkedin_feed_url)
        page.goto(config.linkedin_feed_url, wait_until="domcontentloaded")
        page.bring_to_front()
        page.wait_for_timeout(int(config.linkedin_wait_after_open_seconds * 1000))
        open_linkedin_post_composer(page)

        dialog = page.get_by_role("dialog").first
        dialog.wait_for(state="visible", timeout=10000)

        editor = find_composer_editor(dialog)
        try:
            editor.fill(teaser)
        except Exception:
            editor.click()
            page.keyboard.insert_text(teaser)

        attach_images(dialog, image_paths)

        if interactive:
            print("\nPost staged in LinkedIn. Review it in the browser, then press Enter to close the session.")
            input()
        else:
            print("\nPost staged in LinkedIn. Closing shortly so LinkedIn can auto-save the draft.")
            page.wait_for_timeout(7000)
    finally:
        if owns_session:
            context.close()
        playwright.stop()


def stage_linkedin_article_impl(
    config: AppConfig,
    teaser: str,
    title: str,
    body_html: str,
    body_text: str,
    article_published_at: str | None,
    image_paths: list[Path],
    interactive: bool = True,
    body_only: bool = False,
) -> None:
    ensure_legacy_pipeline_linkedin_allowed(config)
    playwright, browser, context, page, owns_session, session_label = open_linkedin_session(config)
    close_article_tab_on_exit = False
    try:
        print(f"Using {session_label}.")

        article_entry_url = config.linkedin_article_new_url or config.linkedin_company_admin_url
        print(f"Opening article editor entry: {article_entry_url}")
        try:
            closed_count = close_stale_linkedin_article_tabs(context, keep_url=article_entry_url)
            if closed_count:
                print(f"Closed {closed_count} stale LinkedIn article tab(s).")
            page = get_or_open_page_for_url(context, article_entry_url)
            page.goto(article_entry_url, wait_until="domcontentloaded")
            page.bring_to_front()
            dismiss_linkedin_cookie_banner(page)
            page.wait_for_timeout(int(config.linkedin_wait_after_open_seconds * 1000))
            try:
                page.wait_for_load_state("domcontentloaded")
            except Exception:
                pass
            page.wait_for_timeout(1500)
        except Exception as exc:
            print(f"Direct article URL failed: {exc}. Falling back to admin route.")
            page.goto(config.linkedin_company_admin_url, wait_until="domcontentloaded")
            dismiss_linkedin_cookie_banner(page)
            page.wait_for_timeout(int(config.linkedin_wait_after_open_seconds * 1000))

        print("Waiting for article editor shell to settle...")
        page.wait_for_timeout(3000)
        dismiss_linkedin_cookie_banner(page)

        print(f"Selecting publish-as page: {config.linkedin_publish_as_page_name}")
        select_publish_as_page(page, config.linkedin_publish_as_page_name)

        try:
            print("Filling article title...")
            title_input = find_article_title_input(page)
            fill_textbox_like(page, title_input, title)
            try:
                saved_title = title_input.input_value().strip()
                print(f"Article title inserted ({len(saved_title)} chars in input).")
            except Exception:
                pass
        except Exception as exc:
            print(f"Could not fill article title automatically: {exc}")

        try:
            print("Filling article body from original Substack HTML...")
            body_editor = find_article_body_editor(page)
            sanitized_body_html = build_linkedin_article_body_html(
                body_html,
                body_text,
                drop_first_image=False,
            )
            set_contenteditable_html(page, body_editor, sanitized_body_html, fallback_text=body_text)
            try:
                rendered_body = body_editor.inner_text().strip()
                print(f"Article body inserted ({len(rendered_body)} chars visible in editor).")
                try:
                    rendered_html = body_editor.evaluate("(el) => el.innerHTML")
                    if "<img" in str(rendered_html).lower():
                        print("Article body includes embedded image markup.")
                    print(f"Article body HTML length: {len(str(rendered_html))} characters.")
                except Exception:
                    pass
            except Exception:
                pass
            page.wait_for_timeout(2500)
        except Exception as exc:
            print(f"Could not fill article body automatically: {exc}")

        if config.linkedin_article_use_cover_image and image_paths:
            print("Uploading article cover image...")
            cover_uploaded = upload_article_cover_image(page, image_paths[0])
            page.wait_for_timeout(1500)
            if cover_uploaded:
                try:
                    print("Removing the first article image from the body because the cover upload succeeded...")
                    removed_inline_image = remove_first_inline_article_image(page)
                    if not removed_inline_image:
                        body_editor = find_article_body_editor(page)
                        sanitized_body_html = build_linkedin_article_body_html(
                            body_html,
                            body_text,
                            drop_first_image=True,
                        )
                        set_contenteditable_html(page, body_editor, sanitized_body_html, fallback_text=body_text)
                        page.wait_for_timeout(1500)
                except Exception as exc:
                    print(f"Could not trim the inline cover image from the body: {exc}")
        elif image_paths:
            print("Skipping article cover image upload (disabled in config).")

        dismiss_linkedin_article_saving_warning(page)

        if body_only:
            print("Body-only mode enabled; stopping before teaser and scheduling.")
            if interactive:
                print(
                    "\nLinkedIn article body staged. Review it in the browser, then press Enter to close the session."
                )
                input()
            else:
                page.wait_for_timeout(7000)
            return

        try:
            print("Advancing to the Tell your network screen...")
            for attempt in range(1, 4):
                dismiss_linkedin_cookie_banner(page)
                dismissed_warning = dismiss_linkedin_article_saving_warning(page)
                dismiss_linkedin_discard_dialog(page)
                if dismissed_warning:
                    print(f"LinkedIn article saving warning cleared before launch attempt {attempt}.")
                    page.wait_for_timeout(1000)
                if linkedin_article_schedule_dialog_visible(page):
                    print("LinkedIn schedule dialog is already visible; skipping article launch click.")
                    break
                if attempt > 1:
                    print(f"Retrying article launch after clearing transient editor state (attempt {attempt}/3)...")
            next_candidates = [
                page.locator("button:has-text('Next')").first,
                page.get_by_role("button", name=re.compile("^Next$", re.IGNORECASE)).first,
                page.locator("button[aria-label='Next']").first,
                page.locator("button:has-text('Individual article')").first,
                page.locator("button:has-text('Al-Batin')").first,
            ]
            if not linkedin_article_schedule_dialog_visible(page) and not click_linkedin_button_with_retry(
                page, next_candidates, "article launch button", timeout_seconds=20, retries=3
            ):
                raise RuntimeError("Could not click the LinkedIn article launch button.")
            dismiss_linkedin_article_saving_warning(page)
        except Exception as exc:
            print(f"Could not advance to the next screen automatically: {exc}")

        try:
            print("Filling the Tell your network teaser...")
            teaser_page, teaser_editor = find_article_teaser_editor_in_context(context, timeout_seconds=30)
            teaser_page.bring_to_front()
            type_into_contenteditable(teaser_page, teaser_editor, teaser)
            try:
                rendered_teaser = teaser_editor.inner_text().strip()
                print(f"Tell your network teaser inserted ({len(rendered_teaser)} chars visible in editor).")
            except Exception:
                pass
        except Exception as exc:
            print(f"Could not fill the Tell your network teaser automatically: {exc}")

        page.wait_for_timeout(1500)

        try:
            publish_time = compute_article_schedule_time(
                config.linkedin_article_schedule_buffer_minutes,
            )
            schedule_linkedin_article_post(page, publish_time, teaser=teaser)
            if not interactive and not body_only:
                close_article_tab_on_exit = True
        except Exception as exc:
            print(f"Could not schedule LinkedIn article automatically: {exc}")

        print("Article fields filled.")

        if interactive:
            print("\nLinkedIn article draft staged. Review it in the browser, then press Enter to close the session.")
            input()
        else:
            print("\nLinkedIn article draft staged. Exiting cleanly and closing the article tab.")
            return
    finally:
        if close_article_tab_on_exit and not owns_session:
            try:
                if "linkedin.com/article/" in page.url:
                    page.close(run_before_unload=False)
                    print("Closed the LinkedIn article tab after scheduling.")
            except Exception as exc:
                print(f"Could not close the LinkedIn article tab automatically: {exc}")
        if owns_session:
            context.close()
        playwright.stop()


def stage_linkedin_post(
    config: AppConfig,
    teaser: str,
    image_paths: list[Path],
    interactive: bool = True,
    article_title: str | None = None,
    article_link: str | None = None,
    article_html: str | None = None,
    article_text: str | None = None,
    article_published_at: str | None = None,
    content_type: str | None = None,
    body_only: bool = False,
) -> None:
    mode = (content_type or config.linkedin_content_mode).lower()
    if mode == "article":
        source_article = Article(
            title=article_title or "LinkedIn article draft",
            link=article_link or "",
            html=article_html or "",
            text=article_text or teaser,
        )
        stage_linkedin_article_impl(
            config,
            teaser,
            source_article.title,
            source_article.html,
            source_article.text,
            article_published_at,
            image_paths,
            interactive=interactive,
            body_only=body_only,
        )
        return

    stage_linkedin_post_impl(config, teaser, image_paths, interactive=interactive)


def open_linkedin_feed(config: AppConfig) -> None:
    ensure_legacy_pipeline_linkedin_allowed(config)
    playwright, browser, context, page, owns_session, session_label = open_linkedin_session(config)
    try:
        print(f"Using {session_label}.")
        page = get_or_open_page_for_url(context, config.linkedin_feed_url)
        page.goto(config.linkedin_feed_url, wait_until="domcontentloaded")
        page.bring_to_front()
        page.wait_for_timeout(int(config.linkedin_wait_after_open_seconds * 1000))
        print("LinkedIn feed is open. You can log in or continue from here.")
        if not config.linkedin_remote_debugging_url:
            print(
                "This opened in the local persistent profile. If you want to use the dashboard browser, set linkedin_remote_debugging_url."
            )
    finally:
        if owns_session:
            context.close()
        playwright.stop()


def open_linkedin_article_editor(config: AppConfig) -> None:
    ensure_legacy_pipeline_linkedin_allowed(config)
    playwright, browser, context, page, owns_session, session_label = open_linkedin_session(config)
    try:
        print(f"Using {session_label}.")
        article_entry_url = config.linkedin_article_new_url or config.linkedin_company_admin_url
        print(f"Opening article editor: {article_entry_url}")
        closed_count = close_stale_linkedin_article_tabs(context, keep_url=article_entry_url)
        if closed_count:
            print(f"Closed {closed_count} stale LinkedIn article tab(s).")
        page = get_or_open_page_for_url(context, article_entry_url)
        page.goto(article_entry_url, wait_until="domcontentloaded")
        page.bring_to_front()
        page.wait_for_timeout(int(config.linkedin_wait_after_open_seconds * 1000))
        try:
            page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
        print("Article editor opened.")
        if not config.linkedin_remote_debugging_url:
            print(
                "This opened in the local persistent profile. If you want to use the dashboard browser, set linkedin_remote_debugging_url."
            )
    finally:
        if owns_session:
            context.close()
        playwright.stop()


def cleanup_media(media_dir: Path, enabled: bool) -> None:
    if enabled and media_dir.exists():
        shutil.rmtree(media_dir, ignore_errors=True)


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if args.no_cleanup:
        config.cleanup_media_after_run = False

    ensure_runtime_dirs(config)

    try:
        article = fetch_article(config.rss_url, config.article_delay_index)
        image_paths = download_images(article.html, config.media_dir)
        prompt = build_prompt(article, config.max_teaser_words)
        teaser = run_local_ai(prompt, config, article.link)

        print("\nSelected article:")
        print(f"- Title: {article.title}")
        print(f"- Link: {article.link}")
        print(f"- Images: {len(image_paths)}")
        print("\nGenerated teaser:\n")
        print(teaser)

        if args.dry_run:
            return 0

        if args.open_linkedin:
            open_linkedin_feed(config)
            return 0

        if args.open_article_editor:
            open_linkedin_article_editor(config)
            return 0

        if args.article_body_only:
            stage_linkedin_post(
                config,
                teaser,
                image_paths,
                interactive=not args.save_draft,
                article_title=article.title,
                article_link=article.link,
                article_html=article.html,
                article_text=article.text,
                article_published_at=article.published_at,
                content_type="article",
                body_only=True,
            )
            cleanup_media(config.media_dir, config.cleanup_media_after_run)
            return 0

        stage_linkedin_post(
            config,
            teaser,
            image_paths,
            interactive=not args.save_draft,
            article_title=article.title,
            article_link=article.link,
            article_html=article.html,
            article_text=article.text,
            article_published_at=article.published_at,
        )
        return 0
    except Exception as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1
    finally:
        cleanup_media(config.media_dir, config.cleanup_media_after_run)


if __name__ == "__main__":
    raise SystemExit(main())
