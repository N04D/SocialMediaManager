from __future__ import annotations

from datetime import datetime, timedelta, timezone


DEFAULT_ARTICLE_PUBLISH_TIME = "15:00"


def parse_time_of_day(value: str | None) -> tuple[int, int]:
    if not value:
        return 15, 0

    try:
        hour_text, minute_text = str(value).strip().split(":", 1)
        hour = max(0, min(23, int(hour_text)))
        minute = max(0, min(59, int(minute_text)))
        return hour, minute
    except Exception:
        return 15, 0


def compute_article_publish_time(
    mode: str,
    delay_days: int,
    time_of_day: str | None,
    now: datetime | None = None,
) -> datetime | None:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode == "direct":
        return None

    base = now or datetime.now().astimezone()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)

    days = max(0, int(delay_days))
    hour, minute = parse_time_of_day(time_of_day or DEFAULT_ARTICLE_PUBLISH_TIME)
    target = (base + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= base:
        target += timedelta(days=1)
    return target


def compute_article_schedule_time(
    buffer_minutes: int,
    now: datetime | None = None,
) -> datetime:
    base = now or datetime.now().astimezone()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    minutes = max(10, int(buffer_minutes))
    return base + timedelta(minutes=minutes)
