from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from markdown import markdown

from studio_models import ContentItem, PostStatsSnapshot, Publication


ROOT_DIR = Path(__file__).resolve().parent
CONTENT_ROOT = ROOT_DIR / "content"
CONTENT_DRAFTS_DIR = CONTENT_ROOT / "drafts"
STUDIO_DATA_DIR = ROOT_DIR / "studio_data"
PUBLICATIONS_PATH = STUDIO_DATA_DIR / "publications.json"
STATS_SNAPSHOTS_PATH = STUDIO_DATA_DIR / "stats_snapshots.json"
SUBSTACK_IMPORTS_DIRNAME = "imports/substack"
LEGACY_GLOB = "*.md"


def ensure_studio_dirs(content_dir: Path | None = None) -> None:
    base_dir = content_dir or CONTENT_DRAFTS_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    STUDIO_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT_DIR / SUBSTACK_IMPORTS_DIRNAME).mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-") or f"untitled-{uuid4().hex[:8]}"


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return split_csv(value)
    return []


def content_item_to_metadata(item: ContentItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "subtitle": item.subtitle,
        "slug": item.slug,
        "status": item.status,
        "channels": item.channels,
        "tags": item.tags,
        "categories": item.categories,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "published_at": item.published_at,
        "cover_image_path": item.cover_image_path,
        "linkedin_post_urn": item.linkedin_post_urn,
        "instagram_media_id": item.instagram_media_id,
        "substack_post_id": item.substack_post_id,
        "x_post_id": item.x_post_id,
    }


def markdown_frontmatter(item: ContentItem) -> str:
    metadata = yaml.safe_dump(content_item_to_metadata(item), sort_keys=False, allow_unicode=False).strip()
    return f"---\n{metadata}\n---\n\n{item.markdown_body.rstrip()}\n"


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if raw.startswith("---\n"):
        marker = "\n---\n"
        end = raw.find(marker, 4)
        if end != -1:
            metadata_block = raw[4:end]
            body = raw[end + len(marker):]
            loaded = yaml.safe_load(metadata_block) or {}
            if isinstance(loaded, dict):
                return loaded, body.lstrip("\n")
    return {}, raw


def render_markdown_html(markdown_body: str) -> str:
    body = markdown_body.strip()
    if not body:
        return "<p><em>Nothing to preview yet.</em></p>"
    return markdown(
        body,
        extensions=["extra", "sane_lists", "tables", "fenced_code", "nl2br"],
        output_format="html5",
    )


def plain_text_from_markdown(markdown_body: str) -> str:
    text = markdown_body
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^[#>*\-+]+\s*", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def content_dir_for_slug(content_dir: Path, slug: str) -> Path:
    return content_dir / slug


def content_paths_for_slug(content_dir: Path, slug: str) -> dict[str, Path]:
    draft_dir = content_dir_for_slug(content_dir, slug)
    return {
        "dir": draft_dir,
        "json": draft_dir / "content.json",
        "markdown": draft_dir / "content.md",
        "metadata": draft_dir / "metadata.yaml",
        "assets": draft_dir / "assets",
        "revisions": draft_dir / "revisions",
    }


def build_editor_json_from_html(html_body: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": plain_text_from_markdown(html_body or "") or ""}],
            }
        ],
    }


