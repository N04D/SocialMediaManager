from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_pipeline = importlib.import_module("pipeline")
Article = getattr(_pipeline, "Article", Any)


ROOT_DIR = Path(__file__).resolve().parent
OUTBOX_DIR = ROOT_DIR / "outbox"
SCHEDULE_PATH = OUTBOX_DIR / "scheduled_posts.json"
PREVIEW_PATH = OUTBOX_DIR / "last_preview.json"
WORKER_RUNS_PATH = OUTBOX_DIR / "worker_runs.json"
LAUNCH_STATUS_PATH = OUTBOX_DIR / "launch_status.json"


@dataclass
class ScheduleRecord:
    id: str
    created_at: str
    platform: str
    content_type: str
    content_item_id: str | None
    content_item_slug: str | None
    scheduled_for: str
    notes: str
    article_title: str
    article_link: str
    article_html: str
    article_text: str
    source_published_at: str | None
    article_teaser: str
    image_sources: list[str]
    status: str = "queued"
    processed_at: str | None = None
    result: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "platform": self.platform,
            "content_type": self.content_type,
            "content_item_id": self.content_item_id,
            "content_item_slug": self.content_item_slug,
            "scheduled_for": self.scheduled_for,
            "notes": self.notes,
            "article_title": self.article_title,
            "article_link": self.article_link,
            "article_html": self.article_html,
            "article_text": self.article_text,
            "source_published_at": self.source_published_at,
            "article_teaser": self.article_teaser,
            "image_sources": self.image_sources,
            "status": self.status,
            "processed_at": self.processed_at,
            "result": self.result,
        }


def ensure_outbox_dir() -> None:
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)


def load_schedule() -> list[dict[str, Any]]:
    if not SCHEDULE_PATH.exists():
        return []
    try:
        with SCHEDULE_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except json.JSONDecodeError:
        return []
    return []


def save_schedule(records: list[dict[str, Any]]) -> None:
    ensure_outbox_dir()
    with SCHEDULE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=True, indent=2)


def append_schedule(record: dict[str, Any]) -> None:
    records = load_schedule()
    records.append(record)
    save_schedule(records)


def update_schedule_record(record_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    records = load_schedule()
    updated_record: dict[str, Any] | None = None
    for index, record in enumerate(records):
        if record.get("id") == record_id:
            record.update(updates)
            updated_record = record
            records[index] = record
            break
    if updated_record is not None:
        save_schedule(records)
    return updated_record


def reset_failed_schedule_records() -> int:
    records = load_schedule()
    changed = 0
    for record in records:
        if record.get("status") == "failed":
            record.update(
                {
                    "status": "queued",
                    "processed_at": None,
                    "result": None,
                }
            )
            changed += 1
    if changed:
        save_schedule(records)
    return changed


def get_schedule_record(record_id: str) -> dict[str, Any] | None:
    for record in load_schedule():
        if record.get("id") == record_id:
            return record
    return None


def parse_scheduled_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


def next_due_record(records: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any] | None:
    current_time = now or datetime.now()
    for record in records:
        if record.get("status") != "queued":
            continue
        scheduled_for = record.get("scheduled_for")
        if not isinstance(scheduled_for, str):
            continue
        try:
            if parse_scheduled_time(scheduled_for) <= current_time:
                return record
        except ValueError:
            continue
    return None


def queue_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return records[-25:]


def build_schedule_record(
    article: Article,
    teaser: str,
    platform: str,
    content_type: str,
    scheduled_for: str,
    notes: str,
    image_sources: list[str],
    content_item_id: str | None = None,
    content_item_slug: str | None = None,
) -> ScheduleRecord:
    now = datetime.now().isoformat(timespec="seconds")
    return ScheduleRecord(
        id=now,
        created_at=now,
        platform=platform,
        content_type=content_type,
        content_item_id=content_item_id,
        content_item_slug=content_item_slug,
        scheduled_for=scheduled_for,
        notes=notes,
        article_title=article.title,
        article_link=article.link,
        article_html=article.html,
        article_text=article.text,
        source_published_at=article.published_at,
        article_teaser=teaser,
        image_sources=image_sources,
    )


def cache_preview(payload: dict[str, Any]) -> None:
    ensure_outbox_dir()
    with PREVIEW_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def load_preview() -> dict[str, Any] | None:
    if not PREVIEW_PATH.exists():
        return None
    try:
        with PREVIEW_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def save_worker_runs(records: list[dict[str, Any]]) -> None:
    ensure_outbox_dir()
    with WORKER_RUNS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=True, indent=2)


def load_worker_runs() -> list[dict[str, Any]]:
    if not WORKER_RUNS_PATH.exists():
        return []
    try:
        with WORKER_RUNS_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except json.JSONDecodeError:
        return []
    return []


def append_worker_run(record: dict[str, Any]) -> None:
    records = load_worker_runs()
    records.append(record)
    save_worker_runs(records[-25:])


def worker_run_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return records[-10:]


def save_launch_status(payload: dict[str, Any]) -> None:
    ensure_outbox_dir()
    with LAUNCH_STATUS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def load_launch_status() -> dict[str, Any] | None:
    if not LAUNCH_STATUS_PATH.exists():
        return None
    try:
        with LAUNCH_STATUS_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None