def content_item_from_directory(draft_dir: Path) -> ContentItem:
    metadata_path = draft_dir / "metadata.yaml"
    content_json_path = draft_dir / "content.json"
    markdown_path = draft_dir / "content.md"
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        loaded = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            metadata = loaded
    markdown_body = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
    editor_json: dict[str, Any] = {}
    html_body = ""
    if content_json_path.exists():
        loaded = json.loads(content_json_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            editor_json = loaded.get("editor_json") or {}
            html_body = str(loaded.get("html_body") or "")
            markdown_body = str(loaded.get("markdown_body") or markdown_body)
    title = str(metadata.get("title") or draft_dir.name.replace("-", " ").title())
    subtitle = str(metadata.get("subtitle") or "")
    slug = str(metadata.get("slug") or draft_dir.name)
    item_id = str(metadata.get("id") or slug)
    return ContentItem(
        id=item_id,
        title=title,
        subtitle=subtitle,
        slug=slug,
        status=str(metadata.get("status") or "draft"),
        channels=normalize_string_list(metadata.get("channels")),
        tags=normalize_string_list(metadata.get("tags")),
        categories=normalize_string_list(metadata.get("categories")),
        editor_json=editor_json,
        markdown_body=markdown_body.rstrip(),
        html_body=html_body or render_markdown_html(markdown_body),
        cover_image_path=str(metadata.get("cover_image_path") or ""),
        created_at=str(metadata.get("created_at") or ""),
        updated_at=str(metadata.get("updated_at") or ""),
        published_at=str(metadata.get("published_at") or ""),
        linkedin_post_urn=str(metadata.get("linkedin_post_urn") or ""),
        instagram_media_id=str(metadata.get("instagram_media_id") or ""),
        substack_post_id=str(metadata.get("substack_post_id") or ""),
        x_post_id=str(metadata.get("x_post_id") or ""),
    )


def content_item_from_legacy_file(path: Path) -> ContentItem:
    raw = path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(raw)
    title = str(metadata.get("title") or path.stem.replace("-", " ").title())
    subtitle = str(metadata.get("subtitle") or "")
    slug = str(metadata.get("slug") or path.stem)
    item_id = str(metadata.get("id") or slug)
    html_body = render_markdown_html(body)
    return ContentItem(
        id=item_id,
        title=title,
        subtitle=subtitle,
        slug=slug,
        status=str(metadata.get("status") or "draft"),
        channels=normalize_string_list(metadata.get("channels")),
        tags=normalize_string_list(metadata.get("tags")),
        categories=normalize_string_list(metadata.get("categories")),
        editor_json=build_editor_json_from_html(html_body),
        markdown_body=body.rstrip(),
        html_body=html_body,
        cover_image_path=str(metadata.get("cover_image_path") or ""),
        created_at=str(metadata.get("created_at") or ""),
        updated_at=str(metadata.get("updated_at") or ""),
        published_at=str(metadata.get("published_at") or ""),
        linkedin_post_urn=str(metadata.get("linkedin_post_urn") or ""),
        instagram_media_id=str(metadata.get("instagram_media_id") or ""),
        substack_post_id=str(metadata.get("substack_post_id") or ""),
        x_post_id=str(metadata.get("x_post_id") or ""),
    )


def list_content_items(content_dir: Path) -> list[ContentItem]:
    ensure_studio_dirs(content_dir)
    items: list[ContentItem] = []
    for draft_dir in sorted(path for path in content_dir.iterdir() if path.is_dir()):
        if (draft_dir / "metadata.yaml").exists() or (draft_dir / "content.json").exists() or (draft_dir / "content.md").exists():
            items.append(content_item_from_directory(draft_dir))
    for legacy_path in sorted(CONTENT_ROOT.glob(LEGACY_GLOB)):
        slug = legacy_path.stem
        if not (content_dir / slug).exists():
            items.append(content_item_from_legacy_file(legacy_path))
    return sorted(items, key=lambda item: item.updated_at or item.created_at or "", reverse=True)


def get_content_item(content_dir: Path, identifier: str) -> ContentItem | None:
    if not identifier:
        return None
    for item in list_content_items(content_dir):
        if item.id == identifier or item.slug == identifier:
            return item
    return None


def build_content_item_from_form(form: dict[str, Any], existing: ContentItem | None = None) -> ContentItem:
    title = str(form.get("title") or "").strip()
    subtitle = str(form.get("subtitle") or (existing.subtitle if existing else "")).strip()
    slug = slugify(str(form.get("slug") or title or (existing.slug if existing else "")))
    current_time = now_iso()
    existing_id = existing.id if existing else uuid4().hex
    created_at = existing.created_at if existing and existing.created_at else current_time
    published_at = str(form.get("published_at") or (existing.published_at if existing else "")).strip()
    markdown_body = str(form.get("markdown_body") or (existing.markdown_body if existing else "")).rstrip()
    html_body = str(form.get("html_body") or (existing.html_body if existing else "")).strip() or render_markdown_html(markdown_body)
    editor_json = form.get("editor_json") or (existing.editor_json if existing else {})
    if isinstance(editor_json, str):
        try:
            editor_json = json.loads(editor_json)
        except json.JSONDecodeError:
            editor_json = existing.editor_json if existing else {}
    if not isinstance(editor_json, dict):
        editor_json = existing.editor_json if existing else {}
    cover_image_path = str(form.get("cover_image_path") or (existing.cover_image_path if existing else "")).strip()
    return ContentItem(
        id=existing_id,
        title=title or "Untitled",
        subtitle=subtitle,
        slug=slug,
        status=str(form.get("status") or "draft").strip() or "draft",
        channels=normalize_string_list(form.get("channels")),
        tags=split_csv(str(form.get("tags") or "")),
        categories=split_csv(str(form.get("categories") or "")),
        editor_json=editor_json,
        markdown_body=markdown_body,
        html_body=html_body,
        cover_image_path=cover_image_path,
        created_at=created_at,
        updated_at=current_time,
        published_at=published_at,
        linkedin_post_urn=str(form.get("linkedin_post_urn") or (existing.linkedin_post_urn if existing else "")).strip(),
        instagram_media_id=str(form.get("instagram_media_id") or (existing.instagram_media_id if existing else "")).strip(),
        substack_post_id=str(form.get("substack_post_id") or (existing.substack_post_id if existing else "")).strip(),
        x_post_id=str(form.get("x_post_id") or (existing.x_post_id if existing else "")).strip(),
    )


def save_content_item(content_dir: Path, item: ContentItem, previous_slug: str | None = None) -> Path:
    ensure_studio_dirs(content_dir)
    paths = content_paths_for_slug(content_dir, item.slug)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    paths["assets"].mkdir(parents=True, exist_ok=True)
    paths["revisions"].mkdir(parents=True, exist_ok=True)
    payload = {
        "editor_json": item.editor_json,
        "markdown_body": item.markdown_body,
        "html_body": item.html_body,
    }
    paths["json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["markdown"].write_text(markdown_frontmatter(item), encoding="utf-8")
    paths["metadata"].write_text(yaml.safe_dump(content_item_to_metadata(item), sort_keys=False, allow_unicode=False), encoding="utf-8")

    if previous_slug and previous_slug != item.slug:
        old_paths = content_paths_for_slug(content_dir, previous_slug)
        if old_paths["dir"].exists():
            shutil.rmtree(old_paths["dir"])
        legacy = CONTENT_ROOT / f"{previous_slug}.md"
        if legacy.exists():
            legacy.unlink()
    return paths["dir"]


def delete_content_item(content_dir: Path, identifier: str) -> bool:
    item = get_content_item(content_dir, identifier)
    if not item:
        return False
    paths = content_paths_for_slug(content_dir, item.slug)
    if paths["dir"].exists():
        shutil.rmtree(paths["dir"])
    legacy = CONTENT_ROOT / f"{item.slug}.md"
    if legacy.exists():
        legacy.unlink()
    return True


def create_revision_snapshot(content_dir: Path, item: ContentItem, reason: str = "manual") -> Path:
    ensure_studio_dirs(content_dir)
    paths = content_paths_for_slug(content_dir, item.slug)
    paths["revisions"].mkdir(parents=True, exist_ok=True)
    revision_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    revision_path = paths["revisions"] / f"{revision_id}.json"
    payload = {
        "id": revision_id,
        "reason": reason,
        "saved_at": now_iso(),
        "item": content_item_to_metadata(item),
        "editor_json": item.editor_json,
        "markdown_body": item.markdown_body,
        "html_body": item.html_body,
    }
    revision_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return revision_path


def list_content_revisions(content_dir: Path, identifier: str, limit: int = 12) -> list[dict[str, Any]]:
    item = get_content_item(content_dir, identifier)
    if not item:
        return []
    revision_dir = content_paths_for_slug(content_dir, item.slug)["revisions"]
    if not revision_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(revision_dir.glob("*.json"), reverse=True):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(loaded, dict):
            loaded["_path"] = str(path)
            records.append(loaded)
        if len(records) >= limit:
            break
    return records


def load_content_revision(content_dir: Path, identifier: str, revision_id: str) -> dict[str, Any] | None:
    item = get_content_item(content_dir, identifier)
    if not item:
        return None
    revision_path = content_paths_for_slug(content_dir, item.slug)["revisions"] / f"{revision_id}.json"
    if not revision_path.exists():
        return None
    try:
        loaded = json.loads(revision_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def export_markdown(item: ContentItem) -> str:
    return markdown_frontmatter(item)


def export_html(item: ContentItem) -> str:
    return item.html_body or render_markdown_html(item.markdown_body)


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def save_json_list(path: Path, records: list[dict[str, Any]]) -> None:
    STUDIO_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def list_publications() -> list[Publication]:
    records = load_json_list(PUBLICATIONS_PATH)
    return [Publication(**record) for record in records]


def save_publications(publications: list[Publication]) -> None:
    save_json_list(PUBLICATIONS_PATH, [publication.__dict__ for publication in publications])


def list_stats_snapshots() -> list[PostStatsSnapshot]:
    records = load_json_list(STATS_SNAPSHOTS_PATH)
    return [PostStatsSnapshot(**record) for record in records]


def save_stats_snapshots(snapshots: list[PostStatsSnapshot]) -> None:
    save_json_list(STATS_SNAPSHOTS_PATH, [snapshot.__dict__ for snapshot in snapshots])
