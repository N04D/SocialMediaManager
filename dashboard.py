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
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from browser_pilots import (
    ProviderStateEvent,
    append_provider_state_event,
    cancel_pilot,
    confirm_pilot_action,
    create_browser_pilot,
    get_browser_pilot,
    list_browser_pilots,
    list_provider_state_events,
    pause_pilot,
    pop_issued_confirmation_token,
    prepare_pilot_action,
    rollback_pilot,
    run_pilot_preflight,
)
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
    get_publish_job,
    list_channel_job_logs,
    list_metric_snapshots,
    list_published_posts,
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
    get_content_item,
    list_content_items,
    list_content_revisions,
    list_publications,
    list_stats_snapshots,
    load_content_revision,
    plain_text_from_markdown,
    render_markdown_html,
    save_content_item,
    slugify,
)
from pipeline import (
    CONFIG_PATH,
    AppConfig,
    Article,
    build_prompt,
    ensure_runtime_dirs,
    fetch_article,
    load_config,
    run_local_ai,
)
from plugin_runtime import get_plugin_runtime
from scheduler import (
    append_schedule,
    build_schedule_record,
    cache_preview,
    ensure_outbox_dir,
    get_schedule_record,
    load_launch_status,
    load_preview,
    load_schedule,
    load_worker_runs,
    queue_summary,
    reset_failed_schedule_records,
    save_launch_status,
    update_schedule_record,
    worker_run_summary,
)
from src.core.media import MediaInput, MediaValidationError
from src.core.owned_publication import OwnedPublicationWorkspaceService
from src.core.owned_publication.errors import OwnedPublicationError
from src.core.plugin_distribution import (
    PluginDistributionIntegrityService,
    PluginInstallationService,
    PluginRegistryService,
    PluginRegistrySource,
)
from src.core.plugin_distribution.contracts import PLUGIN_DISTRIBUTION_FRAMEWORK_VERSION
from src.core.plugin_host import (
    PLUGIN_HOST_FRAMEWORK_VERSION,
    PLUGIN_HOST_PROTOCOL_VERSION,
    PluginHostIntegrityService,
    PluginHostResourceController,
)
from src.core.plugin_sandbox import (
    PLUGIN_SANDBOX_FRAMEWORK_VERSION,
    PluginSandboxIntegrityService,
    SandboxPolicyCompiler,
    select_sandbox_controller,
)
from src.core.plugin_sandbox.integrity import context_from_install_record
from src.core.publication_dependencies import PublicationDependencyGraph, PublicationTargetDependency
from src.plugin_sdk.compatibility import build_compatibility_report
from src.plugin_sdk.contracts import PLUGIN_SDK_VERSION
from studio_models import ContentItem
from timing import compute_article_schedule_time

ROOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT_DIR / "assets"
ROUTE_EDITOR = "/editor"
ROUTE_DRAFTS = "/drafts"
ROUTE_LINKEDIN = "/linkedin"
ROUTE_STATS = "/stats"
ROUTE_SCHEDULER = "/scheduler"
ROUTE_INSTAGRAM = "/instagram"
ROUTE_CONFIG = "/config"
ROUTE_MEDIA = "/media-library"
ROUTE_CONTENT_PLANS = "/content-plans"
ROUTE_CONTENT_CALENDAR = "/content-calendar"
ROUTE_ANALYTICS = "/analytics"
ROUTE_PLUGINS = "/plugins"
ROUTE_CONTENT = "/content"
ROUTE_PUBLICATIONS = "/publications"
ROUTE_FUNNELS = "/funnels"
ROUTE_OPERATIONS = "/publications/reconciliation"
VALID_ROUTES = {
    ROUTE_EDITOR,
    ROUTE_DRAFTS,
    ROUTE_LINKEDIN,
    ROUTE_STATS,
    ROUTE_SCHEDULER,
    ROUTE_INSTAGRAM,
    ROUTE_CONFIG,
    ROUTE_MEDIA,
    ROUTE_CONTENT_PLANS,
    ROUTE_CONTENT_CALENDAR,
    ROUTE_ANALYTICS,
    ROUTE_PLUGINS,
    ROUTE_CONTENT,
    ROUTE_PUBLICATIONS,
    ROUTE_FUNNELS,
    ROUTE_OPERATIONS,
}

SIDEBAR_ITEMS = [
    (ROUTE_EDITOR, "editor", "Editor", "ED"),
    (ROUTE_DRAFTS, "drafts", "Drafts", "DR"),
    (ROUTE_LINKEDIN, "linkedin", "LinkedIn", "LI"),
    (ROUTE_INSTAGRAM, "instagram", "Instagram", "IG"),
    (ROUTE_SCHEDULER, "scheduler", "Scheduler", "SC"),
    (ROUTE_STATS, "stats", "Stats", "ST"),
    (ROUTE_MEDIA, "media", "Media", "ML"),
    (ROUTE_CONTENT_PLANS, "content", "Plans", "PL"),
    (ROUTE_CONTENT_CALENDAR, "scheduler", "Calendar", "CA"),
    (ROUTE_ANALYTICS, "stats", "Analytics", "AN"),
    (ROUTE_CONTENT, "content", "Content", "CO"),
    (ROUTE_PUBLICATIONS, "scheduler", "Publications", "PU"),
    (ROUTE_FUNNELS, "stats", "Funnels", "FU"),
    (ROUTE_OPERATIONS, "config", "Operations", "OP"),
    (ROUTE_CONFIG, "config", "Config", "CF"),
]

EDITOR_TOOLBAR_BUTTONS = [
    (
        "bold",
        "Bold",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5h5.2c2.6 0 4.3 1.4 4.3 3.7 0 1.5-.8 2.7-2.2 3.2 1.8.4 3 1.8 3 3.8 0 2.6-1.9 4.3-5 4.3H8V5zm3 2.4v3.4h2.1c1 0 1.6-.6 1.6-1.7S14.1 7.4 13 7.4H11zm0 5.7v4h2.6c1.2 0 1.9-.7 1.9-1.9s-.7-2-1.9-2H11z"/></svg>',
    ),
    (
        "italic",
        "Italic",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 5v2h2.2l-3.4 10H6v2h8v-2h-2.2l3.4-10H18V5z"/></svg>',
    ),
    (
        "underline",
        "Underline",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4v7a5 5 0 0 0 10 0V4h-2v7a3 3 0 0 1-6 0V4H7zm-1 15h12v2H6z"/></svg>',
    ),
    (
        "h2",
        "Heading 2",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h2v5h5V6h2v12h-2v-5H6v5H4zM17 9.5c0-1.4 1.1-2.5 2.5-2.5S22 8.1 22 9.5c0 1-.5 1.8-1.3 2.4l-1.9 1.4h3.2V15h-6v-1.3l3.3-2.6c.5-.4.7-.8.7-1.3 0-.6-.4-1-.9-1s-.9.4-.9 1V10h-1.8v-.5z"/></svg>',
    ),
    (
        "h3",
        "Heading 3",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h2v5h5V6h2v12h-2v-5H6v5H4zM18.4 10.2H17V8.7h4.7v1.1l-1.8 1.7c1 .2 1.7 1 1.7 2.1 0 1.5-1.2 2.5-3 2.5-1.9 0-3-.9-3.1-2.5h1.7c.1.6.5 1 1.3 1 .7 0 1.2-.4 1.2-1.1 0-.7-.5-1.1-1.3-1.1h-.9v-1.3z"/></svg>',
    ),
    (
        "bulletList",
        "Bullet list",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6h11v2H9zm0 5h11v2H9zm0 5h11v2H9zM5 7a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zm0 5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zm0 5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0z"/></svg>',
    ),
    (
        "orderedList",
        "Ordered list",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 6h10v2H10zm0 5h10v2H10zm0 5h10v2H10zM4 5h1v5H3V8h1zm-1 8h2.2c.4 0 .8.4.8.8 0 .2-.1.4-.3.6L4 16h2v2H2.4v-1.2l2-1.9H3v-2z"/></svg>',
    ),
    (
        "blockquote",
        "Blockquote",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 6h5v5H9.6c0 1.7 1 3 2.7 3.8L11 17c-2.7-1-4-3.1-4-6.3V6zm8 0h5v5h-2.4c0 1.7 1 3 2.7 3.8L19 17c-2.7-1-4-3.1-4-6.3V6z"/></svg>',
    ),
    (
        "codeBlock",
        "Code block",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8.5 16.5-4.5-4.5 4.5-4.5 1.4 1.4L6.8 12l3.1 3.1zm7 0-1.4-1.4 3.1-3.1-3.1-3.1 1.4-1.4 4.5 4.5zm-4.6 2.1-1.9-.5 4-14 1.9.5z"/></svg>',
    ),
    (
        "horizontalRule",
        "Horizontal rule",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11h16v2H4z"/></svg>',
    ),
    (
        "link",
        "Link",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.6 13.4a1 1 0 0 0 1.4 1.4l4.2-4.2a3 3 0 0 0-4.2-4.2L9.8 8.6a1 1 0 1 0 1.4 1.4l2.2-2.2a1 1 0 1 1 1.4 1.4zm2.8-2.8a1 1 0 0 0-1.4-1.4L7.8 13.4a3 3 0 1 0 4.2 4.2l2.2-2.2a1 1 0 0 0-1.4-1.4l-2.2 2.2a1 1 0 0 1-1.4-1.4z"/></svg>',
    ),
    (
        "image-upload",
        "Upload image",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm0 2v8.2l3.3-3.3a1 1 0 0 1 1.4 0l2 2L15.8 10a1 1 0 0 1 1.4 0L19 11.8V7H5zm14 10v-2.4l-2.5-2.5-4.1 4.1-3-3L5 17h14zM9 8.5A1.5 1.5 0 1 1 6 8.5a1.5 1.5 0 0 1 3 0z"/></svg>',
    ),
]

EDITOR_ACTION_BUTTONS = [
    (
        "editor-new-draft",
        "New draft",
        "secondary",
        "link",
        ROUTE_EDITOR,
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg>',
    ),
    (
        "editor-toggle-preview",
        "Preview mode",
        "secondary",
        "button",
        "",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5c5.5 0 9.3 4.2 10.6 6-1.3 1.8-5.1 6-10.6 6S2.7 12.8 1.4 11C2.7 9.2 6.5 5 12 5zm0 2C8.3 7 5.3 9.5 3.8 11 5.3 12.5 8.3 15 12 15s6.7-2.5 8.2-4C18.7 9.5 15.7 7 12 7zm0 1.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z"/></svg>',
    ),
    (
        "editor-toggle-focus",
        "Focus mode",
        "secondary",
        "button",
        "",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5v2H6v3H4zm10-5h5v5h-2V6h-3V4zM4 15h2v3h3v2H4v-5zm13 0h2v5h-5v-2h3v-3z"/></svg>',
    ),
    (
        "editor-export-markdown",
        "Export Markdown",
        "secondary",
        "button",
        "",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h10l4 4v12H5V4zm9 1.5V9h3.5L14 5.5zM8 12v4H6v-4h2zm1 4 1.6-4h1.6l1.6 4h-1.7l-.2-.7h-1.4l-.2.7H9zm2.1-1.9h.8l-.4-1.3-.4 1.3zm3.1-2.1h1.7l1 1.6 1-1.6h1.7l-1.8 2.8 1.9 3h-1.7l-1.1-1.7-1.1 1.7h-1.7l1.9-3-1.8-2.8z"/></svg>',
    ),
    (
        "editor-export-html",
        "Export HTML",
        "secondary",
        "button",
        "",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h10l4 4v12H5V4zm9 1.5V9h3.5L14 5.5zM8.4 15.8 6 13.4l2.4-2.4 1.1 1.1-1.3 1.3 1.3 1.3-1.1 1.1zm3.2 1.2h-1.4l2.2-8h1.4l-2.2 8zm3-1.2-1.1-1.1 1.3-1.3-1.3-1.3 1.1-1.1 2.4 2.4-2.4 2.4z"/></svg>',
    ),
    (
        "",
        "Save draft",
        "",
        "submit",
        "",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h11l3 3v13H5V4zm2 2v12h10V8.5L15.5 7H15v3H9V6H7zm4 0v2h2V6h-2zm1 10.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z"/></svg>',
    ),
    (
        "",
        "Save and queue",
        "secondary",
        "submit",
        "/editor/schedule",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h12v2H6V5zm0 6h8v2H6v-2zm0 6h8v2H6v-2zm10-5 5 4-5 4v-3h-3v-2h3v-3z"/></svg>',
    ),
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
    if cleaned.startswith("/content/"):
        return ROUTE_CONTENT
    if cleaned.startswith("/publications/"):
        return ROUTE_OPERATIONS if cleaned == ROUTE_OPERATIONS else ROUTE_PUBLICATIONS
    if cleaned.startswith("/funnels/"):
        return ROUTE_FUNNELS
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


def json_response(
    handler: BaseHTTPRequestHandler, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _safe_media_asset_payload(asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "workspace_id": asset.workspace_id,
        "media_type": asset.media_type,
        "mime_type": asset.mime_type,
        "original_filename": asset.original_filename,
        "display_name": asset.display_name,
        "storage_provider_id": asset.storage_provider_id,
        "checksum": asset.checksum[:12],
        "file_size": asset.file_size,
        "width": asset.width,
        "height": asset.height,
        "duration_ms": asset.duration_ms,
        "status": asset.status,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
        "source_type": asset.source_type,
    }


def _safe_relation_payload(relation) -> dict[str, Any]:
    return {
        "id": relation.id,
        "workspace_id": relation.workspace_id,
        "owner_type": relation.owner_type,
        "owner_id": relation.owner_id,
        "asset_id": relation.asset_id,
        "variant_id": relation.variant_id,
        "role": relation.role,
        "position": relation.position,
        "channel_plugin_id": relation.channel_plugin_id,
        "publication_id": relation.publication_id,
        "required": relation.required,
        "active": relation.active,
        "created_at": relation.created_at,
        "updated_at": relation.updated_at,
    }


def _safe_usage_payload(usage) -> dict[str, Any]:
    return {
        "id": usage.id,
        "workspace_id": usage.workspace_id,
        "asset_id": usage.asset_id,
        "variant_id": usage.variant_id,
        "usage_type": usage.usage_type,
        "owner_type": usage.owner_type,
        "owner_id": usage.owner_id,
        "channel_plugin_id": usage.channel_plugin_id,
        "publication_id": usage.publication_id,
        "job_id": usage.job_id,
        "status": usage.status,
        "first_used_at": usage.first_used_at,
        "last_used_at": usage.last_used_at,
        "usage_count": usage.usage_count,
        "retained_until": usage.retained_until,
    }


def _safe_content_payload(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "content_type": item.content_type,
        "title": item.title,
        "body_preview": item.body[:280],
        "summary": item.summary,
        "language": item.language,
        "status": item.status,
        "current_revision_id": item.current_revision_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "source_type": item.source_type,
    }


def _safe_revision_payload(revision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "content_item_id": revision.content_item_id,
        "workspace_id": revision.workspace_id,
        "revision_number": revision.revision_number,
        "title": revision.title,
        "body_preview": revision.body[:280],
        "summary": revision.summary,
        "language": revision.language,
        "checksum": revision.checksum[:16],
        "created_at": revision.created_at,
        "created_by": revision.created_by,
        "change_reason": revision.change_reason,
    }


def _safe_variant_payload(variant) -> dict[str, Any]:
    return {
        "id": variant.id,
        "workspace_id": variant.workspace_id,
        "content_item_id": variant.content_item_id,
        "source_revision_id": variant.source_revision_id,
        "channel_plugin_id": variant.channel_plugin_id,
        "capability": variant.capability,
        "variant_type": variant.variant_type,
        "title": variant.title,
        "body_preview": variant.body[:280],
        "hashtags": list(variant.hashtags or []),
        "language": variant.language,
        "status": variant.status,
        "validation_status": variant.validation_status,
        "requirement_version": variant.requirement_version,
        "variant_checksum": variant.variant_checksum[:16],
        "updated_at": variant.updated_at,
    }


def _safe_plan_payload(plan, targets: list[Any] | None = None) -> dict[str, Any]:
    return {
        "id": plan.id,
        "workspace_id": plan.workspace_id,
        "content_item_id": plan.content_item_id,
        "source_revision_id": plan.source_revision_id,
        "name": plan.name,
        "status": plan.status,
        "planned_start_at": plan.planned_start_at,
        "timezone": plan.timezone,
        "validation_status": plan.validation_status,
        "snapshot_checksum": plan.snapshot_checksum[:16],
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "targets": [_safe_target_payload(target) for target in targets or []],
    }


def _safe_target_payload(target) -> dict[str, Any]:
    snapshot = dict((target.metadata or {}).get("snapshot") or {})
    return {
        "id": target.id,
        "publication_plan_id": target.publication_plan_id,
        "workspace_id": target.workspace_id,
        "channel_plugin_id": target.channel_plugin_id,
        "channel_account_id": target.channel_account_id,
        "capability": target.capability,
        "source_revision_id": target.source_revision_id,
        "channel_variant_id": target.channel_variant_id,
        "media_relation_ids": list(target.media_relation_ids or []),
        "position": target.position,
        "scheduled_at": target.scheduled_at,
        "timezone": target.timezone,
        "status": target.status,
        "validation_status": target.validation_status,
        "snapshot_checksum": target.snapshot_checksum[:16],
        "job_id": target.job_id,
        "snapshot": {
            "content_item_id": snapshot.get("content_item_id", ""),
            "revision_id": snapshot.get("revision_id", ""),
            "variant_id": snapshot.get("variant_id", ""),
            "media_relation_ids": list(snapshot.get("media_relation_ids") or []),
            "media_requirement_version": snapshot.get("media_requirement_version", ""),
            "content_requirement_version": snapshot.get("content_requirement_version", ""),
        },
    }


def _safe_attempt_payload(attempt) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "workspace_id": attempt.workspace_id,
        "publication_plan_id": attempt.publication_plan_id,
        "publication_target_id": attempt.publication_target_id,
        "attempt_number": attempt.attempt_number,
        "snapshot_checksum": attempt.snapshot_checksum[:16],
        "status": attempt.status,
        "phase": attempt.phase,
        "trigger": attempt.trigger,
        "worker_id": attempt.worker_id,
        "lease_id": attempt.lease_id,
        "job_id": attempt.job_id,
        "publication_id": attempt.publication_id,
        "started_at": attempt.started_at,
        "heartbeat_at": attempt.heartbeat_at,
        "completed_at": attempt.completed_at,
        "next_retry_at": attempt.next_retry_at,
        "retry_count": attempt.retry_count,
        "error_class": attempt.error_class,
        "safe_error_code": attempt.safe_error_code,
        "mutation_state": attempt.mutation_state,
        "remote_verification_state": attempt.remote_verification_state,
        "cleanup_state": attempt.cleanup_state,
    }


def _safe_schedule_payload(schedule) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "workspace_id": schedule.workspace_id,
        "name": schedule.name,
        "description": schedule.description,
        "status": schedule.status,
        "timezone": schedule.timezone,
        "starts_at_local": schedule.starts_at_local,
        "starts_at_utc": schedule.starts_at_utc,
        "recurrence_rule_id": schedule.recurrence_rule_id,
        "schedule_policy_id": schedule.schedule_policy_id,
        "template_snapshot_id": schedule.template_snapshot_id,
        "authorization_id": schedule.authorization_id,
        "campaign_id": schedule.campaign_id,
        "next_occurrence_at": schedule.next_occurrence_at,
        "last_occurrence_at": schedule.last_occurrence_at,
        "materialized_until": schedule.materialized_until,
        "generation_version": schedule.generation_version,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
        "paused_at": schedule.paused_at,
        "pause_reason": schedule.pause_reason,
        "cancelled_at": schedule.cancelled_at,
        "cancellation_reason": schedule.cancellation_reason,
    }


def _safe_occurrence_payload(occurrence) -> dict[str, Any]:
    return {
        "id": occurrence.id,
        "workspace_id": occurrence.workspace_id,
        "schedule_id": occurrence.schedule_id,
        "campaign_id": occurrence.campaign_id,
        "occurrence_key": occurrence.occurrence_key[:16],
        "generation_version": occurrence.generation_version,
        "sequence_number": occurrence.sequence_number,
        "scheduled_at_local": occurrence.scheduled_at_local,
        "timezone": occurrence.timezone,
        "scheduled_at_utc": occurrence.scheduled_at_utc,
        "status": occurrence.status,
        "source_template_snapshot_id": occurrence.source_template_snapshot_id,
        "template_snapshot_checksum": occurrence.template_snapshot_checksum[:16],
        "publication_plan_id": occurrence.publication_plan_id,
        "publication_target_ids": list(occurrence.publication_target_ids or []),
        "authorization_id": occurrence.authorization_id,
        "materialized_at": occurrence.materialized_at,
        "completed_at": occurrence.completed_at,
        "skipped_at": occurrence.skipped_at,
        "skip_reason": occurrence.skip_reason,
        "blocked_reason": occurrence.blocked_reason,
    }


def _safe_authorization_payload(authorization) -> dict[str, Any]:
    return {
        "id": authorization.id,
        "workspace_id": authorization.workspace_id,
        "schedule_id": authorization.schedule_id,
        "template_snapshot_checksum": authorization.template_snapshot_checksum[:16],
        "authorized_by": authorization.authorized_by,
        "authorized_at": authorization.authorized_at,
        "valid_from": authorization.valid_from,
        "valid_until": authorization.valid_until,
        "maximum_occurrences": authorization.maximum_occurrences,
        "consumed_occurrences": authorization.consumed_occurrences,
        "allowed_channel_account_ids": list(authorization.allowed_channel_account_ids or []),
        "allowed_capabilities": list(authorization.allowed_capabilities or []),
        "status": authorization.status,
        "revoked_at": authorization.revoked_at,
        "revoke_reason": authorization.revoke_reason,
    }


def _safe_calendar_entry_payload(entry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "workspace_id": entry.workspace_id,
        "entry_type": entry.entry_type,
        "starts_at": entry.starts_at,
        "ends_at": entry.ends_at,
        "timezone": entry.timezone,
        "title": entry.title,
        "status": entry.status,
        "channel_plugin_id": entry.channel_plugin_id,
        "channel_account_id": entry.channel_account_id,
        "campaign_id": entry.campaign_id,
        "schedule_id": entry.schedule_id,
        "occurrence_id": entry.occurrence_id,
        "plan_id": entry.plan_id,
        "target_id": entry.target_id,
        "attempt_id": entry.attempt_id,
        "attention_required": entry.attention_required,
        "blockers": list(entry.blockers or []),
        "safe_summary": entry.safe_summary,
    }


def _safe_campaign_payload(campaign, members: list[Any] | None = None) -> dict[str, Any]:
    return {
        "id": campaign.id,
        "workspace_id": campaign.workspace_id,
        "name": campaign.name,
        "description": campaign.description,
        "status": campaign.status,
        "starts_at": campaign.starts_at,
        "ends_at": campaign.ends_at,
        "timezone": campaign.timezone,
        "coordination_policy_id": campaign.coordination_policy_id,
        "created_at": campaign.created_at,
        "updated_at": campaign.updated_at,
        "paused_at": campaign.paused_at,
        "pause_reason": campaign.pause_reason,
        "cancelled_at": campaign.cancelled_at,
        "cancellation_reason": campaign.cancellation_reason,
        "members": [asdict(member) for member in members or []],
    }


def _shorten_checksums(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _shorten_checksums(item) for key, item in value.items() if "path" not in key.lower()}
    if isinstance(value, list):
        return [_shorten_checksums(item) for item in value]
    if isinstance(value, str) and len(value) >= 40 and all(char in "0123456789abcdef" for char in value.lower()):
        return value[:16]
    return value


def _safe_analytics_payload(payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {
        "contentbody",
        "content_body",
        "browser_session_id",
        "takeover_url",
        "storage_reference",
        "materialized_path",
        "screenshot_path",
        "cookies",
        "html",
    }
    return {
        key: _shorten_checksums(value)
        for key, value in payload.items()
        if key not in blocked and not any(fragment in key.lower() for fragment in ("path", "cookie", "secret"))
    }


def _safe_observation_payload(observation) -> dict[str, Any]:
    payload = asdict(observation)
    payload["observation_key"] = str(payload.get("observation_key") or "")[:16]
    payload["source_evidence_reference"] = "available" if payload.get("source_evidence_reference") else ""
    payload["metadata"] = {
        key: value
        for key, value in dict(payload.get("metadata") or {}).items()
        if not any(fragment in key.lower() for fragment in ("path", "cookie", "secret", "html"))
    }
    return _safe_analytics_payload(payload)


def _safe_attribution_payload(attribution) -> dict[str, Any]:
    payload = asdict(attribution)
    payload["attribution_checksum"] = str(payload.get("attribution_checksum") or "")[:16]
    return _safe_analytics_payload(payload)


def _query_filters(query: dict[str, list[str]]) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    for key in [
        "page",
        "page_size",
        "sort_by",
        "sort_dir",
        "display_name",
        "original_filename",
        "media_type",
        "mime_type",
        "status",
        "storage_provider_id",
        "inspection_status",
        "min_width",
        "max_width",
        "min_height",
        "max_height",
        "checksum",
        "suitability",
    ]:
        if query.get(key, [""])[0] != "":
            filters[key] = query.get(key, [""])[0]
    for key in ["linked", "used", "deleted"]:
        if key in query:
            filters[key] = query.get(key, [""])[0].lower() in {"1", "true", "on", "yes"}
    return filters


def validate_force_unlock_confirmation(reason: str, confirmation: str) -> tuple[bool, str]:
    if len(reason.strip()) < 8:
        return False, "Force unlock requires a reason of at least 8 characters."
    if confirmation.strip().lower() not in {"yes", "on", "true", "1"}:
        return False, "Force unlock requires explicit confirmation."
    return True, ""


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
        raw = raw[len(prefix) :]
    if raw.startswith("content/drafts/"):
        raw = raw[len("content/drafts/") :]
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
        if button_type == "link":
            href_attr = f' href="{html.escape(form_action)}"'
            action_buttons.append(
                f'<a class="{classes}"{id_attr}{href_attr} title="{html.escape(label)}" aria-label="{html.escape(label)}">{icon}<span class="sr-only action-label">{html.escape(label)}</span></a>'
            )
            continue
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


def build_editor_item_from_request(
    form: dict[str, list[str]],
    existing: ContentItem | None = None,
    *,
    forced_status: str | None = None,
    fallback_channels: list[str] | None = None,
) -> ContentItem:
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
              <path d="M5 4.5h9.5L19 9v10.5H5z"></path>
              <path d="M14.5 4.5V9H19"></path>
              <path d="M8 13h8"></path>
              <path d="M8 16.5h6"></path>
            </svg>
        """,
        "drafts": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6 5h9l3 3v11H6z"></path>
              <path d="M15 5v3h3"></path>
              <path d="M9 12h6"></path>
              <path d="M9 15.5h4"></path>
              <path d="M4 8h2"></path>
              <path d="M4 12h2"></path>
              <path d="M4 16h2"></path>
            </svg>
        """,
        "linkedin": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 10h3v9H5z"></path>
              <path d="M5 5.5a1.5 1.5 0 1 0 3 0 1.5 1.5 0 0 0-3 0"></path>
              <path d="M12 10h3v1.4c.6-.9 1.6-1.7 3.1-1.7 2.3 0 3.9 1.6 3.9 4.6V19h-3v-4.2c0-1.4-.6-2.2-1.8-2.2-1.1 0-1.8.7-2.2 1.6V19h-3z"></path>
            </svg>
        """,
        "instagram": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="4.5" y="4.5" width="15" height="15" rx="4"></rect>
              <circle cx="12" cy="12" r="3.2"></circle>
              <path d="M16.8 7.2h.01"></path>
            </svg>
        """,
        "scheduler": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="4" y="5.5" width="16" height="14" rx="2"></rect>
              <path d="M4 10h16"></path>
              <path d="M8 3.5v4"></path>
              <path d="M16 3.5v4"></path>
              <path d="M10 14h4"></path>
              <path d="M12 12v4"></path>
            </svg>
        """,
        "stats": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 19h16"></path>
              <path d="M7 16V9"></path>
              <path d="M12 16V5"></path>
              <path d="M17 16v-6"></path>
            </svg>
        """,
        "config": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="3"></circle>
              <path d="M12 3.5v2"></path>
              <path d="M12 18.5v2"></path>
              <path d="M4.6 7.8l1.7 1"></path>
              <path d="M17.7 15.2l1.7 1"></path>
              <path d="M4.6 16.2l1.7-1"></path>
              <path d="M17.7 8.8l1.7-1"></path>
            </svg>
        """,
        "channels": """
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="4" y="5" width="6" height="6" rx="1.5"></rect>
              <rect x="14" y="5" width="6" height="6" rx="1.5"></rect>
              <rect x="4" y="15" width="6" height="4" rx="1.3"></rect>
              <rect x="14" y="15" width="6" height="4" rx="1.3"></rect>
            </svg>
        """,
    }
    svg = icons.get(name)
    if svg:
        return svg
    return f'<span class="sidebar-fallback">{html.escape(fallback)}</span>'


def queue_item_url(record_id: str, route: str) -> str:
    return f"{route}?detail={html.escape(record_id)}"


def status_filter_url(route: str, status: str | None, detail_id: str | None = None) -> str:
    params: list[str] = []
    if status and status != "all":
        params.append(f"status={status}")
    if detail_id:
        params.append(f"detail={detail_id}")
    return route + (("?" + "&".join(params)) if params else "")


def render_status_badge(status: str, label: str | None = None) -> str:
    normalized = (status or "unknown").strip().lower()
    known = {"queued", "processing", "done", "failed", "success", "idle", "running"}
    class_name = normalized if normalized in known else "unknown"
    return f'<span class="status-badge status-{html.escape(class_name)}">{html.escape(label or status or "Unknown")}</span>'


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
        log_file.write(
            f"\n[{datetime.now().isoformat(timespec='seconds')}] Opening and filling LinkedIn article draft\n"
        )
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
        log_file.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] Starting worker: {' '.join(worker_args)}\n")
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
    return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${").replace("</", "<\\/")


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


def select_content_item_for_route(
    content_dir: Path,
    content_items: list[ContentItem],
    content_identifier: str | None,
    route: str,
) -> ContentItem:
    selected = get_content_item(content_dir, content_identifier) if content_identifier else None
    if selected is not None:
        return selected
    return make_empty_content_item()


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
        rows.append('<p class="meta">No local drafts yet. Create your first content item here.</p>')
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
    editor_json_seed = json.dumps(selected_item.editor_json or {}, ensure_ascii=False)
    cover_preview_url = public_asset_url(config.content_dir, selected_item.cover_image_path)
    revisions = (
        list_content_revisions(config.content_dir, selected_item.id or selected_item.slug, limit=10)
        if selected_item.id or selected_item.slug
        else []
    )
    cover_preview_markup = (
        f'<img src="{html.escape(cover_preview_url)}" alt="Cover preview" class="cover-preview-image" />'
        if cover_preview_url
        else '<div class="cover-preview-empty">No cover selected yet.</div>'
    )
    revision_items = (
        "".join(
            f"""
        <li class="revision-item">
          <div class="revision-copy">
            <strong>{html.escape(str(revision.get("saved_at") or revision.get("id") or "Unknown revision"))}</strong>
            <span class="meta">{html.escape(render_revision_reason(str(revision.get("reason") or "manual")))}</span>
          </div>
          <form method="post" action="/editor/restore-revision" class="revision-form">
            <input type="hidden" name="return_to" value="{html.escape(f"{ROUTE_EDITOR}?content={selected_item.id or selected_item.slug}")}" />
            <input type="hidden" name="content_id" value="{html.escape(selected_item.id or selected_item.slug)}" />
            <input type="hidden" name="revision_id" value="{html.escape(str(revision.get("id") or ""))}" />
            <button type="submit" class="editor-panel-button subtle">Restore</button>
          </form>
        </li>
        """
            for revision in revisions
        )
        or '<li class="revision-empty meta">No revisions yet. They start appearing after edits and restores.</li>'
    )
    return f"""
      <div class=\"editor-main\">
        <section class=\"card\">
            <form method=\"post\" action=\"/editor/save\" id=\"studio-editor-form\">
              <input type=\"hidden\" name=\"return_to\" value=\"{html.escape(ROUTE_EDITOR)}\" />
              <input type=\"hidden\" name=\"content_id\" value=\"{html.escape(selected_item.id)}\" />
              <input type=\"hidden\" name=\"previous_slug\" value=\"{html.escape(selected_item.slug)}\" />
              <input type=\"hidden\" name=\"editor_json\" id=\"editor-json-input\" value=\"{
        html.escape(editor_json_seed)
    }\" />
              <input type=\"hidden\" name=\"markdown_body\" id=\"editor-markdown-input\" value=\"{
        html.escape(selected_item.markdown_body)
    }\" />
              <input type=\"hidden\" name=\"html_body\" id=\"editor-html-input\" value=\"{
        html.escape(editor_html_seed)
    }\" />
              <input type=\"hidden\" name=\"cover_image_path\" id=\"editor-cover-image-input\" value=\"{
        html.escape(selected_item.cover_image_path)
    }\" />
              <input type=\"file\" id=\"editor-image-upload\" accept=\"image/*\" hidden />

              <div class=\"writer-shell\">
                <div class=\"writer-layout\">
                  <div class=\"writer-compose\">
                    <div class=\"editor-workbench\">
                      <div class=\"editor-column\">
                        <div class=\"editor-toolbar\" id=\"editor-toolbar\">{render_editor_toolbar()}</div>
                        <div class=\"editor-writing-surface\">
                          <div class=\"editor-primary-fields editor-primary-fields-inline\">
                            <input id=\"editor-title\" class=\"editor-title-input\" name=\"title\" value=\"{
        html.escape(selected_item.title)
    }\" placeholder=\"Title\" />
                            <textarea id=\"editor-subtitle\" class=\"editor-subtitle-input\" name=\"subtitle\" placeholder=\"Subtitle or dek\">{
        html.escape(selected_item.subtitle)
    }</textarea>
                          </div>
                          <div class=\"editor-drop-hint\" id=\"editor-drop-hint\">Drop images here to add them to the draft</div>
                          <div id=\"tiptap-editor\" class=\"tiptap-editor\"></div>
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
                          <pre id=\"frontmatter-preview\" class=\"frontmatter-preview\">---\ntitle: {
        html.escape(selected_item.title)
    }\nsubtitle: {html.escape(selected_item.subtitle)}\nstatus: {html.escape(selected_item.status)}\nchannels: [{
        html.escape(", ".join(selected_item.channels))
    }]\ntags: [{html.escape(", ".join(selected_item.tags))}]\ncreated_at: {
        html.escape(selected_item.created_at)
    }\nupdated_at: {html.escape(selected_item.updated_at)}\npublished_at: {
        html.escape(selected_item.published_at)
    }\nlinkedin_post_urn: {html.escape(selected_item.linkedin_post_urn)}\ninstagram_media_id: {
        html.escape(selected_item.instagram_media_id)
    }\nsubstack_post_id: {html.escape(selected_item.substack_post_id)}\nx_post_id: {
        html.escape(selected_item.x_post_id)
    }\n---</pre>
                        </section>
                      </div>
                    </div>
                  </div>

                  <aside class=\"editor-rail\">
                    <div class=\"editor-rail-sticky\">
                      <details class=\"editor-panel\">
                        <summary class=\"editor-panel-summary\">
                          <span class=\"editor-panel-summary-left\"><span class=\"editor-panel-icon\">{
        render_editor_panel_icon("metadata")
    }</span><span>Metadata</span></span>
                          <span class=\"editor-panel-chevron\" aria-hidden=\"true\"></span>
                        </summary>
                        <div class=\"editor-panel-body editor-side-fields\">
                          <label for=\"editor-slug\">Slug</label>
                          <input id=\"editor-slug\" name=\"slug\" value=\"{
        html.escape(selected_item.slug)
    }\" placeholder=\"auto-generated-from-title\" />
                          <label for=\"editor-status\">Status</label>
                          <select id=\"editor-status\" name=\"status\">
                            <option value=\"draft\" {
        "selected" if selected_item.status == "draft" else ""
    }>Draft</option>
                            <option value=\"scheduled\" {
        "selected" if selected_item.status == "scheduled" else ""
    }>Scheduled</option>
                          </select>
                          <label for=\"editor-tags\">Tags</label>
                          <input id=\"editor-tags\" name=\"tags\" value=\"{
        html.escape(", ".join(selected_item.tags))
    }\" placeholder=\"essay, theology, psychology\" />
                          <label for=\"editor-categories\">Categories</label>
                          <input id=\"editor-categories\" name=\"categories\" value=\"{
        html.escape(", ".join(selected_item.categories))
    }\" placeholder=\"LinkedIn, Longform\" />
                          <label for=\"editor-published-at\">Published at</label>
                          <input id=\"editor-published-at\" name=\"published_at\" value=\"{
        html.escape(selected_item.published_at)
    }\" placeholder=\"2026-06-09T15:00:00+02:00\" />
                        </div>
                      </details>

                      <details class=\"editor-panel\">
                        <summary class=\"editor-panel-summary\">
                          <span class=\"editor-panel-summary-left\"><span class=\"editor-panel-icon\">{
        render_editor_panel_icon("channels")
    }</span><span>Channels</span></span>
                          <span class=\"editor-panel-chevron\" aria-hidden=\"true\"></span>
                        </summary>
                        <div class=\"editor-panel-body\">
                          <div class=\"checkbox-grid checkbox-grid-rail\">{
        render_channel_checkbox_grid(selected_channels)
    }</div>
                        </div>
                      </details>

                      <details class=\"editor-panel\">
                        <summary class=\"editor-panel-summary\">
                          <span class=\"editor-panel-summary-left\"><span class=\"editor-panel-icon\">{
        render_editor_panel_icon("media")
    }</span><span>Media</span></span>
                          <span class=\"editor-panel-chevron\" aria-hidden=\"true\"></span>
                        </summary>
                        <div class=\"editor-panel-body\">
                          <p class=\"meta\">The first image you upload becomes the cover automatically.</p>
                          <div id=\"editor-cover-preview\" class=\"cover-preview\">{cover_preview_markup}</div>
                          <label for=\"editor-cover-image-path\">Cover image path</label>
                          <input id=\"editor-cover-image-path\" value=\"{
        html.escape(selected_item.cover_image_path)
    }\" placeholder=\"Auto-filled from first uploaded image\" readonly />
                        </div>
                      </details>

                      <details class=\"editor-panel\">
                        <summary class=\"editor-panel-summary\">
                          <span class=\"editor-panel-summary-left\"><span class=\"editor-panel-icon\">{
        render_editor_panel_icon("revisions")
    }</span><span>Revisions</span></span>
                          <span class=\"editor-panel-chevron\" aria-hidden=\"true\"></span>
                        </summary>
                        <div class=\"editor-panel-body\">
                          <ul class=\"revision-list\">{revision_items}</ul>
                        </div>
                      </details>

                      <details class=\"editor-panel\">
                        <summary class=\"editor-panel-summary\">
                          <span class=\"editor-panel-summary-left\"><span class=\"editor-panel-icon\">{
        render_editor_panel_icon("ai")
    }</span><span>AI prompt</span></span>
                          <span class=\"editor-panel-chevron\" aria-hidden=\"true\"></span>
                        </summary>
                        <div class=\"editor-panel-body ai-chat-panel\">
                          <textarea id=\"editor-ai-prompt\" class=\"editor-ai-prompt\" aria-label=\"AI prompt\"></textarea>
                          <div class=\"ai-chat-actions\">
                            <button id=\"editor-ai-apply\" type=\"button\" class=\"editor-panel-button\">Send</button>
                          </div>
                          <p id=\"editor-ai-feedback\" class=\"meta editor-ai-feedback\"></p>
                        </div>
                      </details>
                    </div>
                  </aside>
                </div>

              </div>
            </form>
        </section>
        {render_document_performance_panel(selected_item)}
        {
        render_derivatives_panel(
            selected_item, return_to=f"{ROUTE_EDITOR}?content={selected_item.id or selected_item.slug}"
        )
    }
      </div>
      <script>
        window.__studioEditorSeed = {
        json.dumps(
            {
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
            },
            ensure_ascii=False,
        )
    };
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

    image_rows = (
        "".join(
            f'<li><a href="{html.escape(str(source))}" target="_blank" rel="noreferrer">{html.escape(str(source))}</a></li>'
            for source in image_sources
        )
        or "<li>No image sources stored.</li>"
    )

    result = record.get("result") or "No result yet."
    processed_at = record.get("processed_at") or "Not processed yet."
    content_type = str(record.get("content_type", "post"))
    route = "Article -> Al-Batin Page" if content_type == "article" else "Post -> LinkedIn feed"
    retry_button = ""
    if str(record.get("status", "")) == "failed":
        retry_button = f"""
          <form method="post" action="/retry">
            <input type="hidden" name="id" value="{html.escape(str(record.get("id", "")))}" />
            <input type="hidden" name="return_to" value="{html.escape(return_to)}" />
            <div class="actions">
              <button type="submit">Retry failed item</button>
            </div>
          </form>
        """

    return f"""
        <section class="card">
          <h2>Queue Detail</h2>
          <p><strong>{html.escape(str(record.get("article_title", "Untitled")))}</strong></p>
          <p class="meta">Platform: <code>{html.escape(str(record.get("platform", "")))}</code></p>
          <p class="meta">Content type: <code>{html.escape(str(record.get("content_type", "post")))}</code></p>
          <p class="meta">Route: <code>{html.escape(route)}</code></p>
          <p class="meta">Status: {render_status_badge(str(record.get("status", "queued")))}</p>
          <p class="meta">Scheduled for: <code>{html.escape(str(record.get("scheduled_for", "")))}</code></p>
          <p class="meta">Source published at: <code>{html.escape(str(record.get("source_published_at", "")) or "Unknown")}</code></p>
          <p class="meta">Created at: <code>{html.escape(str(record.get("created_at", "")))}</code></p>
          <p class="meta">Processed at: <code>{html.escape(str(processed_at))}</code></p>
          <p class="meta">Article link: <a href="{html.escape(str(record.get("article_link", "")))}" target="_blank" rel="noreferrer">{html.escape(str(record.get("article_link", "")))}</a></p>
          <p class="meta">Notes: {html.escape(str(record.get("notes", "")) or "No notes")}</p>
          <h3>Teaser</h3>
          <div class="teaser">{html.escape(str(record.get("article_teaser", "")))}</div>
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
            f"<td>{render_status_badge(str(record.get('status', '')))}</td>"
            f"<td>{html.escape(str(record.get('message', '')))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='3'><div class='empty-state'>No worker runs yet.</div></td></tr>")
    return f"""
        <section class="card">
          <h2>Worker Runs</h2>
          <table>
            <thead><tr><th>Time</th><th>Status</th><th>Message</th></tr></thead>
            <tbody>{"".join(rows)}</tbody>
          </table>
        </section>
    """


def render_launch_status() -> str:
    return """
        <section class="card">
          <h2>Article Launch</h2>
          <div id="launch-status-content">
            <div class="empty-state">No launch in progress yet.</div>
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
          <p class="meta">Cover image: <code>{"enabled" if config.linkedin_article_use_cover_image else "disabled"}</code></p>
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
            f'<a href="{status_filter_url(route, status)}" class="button nav-chip{active}">{html.escape(status.title())} ({counts[status]})</a>'
        )
    chips.append(
        f'<form class="inline-form" method="post" action="/retry-all"><input type="hidden" name="return_to" value="{html.escape(route)}" /><button type="submit">Retry all failed</button></form>'
    )
    return f"<div class='actions filter-bar' aria-label='Queue filters'>{''.join(chips)}</div>"


def render_scheduler_summary(records: list[dict[str, Any]]) -> str:
    total = len(records)
    failed = sum(1 for record in records if str(record.get("status", "")) == "failed")
    processing = sum(1 for record in records if str(record.get("status", "")) == "processing")
    queued = sum(1 for record in records if str(record.get("status", "")) == "queued")
    done = sum(1 for record in records if str(record.get("status", "")) == "done")
    latest_run = ""
    worker_runs = worker_run_summary(load_worker_runs())
    if worker_runs:
        latest = worker_runs[-1]
        latest_run = (
            f'<p class="meta">Last worker run: '
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
          <a class="summary-pill" href="{status_filter_url(ROUTE_SCHEDULER, "all")}"><strong>{total}</strong><span>Total</span></a>
          <a class="summary-pill" href="{status_filter_url(ROUTE_SCHEDULER, "queued")}"><strong>{queued}</strong><span>Queued</span></a>
          <a class="summary-pill" href="{status_filter_url(ROUTE_SCHEDULER, "processing")}"><strong>{processing}</strong><span>Processing</span></a>
          <a class="summary-pill" href="{status_filter_url(ROUTE_SCHEDULER, "done")}"><strong>{done}</strong><span>Done</span></a>
          <a class="summary-pill" href="{status_filter_url(ROUTE_SCHEDULER, "failed")}"><strong>{failed}</strong><span>Failed</span></a>
        </div>
        {latest_run}
      </section>
    """


def render_queue_table(queue: list[dict[str, Any]], route: str) -> str:
    queue_rows = []
    for item in reversed(queue):
        record_id = str(item.get("id", ""))
        queue_rows.append(
            f'<tr><td><a href="{queue_item_url(record_id, route)}">{html.escape(str(item.get("scheduled_for", "")))}</a></td>'
            f"<td>{html.escape(str(item.get('platform', '')))}</td>"
            f"<td>{html.escape(str(item.get('content_type', 'article')))}</td>"
            f"<td>{html.escape(str(item.get('source_published_at', '') or 'Unknown'))}</td>"
            f"<td>{html.escape(str(item.get('article_title', '')))}</td>"
            f"<td>{render_status_badge(str(item.get('status', 'queued')))}</td></tr>"
        )
    if not queue_rows:
        queue_rows.append("<tr><td colspan='6'><div class='empty-state'>No scheduled items yet.</div></td></tr>")
    return f"""
      <section class="card">
        <h2>Schedule Queue</h2>
        <table>
          <thead><tr><th>Scheduled for</th><th>Platform</th><th>Type</th><th>Source published</th><th>Article</th><th>Status</th></tr></thead>
          <tbody>{"".join(queue_rows)}</tbody>
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
      <div class=\"teaser\">{html.escape(teaser) if teaser else "Click Generate Preview to create the teaser."}</div>
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
        <input id=\"scheduled_for\" name=\"scheduled_for\" value=\"{html.escape(default_schedule_time("article", article, config))}\" />
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


def render_linkedin_page(
    config: AppConfig, snapshot: dict[str, Any], preview: dict[str, Any] | None, all_records: list[dict[str, Any]]
) -> str:
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


def render_scheduler_page(
    all_records: list[dict[str, Any]],
    queue: list[dict[str, Any]],
    selected_record: dict[str, Any] | None,
    selected_status: str | None,
) -> str:
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
      <div class=\"config-tabs\">
        <input class=\"config-tab-input\" type=\"radio\" name=\"config_tab\" id=\"config-tab-overview\" checked />
        <input class=\"config-tab-input\" type=\"radio\" name=\"config_tab\" id=\"config-tab-system\" />
        <input class=\"config-tab-input\" type=\"radio\" name=\"config_tab\" id=\"config-tab-browser\" />
        <input class=\"config-tab-input\" type=\"radio\" name=\"config_tab\" id=\"config-tab-article\" />
        <input class=\"config-tab-input\" type=\"radio\" name=\"config_tab\" id=\"config-tab-channels\" />
        <div class=\"config-tab-list\" role=\"tablist\" aria-label=\"Config sections\">
          <label class=\"config-tab-label\" for=\"config-tab-overview\" role=\"tab\">Overview</label>
          <label class=\"config-tab-label\" for=\"config-tab-system\" role=\"tab\">System</label>
          <label class=\"config-tab-label\" for=\"config-tab-browser\" role=\"tab\">Browser</label>
          <label class=\"config-tab-label\" for=\"config-tab-article\" role=\"tab\">Article</label>
          <label class=\"config-tab-label\" for=\"config-tab-channels\" role=\"tab\">Channels</label>
        </div>
        <div class=\"config-tab-panels\">
          <div class=\"config-tab-panel config-panel-overview\" role=\"tabpanel\">
            <section class=\"card compact-card\">
              <div class=\"card-heading\">
                <div><h2>Read-only Config</h2></div>
                <span class=\"status-badge\">Read only</span>
              </div>
              <dl class=\"readonly-config-list\">
                <div><dt>Config file</dt><dd><code>{html.escape(str(CONFIG_PATH))}</code></dd></div>
                <div><dt>Content directory</dt><dd><code>{html.escape(str(config.content_dir))}</code></dd></div>
                <div><dt>RSS feed</dt><dd><code>{html.escape(config.rss_url)}</code></dd></div>
                <div><dt>Publish as</dt><dd><code>{html.escape(config.linkedin_publish_as_page_name)}</code></dd></div>
                <div><dt>Content mode</dt><dd><code>{html.escape(config.linkedin_content_mode)}</code></dd></div>
                <div><dt>Schedule buffer</dt><dd><code>{html.escape(str(config.linkedin_article_schedule_buffer_minutes))} minutes</code></dd></div>
                <div><dt>Stats interval</dt><dd><code>{html.escape(str(config.stats_sync_interval_minutes))} minutes</code></dd></div>
                <div><dt>Cover upload</dt><dd><code>{"enabled" if config.linkedin_article_use_cover_image else "disabled"}</code></dd></div>
              </dl>
            </section>
          </div>
          <div class=\"config-tab-panel config-panel-system\" role=\"tabpanel\">
            <section class=\"card\">
              <h2>Platform Configuration</h2>
              <form method=\"post\" action=\"/system-config\">
                <input type=\"hidden\" name=\"return_to\" value=\"{html.escape(ROUTE_CONFIG)}\" />
                <div class=\"editor-two-up\">
                  <div>
                    <label for=\"content_dir\">Local content directory</label>
                    <input id=\"content_dir\" name=\"content_dir\" value=\"{html.escape(str(config.content_dir))}\" />
                  </div>
                  <div>
                    <label for=\"substack_import_dir\">Substack export/import directory</label>
                    <input id=\"substack_import_dir\" name=\"substack_import_dir\" value=\"{html.escape(str(config.substack_import_dir))}\" />
                  </div>
                </div>
                <label for=\"stats_sync_interval_minutes\">Stats sync interval (minutes)</label>
                <input id=\"stats_sync_interval_minutes\" name=\"stats_sync_interval_minutes\" type=\"number\" min=\"15\" value=\"{html.escape(str(config.stats_sync_interval_minutes))}\" />
                <div class=\"editor-two-up\">
                  <div>
                    <label><input type=\"checkbox\" name=\"linkedin_api_enabled\" value=\"true\" {"checked" if config.linkedin_api_enabled else ""} /> LinkedIn API enabled</label>
                    <label for=\"linkedin_api_org_urn\">LinkedIn org/page URN</label>
                    <input id=\"linkedin_api_org_urn\" name=\"linkedin_api_org_urn\" value=\"{html.escape(config.linkedin_api_org_urn)}\" placeholder=\"urn:li:organization:123\" />
                  </div>
                  <div>
                    <label><input type=\"checkbox\" name=\"instagram_api_enabled\" value=\"true\" {"checked" if config.instagram_api_enabled else ""} /> Instagram/Meta API enabled</label>
                    <label for=\"instagram_business_account_id\">Instagram business account ID</label>
                    <input id=\"instagram_business_account_id\" name=\"instagram_business_account_id\" value=\"{html.escape(config.instagram_business_account_id)}\" placeholder=\"1784...\" />
                  </div>
                </div>
                <div class=\"editor-two-up\">
                  <div>
                    <label><input type=\"checkbox\" name=\"substack_import_enabled\" value=\"true\" {"checked" if config.substack_import_enabled else ""} /> Substack import enabled</label>
                  </div>
                  <div>
                    <label><input type=\"checkbox\" name=\"x_api_enabled\" value=\"true\" {"checked" if config.x_api_enabled else ""} /> X API enabled</label>
                    <label for=\"x_account_id\">X account ID</label>
                    <input id=\"x_account_id\" name=\"x_account_id\" value=\"{html.escape(config.x_account_id)}\" placeholder=\"account id\" />
                  </div>
                </div>
                <div class=\"actions\"><button type=\"submit\">Save system config</button></div>
              </form>
            </section>
          </div>
          <div class=\"config-tab-panel config-panel-browser\" role=\"tabpanel\">{render_browser_session(config, ROUTE_CONFIG)}</div>
          <div class=\"config-tab-panel config-panel-article\" role=\"tabpanel\">{render_article_timing(config, ROUTE_CONFIG)}</div>
          <div class=\"config-tab-panel config-panel-channels\" role=\"tabpanel\">{render_channel_cards(return_to=ROUTE_CONFIG)}</div>
        </div>
      </div>
    """


def render_media_library_page(config: AppConfig, query: dict[str, list[str]] | None = None) -> str:
    query = query or {}
    runtime = get_plugin_runtime(config, reset=True, strict=False)
    library = runtime.media_library_service(config)
    workspace_id = query.get("workspace_id", ["linkedin"])[0]
    filters = {
        "page": query.get("page", ["1"])[0],
        "page_size": query.get("page_size", ["24"])[0],
        "display_name": query.get("display_name", [""])[0],
        "mime_type": query.get("mime_type", [""])[0],
        "status": query.get("status", [""])[0],
        "sort_by": query.get("sort_by", ["created_at"])[0],
        "sort_dir": query.get("sort_dir", ["desc"])[0],
        "deleted": query.get("deleted", [""])[0].lower() in {"1", "true", "on"},
    }
    result = library.search_assets(workspace_id=workspace_id, filters=filters)
    cards = []
    for asset in result.assets:
        suitability = asset.get("channel_suitability", {})
        linkedin = next(iter(suitability.values()), {})
        preview_url = f"/api/media/assets/{html.escape(asset['id'])}/preview?workspace_id={html.escape(workspace_id)}"
        cards.append(
            f"""
            <article class="panel-card media-library-card">
              <img class="media-library-preview" src="{preview_url}" alt="" loading="lazy" />
              <div class="media-library-meta">
                <strong>{html.escape(str(asset.get("display_name") or asset.get("original_filename") or asset["id"]))}</strong>
                <span class="meta">{html.escape(str(asset.get("mime_type") or ""))} · {asset.get("width", 0)}×{asset.get("height", 0)} · {asset.get("file_size", 0)} bytes</span>
                <span class="meta">Relations {asset.get("relation_count", 0)} · Usage {asset.get("usage_count", 0)} · {html.escape(str(asset.get("created_at") or ""))}</span>
                <span class="meta">LinkedIn: {html.escape(str(linkedin.get("status") or "unknown"))}</span>
                <div class="inline-actions">
                  <form method="post" action="/media-library/soft-delete">
                    <input type="hidden" name="asset_id" value="{html.escape(asset["id"])}" />
                    <input type="hidden" name="workspace_id" value="{html.escape(workspace_id)}" />
                    <button type="submit" class="danger">Soft delete</button>
                  </form>
                  <form method="post" action="/media-library/restore">
                    <input type="hidden" name="asset_id" value="{html.escape(asset["id"])}" />
                    <input type="hidden" name="workspace_id" value="{html.escape(workspace_id)}" />
                    <button type="submit" class="secondary">Restore</button>
                  </form>
                </div>
              </div>
            </article>
            """
        )
    page_prev = max(result.page - 1, 1)
    page_next = result.page + 1
    return f"""
    <section class="editor-shell">
      <div class="editor-main">
        <div class="editor-panel">
          <div class="editor-panel-header">
            <div>
              <h2>Media Library</h2>
              <p class="meta">{result.total} assets · page {result.page}</p>
            </div>
            <div class="inline-actions">
              <a class="button secondary" href="/api/media/library/health">Health</a>
              <a class="button secondary" href="/api/media/integrity?workspace_id={html.escape(workspace_id)}">Integrity</a>
              <a class="button secondary" href="/api/media/retention/preview?workspace_id={html.escape(workspace_id)}">Retention preview</a>
            </div>
          </div>
          <form class="config-grid" method="get" action="{ROUTE_MEDIA}">
            <label>Workspace<input name="workspace_id" value="{html.escape(workspace_id)}" /></label>
            <label>Name<input name="display_name" value="{html.escape(str(filters["display_name"]))}" /></label>
            <label>MIME<input name="mime_type" value="{html.escape(str(filters["mime_type"]))}" /></label>
            <label>Status<input name="status" value="{html.escape(str(filters["status"]))}" /></label>
            <label>Sort
              <select name="sort_by">
                {"".join(f'<option value="{value}" {"selected" if filters["sort_by"] == value else ""}>{value}</option>' for value in ["created_at", "display_name", "file_size", "last_used_at", "usage_count"])}
              </select>
            </label>
            <label><input type="checkbox" name="deleted" value="1" {"checked" if filters["deleted"] else ""} /> include deleted</label>
            <button type="submit">Filter</button>
          </form>
          <div class="media-library-grid">{"".join(cards) or render_placeholder_card("No media", "No matching media assets found.")}</div>
          <div class="inline-actions">
            <a class="button secondary" href="{ROUTE_MEDIA}?workspace_id={html.escape(workspace_id)}&page={page_prev}">Previous</a>
            <a class="button secondary" href="{ROUTE_MEDIA}?workspace_id={html.escape(workspace_id)}&page={page_next}">Next</a>
          </div>
        </div>
      </div>
    </section>
    """


def render_content_planning_page(config: AppConfig) -> str:
    runtime = get_plugin_runtime(config, reset=True, strict=False)
    content_service = runtime.content_service(config)
    planning = runtime.publication_planning_service(config)
    execution = runtime.publication_execution_service(config)
    items = content_service.list_content()
    plans = planning.plan_repository.list_all()
    due = execution.find_due_targets(batch_size=10, dry_run=True)
    health = execution.health_check()
    item_options = "".join(
        f'<option value="{html.escape(item.id)}">{html.escape(item.title)} · {html.escape(item.status)}</option>'
        for item in items
    )
    plan_rows = []
    for plan in plans[:20]:
        targets = planning.target_repository.list_by_plan(plan.id)
        plan_rows.append(
            f"""
            <tr>
              <td>{html.escape(plan.name)}</td>
              <td><code>{html.escape(plan.id)}</code></td>
              <td>{html.escape(plan.status)}</td>
              <td>{len(targets)}</td>
              <td><code>{html.escape(plan.snapshot_checksum[:16])}</code></td>
              <td class="inline-actions">
                <form method="post" action="/content-plans/validate"><input type="hidden" name="plan_id" value="{html.escape(plan.id)}" /><button type="submit" class="secondary">Validate</button></form>
                <form method="post" action="/content-plans/prepare"><input type="hidden" name="plan_id" value="{html.escape(plan.id)}" /><button type="submit" class="secondary">Prepare</button></form>
                <form method="post" action="/content-plans/queue"><input type="hidden" name="plan_id" value="{html.escape(plan.id)}" /><button type="submit">Queue</button></form>
              </td>
            </tr>
            """
        )
    return f"""
      {render_website_analytics_page()}
      {render_website_instrumentation_page()}
      {render_staging_analytics_page()}
      <div class="page-grid">
        <div class="stack">
          <section class="card">
            <div class="card-heading">
              <div><h2>Canonical Content</h2><p class="meta">Content Framework v0.1 keeps source text, variants, media relations, and publication intent separate.</p></div>
              <a class="button secondary" href="/api/content/requirements">Requirements</a>
            </div>
            <form method="post" action="/content-plans/create-content">
              <label>Title<input name="title" placeholder="Canonical title" /></label>
              <label>Body<textarea name="body" rows="8" placeholder="Canonical source body"></textarea></label>
              <div class="editor-two-up">
                <label>Workspace<input name="workspace_id" value="linkedin" /></label>
                <label>Language<input name="language" placeholder="optional" /></label>
              </div>
              <button type="submit">Create content</button>
            </form>
          </section>
          <section class="card">
            <h2>Publication Plans</h2>
            <table>
              <thead><tr><th>Name</th><th>ID</th><th>Status</th><th>Targets</th><th>Snapshot</th><th>Actions</th></tr></thead>
              <tbody>{"".join(plan_rows) or "<tr><td colspan='6'>No publication plans yet.</td></tr>"}</tbody>
            </table>
          </section>
        </div>
        <div class="stack">
          <section class="card">
            <div class="card-heading">
              <div><h2>Execution</h2><p class="meta">Due {health.get("due_targets", 0)} · active leases {health.get("active_leases", 0)} · uncertain {health.get("uncertain_targets", 0)}</p></div>
              <a class="button secondary" href="/api/publication-execution/health">Health</a>
            </div>
            <div class="inline-actions">
              <a class="button secondary" href="/api/publication-execution/due?dry_run=1">Due dry-run</a>
              <form method="post" action="/content-plans/dispatch-due"><button type="submit">Dispatch due</button></form>
              <form method="post" action="/content-plans/reconcile"><button type="submit" class="secondary">Reconcile</button></form>
            </div>
            <table>
              <thead><tr><th>Target</th><th>Scheduled UTC</th><th>Status</th><th>Blockers</th></tr></thead>
              <tbody>{"".join(f"<tr><td><code>{html.escape(item.publication_target_id)}</code></td><td>{html.escape(item.resolved_scheduled_at_utc)}</td><td>{html.escape(item.status)}</td><td>{html.escape(', '.join(item.blockers) or 'ready')}</td></tr>" for item in due) or "<tr><td colspan='4'>No due targets.</td></tr>"}</tbody>
            </table>
          </section>
          <section class="card">
            <h2>Create Plan</h2>
            <form method="post" action="/content-plans/create-plan">
              <label>Content<select name="content_item_id">{item_options}</select></label>
              <label>Name<input name="name" placeholder="LinkedIn launch" /></label>
              <div class="editor-two-up">
                <label>Workspace<input name="workspace_id" value="linkedin" /></label>
                <label>Timezone<input name="timezone" value="Europe/Amsterdam" /></label>
              </div>
              <button type="submit">Create plan</button>
            </form>
          </section>
          <section class="card">
            <h2>Add LinkedIn Target</h2>
            <form method="post" action="/content-plans/add-target">
              <label>Plan ID<input name="plan_id" /></label>
              <label>Scheduled intent<input name="scheduled_at" placeholder="optional ISO timestamp" /></label>
              <input type="hidden" name="workspace_id" value="linkedin" />
              <input type="hidden" name="channel_plugin_id" value="channel.linkedin" />
              <input type="hidden" name="channel_account_id" value="linkedin" />
              <input type="hidden" name="capability" value="channel.publish.text" />
              <button type="submit">Add target</button>
            </form>
          </section>
        </div>
      </div>
    """


def render_content_calendar_page(config: AppConfig) -> str:
    runtime = get_plugin_runtime(config, reset=True, strict=False)
    scheduling = runtime.schedule_materialization_service(config)
    calendar_service = runtime.execution_calendar_service(config)
    campaign_service = runtime.campaign_service(config)
    workspace_id = "linkedin"
    now = datetime.now().astimezone()
    start = (now - timedelta(days=7)).isoformat(timespec="seconds")
    end = (now + timedelta(days=45)).isoformat(timespec="seconds")
    schedules = scheduling.schedule_repository.list_all(workspace_id=workspace_id)
    campaigns = campaign_service.campaign_repository.list_all(workspace_id=workspace_id)
    entries = calendar_service.list_calendar_entries(
        workspace_id=workspace_id,
        start=start,
        end=end,
        timezone="Europe/Amsterdam",
        limit=100,
    )
    schedule_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(schedule.name)}</td>
          <td><code>{html.escape(schedule.id)}</code></td>
          <td>{html.escape(schedule.status)}</td>
          <td>{html.escape(schedule.next_occurrence_at or schedule.starts_at_utc)}</td>
          <td>{html.escape(schedule.timezone)}</td>
          <td class="inline-actions">
            <form method="post" action="/content-calendar/materialize"><input type="hidden" name="schedule_id" value="{html.escape(schedule.id)}" /><button type="submit">Materialize</button></form>
            <form method="post" action="/content-calendar/pause"><input type="hidden" name="schedule_id" value="{html.escape(schedule.id)}" /><button type="submit" class="secondary">Pause</button></form>
            <form method="post" action="/content-calendar/resume"><input type="hidden" name="schedule_id" value="{html.escape(schedule.id)}" /><button type="submit" class="secondary">Resume</button></form>
            <form method="post" action="/content-calendar/cancel"><input type="hidden" name="schedule_id" value="{html.escape(schedule.id)}" /><button type="submit" class="danger">Cancel</button></form>
          </td>
        </tr>
        """
        for schedule in schedules[:25]
    )
    entry_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(entry.starts_at)}</td>
          <td>{html.escape(entry.entry_type)}</td>
          <td>{html.escape(entry.title)}</td>
          <td>{html.escape(entry.status)}</td>
          <td>{"yes" if entry.attention_required else "no"}</td>
          <td><code>{html.escape(entry.schedule_id or entry.plan_id or entry.target_id)}</code></td>
        </tr>
        """
        for entry in entries
    )
    campaign_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(campaign.name)}</td>
          <td><code>{html.escape(campaign.id)}</code></td>
          <td>{html.escape(campaign.status)}</td>
          <td class="inline-actions">
            <form method="post" action="/content-calendar/campaign-pause"><input type="hidden" name="campaign_id" value="{html.escape(campaign.id)}" /><button type="submit" class="secondary">Pause</button></form>
            <form method="post" action="/content-calendar/campaign-resume"><input type="hidden" name="campaign_id" value="{html.escape(campaign.id)}" /><button type="submit" class="secondary">Resume</button></form>
            <form method="post" action="/content-calendar/campaign-cancel"><input type="hidden" name="campaign_id" value="{html.escape(campaign.id)}" /><button type="submit" class="danger">Cancel</button></form>
          </td>
        </tr>
        """
        for campaign in campaigns[:25]
    )
    plan_options = "".join(
        f'<option value="{html.escape(plan.id)}">{html.escape(plan.name)} · {html.escape(plan.status)}</option>'
        for plan in runtime.publication_planning_service(config).plan_repository.list_all(workspace_id=workspace_id)
    )
    schedule_options = "".join(
        f'<option value="{html.escape(schedule.id)}">{html.escape(schedule.name)} · {html.escape(schedule.status)}</option>'
        for schedule in schedules
    )
    campaign_options = "".join(
        f'<option value="{html.escape(campaign.id)}">{html.escape(campaign.name)} · {html.escape(campaign.status)}</option>'
        for campaign in campaigns
    )
    return f"""
      <div class="page-grid">
        <div class="stack">
          <section class="card">
            <div class="card-heading">
              <div><h2>Execution Calendar</h2><p class="meta">Read-only range view for occurrences, targets, execution status, and campaign context.</p></div>
              <div class="inline-actions">
                <a class="button secondary" href="/api/scheduling/health">Health</a>
                <a class="button secondary" href="/api/execution-calendar?workspace_id=linkedin">API</a>
              </div>
            </div>
            <table>
              <thead><tr><th>Starts</th><th>Type</th><th>Title</th><th>Status</th><th>Attention</th><th>Source</th></tr></thead>
              <tbody>{entry_rows or "<tr><td colspan='6'>No calendar entries in range.</td></tr>"}</tbody>
            </table>
          </section>
          <section class="card">
            <h2>Schedules</h2>
            <table>
              <thead><tr><th>Name</th><th>ID</th><th>Status</th><th>Next</th><th>Timezone</th><th>Actions</th></tr></thead>
              <tbody>{schedule_rows or "<tr><td colspan='6'>No schedules yet.</td></tr>"}</tbody>
            </table>
          </section>
        </div>
        <div class="stack">
          <section class="card">
            <h2>Create Schedule</h2>
            <form method="post" action="/content-calendar/create-schedule">
              <label>Template plan<select name="source_publication_plan_id">{plan_options}</select></label>
              <label>Name<input name="name" placeholder="Weekly LinkedIn post" /></label>
              <div class="editor-two-up">
                <label>Start local<input name="starts_at_local" value="{html.escape(now.replace(hour=9, minute=0, second=0, microsecond=0).isoformat(timespec="seconds"))}" /></label>
                <label>Timezone<input name="timezone" value="Europe/Amsterdam" /></label>
              </div>
              <div class="editor-two-up">
                <label>Frequency<select name="frequency"><option>daily</option><option>weekly</option><option>monthly</option><option>once</option></select></label>
                <label>Count<input name="count" type="number" min="1" max="100" value="5" /></label>
              </div>
              <label><input type="checkbox" name="bounded_authorization" value="1" /> bounded schedule authorization</label>
              <button type="submit">Create schedule</button>
            </form>
          </section>
          <section class="card">
            <h2>Campaigns</h2>
            <table>
              <thead><tr><th>Name</th><th>ID</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>{campaign_rows or "<tr><td colspan='4'>No campaigns yet.</td></tr>"}</tbody>
            </table>
            <form method="post" action="/content-calendar/create-campaign">
              <label>Name<input name="name" placeholder="Campaign name" /></label>
              <button type="submit">Create campaign</button>
            </form>
            <form method="post" action="/content-calendar/add-campaign-member">
              <label>Campaign<select name="campaign_id">{campaign_options}</select></label>
              <label>Schedule<select name="member_id">{schedule_options}</select></label>
              <input type="hidden" name="member_type" value="publication_schedule" />
              <button type="submit" class="secondary">Add schedule</button>
            </form>
          </section>
        </div>
      </div>
    """


def render_instagram_page() -> str:
    return f"""
      <div class=\"page-grid\"><div class=\"stack\">{render_placeholder_card("Instagram", "Instagram workflow will be configured here later.")}</div></div>
    """


def render_analytics_page(config: AppConfig) -> str:
    runtime = get_plugin_runtime(config, reset=True, strict=False)
    bundle = runtime.analytics_bundle(config)
    readmodels = bundle.read_model_service
    workspace_id = "linkedin"
    definitions = bundle.metric_registry.list_definitions("channel.linkedin")
    runs = bundle.collection_run_repository.list_all(workspace_id=workspace_id)[:8]
    attributions = bundle.attribution_repository.list_all(workspace_id=workspace_id)[:20]
    observations = bundle.observation_repository.list_all(workspace_id=workspace_id)[-30:]
    publications = list_published_posts(channel_id=workspace_id)[:20]
    publication_rows = []
    for post in publications:
        try:
            perf = readmodels.publication_performance(post.id, workspace_id=workspace_id)
            latest = perf.get("latest_metrics", {})
            publication_rows.append(
                f"""
                <tr>
                  <td><code>{html.escape(post.id)}</code></td>
                  <td>{html.escape(post.external_id or "missing")}</td>
                  <td>{html.escape(str(perf.get("content_item_id") or ""))}</td>
                  <td>{html.escape(str(perf.get("revision_id") or ""))}</td>
                  <td>{html.escape(str(perf.get("attribution_status") or ""))}</td>
                  <td>{html.escape(str(perf.get("freshness") or "unknown"))}</td>
                  <td>{html.escape(", ".join(sorted(latest.keys())) or "none")}</td>
                </tr>
                """
            )
        except Exception:
            publication_rows.append(
                f"""
                <tr>
                  <td><code>{html.escape(post.id)}</code></td>
                  <td>{html.escape(post.external_id or "missing")}</td>
                  <td colspan="5">Attribution pending</td>
                </tr>
                """
            )
    definition_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(item.metric_key)}</td>
          <td>{html.escape(item.version)}</td>
          <td>{html.escape(item.semantic_type)}</td>
          <td>{html.escape(item.comparable_group)}</td>
          <td>{html.escape(item.aggregation_type)}</td>
        </tr>
        """
        for item in definitions
    )
    observation_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(item.metric_key)}</td>
          <td>{html.escape(str(item.observed_value))}</td>
          <td>{html.escape(item.observed_at)}</td>
          <td><code>{html.escape(item.publication_id)}</code></td>
          <td>{html.escape(item.status)}</td>
        </tr>
        """
        for item in observations
    )
    attribution_rows = "".join(
        f"""
        <tr>
          <td><code>{html.escape(item.publication_id)}</code></td>
          <td>{html.escape(item.status)}</td>
          <td>{html.escape(item.content_revision_id)}</td>
          <td>{html.escape(item.channel_variant_id or "direct")}</td>
          <td>{html.escape(item.campaign_id or "-")}</td>
          <td><code>{html.escape(item.attribution_checksum[:16])}</code></td>
        </tr>
        """
        for item in attributions
    )
    run_rows = "".join(
        f"""
        <tr>
          <td><code>{html.escape(run.id)}</code></td>
          <td>{html.escape(run.status)}</td>
          <td>{run.publication_count}</td>
          <td>{run.observation_count}</td>
          <td>{run.duplicate_count}</td>
          <td>{run.failure_count}</td>
          <td>{html.escape(run.started_at)}</td>
        </tr>
        """
        for run in runs
    )
    return f"""
      <div class="page-grid">
        <div class="stack">
          <section class="card">
            <div class="card-heading">
              <div>
                <h2>Analytics</h2>
                <p class="meta">Publication-level observations tied to content revisions, variants, media, schedules, and campaigns.</p>
              </div>
              <div class="inline-actions">
                <a class="button secondary" href="/api/analytics/health">Health</a>
                <a class="button secondary" href="/api/analytics/integrity?workspace_id=linkedin">Integrity</a>
              </div>
            </div>
            <form method="post" action="/analytics/collect" class="inline-actions">
              <button type="submit">Ingest existing snapshots</button>
              <a class="button secondary" href="/api/analytics/definitions/channel.linkedin">Definitions</a>
            </form>
            <table>
              <thead><tr><th>Publication</th><th>Remote ID</th><th>Content</th><th>Revision</th><th>Attribution</th><th>Freshness</th><th>Metrics</th></tr></thead>
              <tbody>{"".join(publication_rows) or "<tr><td colspan='7'>No analytics-ready publications yet.</td></tr>"}</tbody>
            </table>
          </section>
          <section class="card">
            <h2>Observations</h2>
            <table>
              <thead><tr><th>Metric</th><th>Value</th><th>Observed</th><th>Publication</th><th>Status</th></tr></thead>
              <tbody>{observation_rows or "<tr><td colspan='5'>No observations yet.</td></tr>"}</tbody>
            </table>
          </section>
        </div>
        <div class="stack">
          <section class="card">
            <h2>LinkedIn definitions</h2>
            <table>
              <thead><tr><th>Key</th><th>Version</th><th>Semantic</th><th>Comparable</th><th>Aggregation</th></tr></thead>
              <tbody>{definition_rows or "<tr><td colspan='5'>No definitions registered.</td></tr>"}</tbody>
            </table>
          </section>
          <section class="card">
            <h2>Attribution</h2>
            <table>
              <thead><tr><th>Publication</th><th>Status</th><th>Revision</th><th>Variant</th><th>Campaign</th><th>Checksum</th></tr></thead>
              <tbody>{attribution_rows or "<tr><td colspan='6'>No attribution records yet.</td></tr>"}</tbody>
            </table>
          </section>
          <section class="card">
            <h2>Collection runs</h2>
            <table>
              <thead><tr><th>Run</th><th>Status</th><th>Publications</th><th>Created</th><th>Duplicates</th><th>Failures</th><th>Started</th></tr></thead>
              <tbody>{run_rows or "<tr><td colspan='7'>No collection runs yet.</td></tr>"}</tbody>
            </table>
          </section>
        </div>
      </div>
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
    recent_items = (
        "".join(
            f"<tr><td>{html.escape(item.title)}</td><td>{html.escape(item.status)}</td><td>{html.escape(', '.join(item.channels) or '—')}</td><td>{html.escape(item.updated_at or item.created_at or 'Unknown')}</td></tr>"
            for item in content_items[:8]
        )
        or "<tr><td colspan='4'>No local content items yet.</td></tr>"
    )
    return f"""
      <div class=\"page-grid\">
        <div class=\"stack\">
          <section class=\"card\">
            <h2>Stats Dashboard</h2>
            <p class=\"meta\">Official APIs, exports, or manual imports should feed these cards later. Web scraping is intentionally not the default path.</p>
            <div class=\"summary-metrics\">
              <div class=\"summary-pill static\"><strong>{platform_counts["linkedin"]}</strong><span>LinkedIn publications</span></div>
              <div class=\"summary-pill static\"><strong>{platform_counts["instagram"]}</strong><span>Instagram publications</span></div>
              <div class=\"summary-pill static\"><strong>{platform_counts["substack"]}</strong><span>Substack publications</span></div>
              <div class=\"summary-pill static\"><strong>{platform_counts["x"]}</strong><span>X publications</span></div>
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
          {render_placeholder_card("LinkedIn post stats", "Impressions, reach, reactions, comments, shares, saves, clicks, and follower lift will appear here when the adapter is connected.")}
          {render_placeholder_card("Instagram insights", "Professional account and media insights will be surfaced here through the Meta API when configured.")}
          {render_placeholder_card("Substack import stats", f"Manual ZIP/CSV imports from {SUBSTACK_IMPORTS_DIRNAME} will be associated to local content by title, slug, or URL.")}
          {render_placeholder_card("X post stats", "X analytics can be attached here later if the account and API access are configured.")}
        </div>
      </div>
    """


def render_sidebar(active_route: str) -> str:
    channel_routes = {ROUTE_LINKEDIN, ROUTE_INSTAGRAM}
    items = []
    channel_items = []
    for route, icon_name, label, fallback in SIDEBAR_ITEMS:
        active = " active" if route == active_route else ""
        item = f'<a class="sidebar-link{active}" href="{route}"><span class="sidebar-icon">{render_sidebar_icon(icon_name, fallback)}</span><span class="sidebar-label">{html.escape(label)}</span></a>'
        if route in channel_routes:
            channel_items.append(item)
        else:
            items.append(item)
    channels_open = " open" if active_route in channel_routes else ""
    channels_active = " active" if active_route in channel_routes else ""
    channel_group = (
        f'<details class="sidebar-section"{channels_open}>'
        f'<summary class="sidebar-section-summary{channels_active}" aria-label="Toggle channel navigation">'
        f'<span class="sidebar-icon">{render_sidebar_icon("channels", "CH")}</span>'
        f'<span class="sidebar-label">Channels</span>'
        f'<span class="sidebar-section-chevron" aria-hidden="true"></span>'
        f"</summary>"
        f'<div class="sidebar-subnav">{"".join(channel_items)}</div>'
        f"</details>"
    )
    return f"""
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-top">
          <button class="sidebar-toggle" id="sidebar-toggle" type="button" aria-label="Toggle navigation"><span aria-hidden="true">|||</span></button>
        </div>
        <nav class="sidebar-nav" aria-label="Primary navigation">{"".join(items[:2])}{channel_group}{"".join(items[2:])}</nav>
      </aside>
    """


def _builtin_plugin_paths() -> dict[str, Path]:
    return {
        "channel.linkedin": ROOT_DIR / "channels" / "linkedin",
        "channel.mastodon": ROOT_DIR / "channels" / "mastodon",
    }


def _safe_plugin_report_payload(plugin_id: str, plugin_path: Path) -> dict[str, Any]:
    report = build_compatibility_report(plugin_path)
    return {
        "plugin_id": report.plugin_id if report.plugin_id != "unknown" else plugin_id,
        "version": report.plugin_version,
        "distribution": report.distribution,
        "sdk_version": report.sdk_version,
        "manifest_status": "valid" if report.compatibility_status != "invalid" else "invalid",
        "framework_compatibility": report.declared_contract_versions,
        "compatibility": report.compatibility_status,
        "capabilities": list(report.capabilities),
        "permissions": list(report.permissions),
        "contract_tests_status": "passed" if report.compatible else "failed",
        "fixture_status": report.fixture_status,
        "doctor_status": report.doctor_status,
        "warnings": list(report.warnings),
    }


def plugin_sdk_version_payload() -> dict[str, Any]:
    return {"plugin_sdk_version": PLUGIN_SDK_VERSION, "manifest_schema_version": "1.0"}


def plugin_compatibility_payload(plugin_id: str | None = None) -> dict[str, Any]:
    plugin_paths = _builtin_plugin_paths()
    if plugin_id:
        plugin_path = plugin_paths.get(plugin_id)
        if plugin_path is None:
            return {"error": {"code": "plugin_not_found", "message": "Plugin not found."}}
        return {"plugin": _safe_plugin_report_payload(plugin_id, plugin_path)}
    return {"plugins": [_safe_plugin_report_payload(pid, path) for pid, path in plugin_paths.items()]}


def _plugin_distribution_root() -> Path:
    return Path.home() / ".local" / "share" / "socialmediamanager" / "plugins"


def _plugin_distribution_cache() -> Path:
    return Path.home() / ".cache" / "socialmediamanager" / "plugin-registry"


def _plugin_quarantine_root() -> Path:
    return Path.home() / ".cache" / "socialmediamanager" / "plugin-quarantine"


def _plugin_host_environment_root() -> Path:
    return Path.home() / ".local" / "share" / "socialmediamanager" / "plugin-host-envs"


def _plugin_host_work_root() -> Path:
    return Path.home() / ".cache" / "socialmediamanager" / "plugin-host-work"


def _plugin_sandbox_root() -> Path:
    return Path.home() / ".local" / "share" / "socialmediamanager" / "plugin-sandbox"


def _fixture_registry_source() -> PluginRegistrySource:
    root = ROOT_DIR / "integrations" / "plugin_registry"
    return PluginRegistrySource(
        id="fixture",
        name="Community registry fixture",
        metadata_base_url=str(root / "metadata"),
        targets_base_url=str(root / "targets"),
        trusted_root_path=str(root / "trusted-root.json"),
        enabled=True,
        official=False,
        allow_download=True,
        allow_install=True,
        status="configured",
    )


def plugin_distribution_health_payload() -> dict[str, Any]:
    health = PluginDistributionIntegrityService(_plugin_distribution_root(), _plugin_quarantine_root()).health()
    return {
        "health": asdict(health),
        "labels": [
            "Registry metadata verified",
            "Artifact hash verified",
            "Signature valid",
            "Publisher identity matched",
            "SDK compatible",
            "Static checks passed",
            "Installed disabled",
            "Enabled",
            "Community maintained",
            "Official/builtin",
        ],
        "warning": "signed != safe; compatible != trustworthy; installed != enabled; enabled != official",
    }


def plugin_distribution_integrity_payload() -> dict[str, Any]:
    service = PluginDistributionIntegrityService(_plugin_distribution_root(), _plugin_quarantine_root())
    return {"issues": [asdict(item) for item in service.scan_installs() + service.scan_cache()]}


def plugin_registry_payload(plugin_id: str | None = None) -> dict[str, Any]:
    service = PluginRegistryService(_fixture_registry_source(), _plugin_distribution_cache())
    entries = service.list_plugins()
    if plugin_id:
        entries = [item for item in entries if item.plugin_id == plugin_id]
        return {"plugin": asdict(entries[0]) if entries else None}
    return {"plugins": [asdict(item) for item in entries]}


def plugin_installed_payload(plugin_id: str | None = None) -> dict[str, Any]:
    rows = PluginInstallationService(_plugin_distribution_root()).list_installed()
    safe_rows = [
        {
            "plugin_id": row.get("plugin_id"),
            "plugin_version": row.get("plugin_version"),
            "release_id": row.get("release_id"),
            "install_status": row.get("install_status"),
            "permissions": row.get("permissions", []),
            "installed_at": row.get("installed_at"),
            "enabled_at": row.get("enabled_at"),
            "artifact_sha256": str(row.get("artifact_sha256", ""))[:16],
        }
        for row in rows
        if not plugin_id or row.get("plugin_id") == plugin_id
    ]
    return {"plugins": safe_rows} if not plugin_id else {"plugin": safe_rows}


def plugin_host_process_payload(host_id: str | None = None) -> dict[str, Any]:
    installed = plugin_installed_payload()["plugins"]
    processes = []
    containment = PluginHostResourceController().containment_status()
    for row in installed:
        plugin_id = str(row.get("plugin_id") or "")
        version = str(row.get("plugin_version") or "")
        current_host_id = f"{plugin_id}=={version}"
        if host_id and host_id != current_host_id:
            continue
        processes.append(
            {
                "host_id": current_host_id,
                "plugin_id": plugin_id,
                "plugin_version": version,
                "execution_mode": "external_process",
                "environment_status": "prepared" if row.get("install_status") else "not_prepared",
                "process_status": "stopped",
                "protocol": PLUGIN_HOST_PROTOCOL_VERSION,
                "heartbeat": "not_started",
                "active_calls": 0,
                "memory_status": "not_sampled",
                "cpu_status": "not_sampled",
                "crash_count": 0,
                "restartbackoff": 0,
                "crashclassification": "",
                "resource_containment": containment,
                "warnings": ["venv is not an OS sandbox"],
            }
        )
    return {"processes": processes} if host_id is None else {"process": processes[0] if processes else None}


def plugin_host_health_payload() -> dict[str, Any]:
    processes = plugin_host_process_payload()["processes"]
    degraded = sum(1 for row in processes if row["resource_containment"] != "enforced")
    return {
        "status": "ready" if not degraded else "degraded",
        "framework_version": PLUGIN_HOST_FRAMEWORK_VERSION,
        "protocol_version": PLUGIN_HOST_PROTOCOL_VERSION,
        "active_hosts": len(processes),
        "degraded_hosts": degraded,
        "resource_containment": PluginHostResourceController().containment_status(),
        "warning": "process isolation contains crashes; it is not a full OS sandbox",
    }


def plugin_host_integrity_payload() -> dict[str, Any]:
    findings = PluginHostIntegrityService(
        _plugin_distribution_root(), _plugin_host_environment_root(), _plugin_host_work_root()
    ).scan()
    return {"findings": [asdict(finding) for finding in findings]}


def plugin_sandbox_health_payload() -> dict[str, Any]:
    return PluginSandboxIntegrityService(_plugin_sandbox_root()).to_public()


def plugin_sandbox_platform_payload() -> dict[str, Any]:
    return {"platform": asdict(select_sandbox_controller().inspect_platform())}


def plugin_sandbox_plan_payload(plugin_id: str | None = None) -> dict[str, Any]:
    rows = PluginInstallationService(_plugin_distribution_root()).list_installed()
    plans = []
    controller = select_sandbox_controller()
    compiler = SandboxPolicyCompiler()
    for row in rows:
        if plugin_id and row.get("plugin_id") != plugin_id:
            continue
        policy = compiler.build_policy(
            plugin_id=str(row.get("plugin_id")),
            plugin_version=str(row.get("plugin_version")),
            distribution_status=str(row.get("distribution_status") or "community"),
            permissions=list(row.get("permissions", [])),
            capabilities=[],
        )
        plan = controller.compile_plan(policy, context_from_install_record(row))
        plans.append(plan.to_dict())
    return {"plans": plans}


def markdown_website_profiles_payload(profile_id: str | None = None) -> dict[str, Any]:
    from channels.markdown_website.profiles import get_profile, list_profiles

    profiles = [get_profile(profile_id)] if profile_id else list_profiles()
    return {
        "profiles": [
            {
                "id": profile.id,
                "version": profile.version,
                "file_template": profile.file_template,
                "custom_frontmatter_allowlist": list(profile.custom_frontmatter_allowlist),
                "markdown_policy": dict(profile.markdown_policy),
            }
            for profile in profiles
        ],
        "raw_credentials_exposed": False,
        "absolute_paths_exposed": False,
    }


def markdown_website_accounts_payload(account_id: str | None = None) -> dict[str, Any]:
    account = {
        "id": account_id or "fixture-account",
        "channel_plugin_id": "channel.markdown_website",
        "channel_family": "owned_publication",
        "publisher_type": "git_repository",
        "repository_reference_id": "host_configured",
        "push_policy": "commit_only",
        "verification_policy": "public_url",
        "status": "requires_host_configuration",
    }
    return {"account": account} if account_id else {"accounts": [account]}


def markdown_website_preview_payload() -> dict[str, Any]:
    from channels.markdown_website.models import (
        MarkdownWebsiteAccountConfig,
        WebsitePublicationSnapshot,
        WebsiteVariant,
    )
    from channels.markdown_website.renderer import MarkdownRenderer

    now = datetime.now(UTC)
    account = MarkdownWebsiteAccountConfig(
        id="preview-account",
        workspace_id="preview-workspace",
        account_id="preview-site",
        display_name="Preview Site",
        repository_reference_id="host_configured",
        branch="main",
        content_root="articles",
        media_root="static/media",
        public_base_url="https://example.test",
        public_url_template="https://example.test/articles/{slug}",
        frontmatter_profile_id="generic_yaml",
    )
    snapshot = WebsitePublicationSnapshot(
        content_item_id="preview-content",
        content_revision_id="preview-revision",
        channel_variant_id="preview-variant",
        publication_plan_id="preview-plan",
        publication_target_id="preview-target",
        publication_attempt_id="preview-attempt",
        publication_snapshot_checksum="preview-snapshot",
        website_profile_id="generic_yaml",
        website_profile_version="1.0",
        account_config=account,
        variant=WebsiteVariant(
            title="Preview Article", markdown_body="# Preview\n\nWebsite preview.", published_at=now, updated_at=now
        ),
    )
    rendered = MarkdownRenderer().render(snapshot)
    return {
        "relative_path": rendered.relative_path,
        "public_url": rendered.public_url,
        "checksum": rendered.checksum,
        "markdown": rendered.markdown,
        "warnings": list(rendered.warnings),
    }


def publication_dependencies_payload() -> dict[str, Any]:
    graph = PublicationDependencyGraph()
    dependency = PublicationTargetDependency(
        id="website-before-social",
        plan_id="fixture-plan",
        predecessor_target_id="target-website",
        dependent_target_id="target-linkedin",
        required_state="publication_verified",
    )
    graph.add(dependency)
    return {"dependencies": [asdict(item) for item in graph.list()]}


def funnel_payload(content_item_id: str | None = None) -> dict[str, Any]:
    service = OwnedPublicationWorkspaceService()
    if content_item_id:
        return service.funnel(content_item_id)
    return {"funnels": [service.funnel()["model"]], "causality_claimed": False}


def owned_publication_service() -> OwnedPublicationWorkspaceService:
    return OwnedPublicationWorkspaceService()


def website_analytics_service():
    from src.core.website_analytics.service import WebsiteAnalyticsService

    return WebsiteAnalyticsService()


def website_instrumentation_service():
    from src.core.website_instrumentation.service import WebsiteInstrumentationService

    return WebsiteInstrumentationService()


def staging_analytics_service():
    from src.core.staging_analytics.service import StagingAnalyticsCertificationService

    return StagingAnalyticsCertificationService()


def certification_evidence_service():
    from src.core.certification_evidence.service import CertificationEvidenceService

    return CertificationEvidenceService()


def managed_secrets_service():
    from src.core.managed_secrets.service import configured_managed_secret_facade

    return configured_managed_secret_facade()


def trusted_signer_service():
    from src.core.managed_secrets.service import PurposeBoundSecretReader
    from src.core.trusted_signing.service import TrustedSignerService

    facade = managed_secrets_service()
    return TrustedSignerService(
        secret_reader=PurposeBoundSecretReader(facade, purpose="certification_signing", consumer="trusted_signer")
    )


def ci_artifact_service():
    from src.core.ci_artifacts.service import CiArtifactImportService

    return CiArtifactImportService()


def ci_operator_service():
    from src.core.ci_artifacts.operator_flow import CiEvidenceOperatorService

    return CiEvidenceOperatorService(import_service=ci_artifact_service())


def owned_publication_operations_payload() -> dict[str, Any]:
    service = owned_publication_service()
    health = service.operations_health()
    recovery = service.recovery()
    release = service.release_check_payload(require_certification=False)
    analytics = website_analytics_service().analytics_health()
    instrumentation = website_instrumentation_service().operations_health()
    staging = staging_analytics_service().operations_health()
    certification = certification_evidence_service()
    ci_artifacts = ci_artifact_service()
    trusted_signing = trusted_signer_service()
    managed_secrets = managed_secrets_service()
    return {
        "storage": health["storage"],
        "recovery": recovery,
        "workers": health["workers"],
        "metrics": health["metrics"],
        "website_analytics": analytics,
        "website_instrumentation": instrumentation,
        "staging_analytics": staging,
        "certification_evidence": certification.list_evidence(),
        "certification_readiness": certification.readiness(),
        "trusted_signing": trusted_signing.status(),
        "managed_secrets": managed_secrets.status(),
        "ci_artifacts": ci_artifacts.imports(),
        "ci_origins": ci_artifacts.origins(),
        "backups": service.backup_list(),
        "readiness": release["report"],
        "active_leases": int(health["metrics"]["owned_publication_active_leases"]),
        "expired_leases_released": recovery["expired_reconciliation_leases_released"],
        "queue_depth": len(service.reconciliation()["items"]),
        "readmodels": service.readmodels_status(),
        "phase20_2": service.phase20_2_status(),
    }


def render_website_analytics_page() -> str:
    service = website_analytics_service()
    providers = service.providers_payload()["providers"]
    accounts = service.list_accounts()["accounts"]
    provider_rows = "".join(
        f"<tr><td>{html.escape(item['provider_id'])}</td><td>{html.escape(item['provider_version'])}</td>"
        f"<td>{html.escape(item['data_access'])}</td><td>{len(item['capabilities'])}</td></tr>"
        for item in providers
    )
    account_rows = (
        "".join(
            f"<tr><td>{html.escape(item['id'])}</td><td>{html.escape(item['site_identifier'])}</td>"
            f"<td>{html.escape(item['status'])}</td><td>{html.escape(item['secret_reference_id'])}</td></tr>"
            for item in accounts
        )
        or "<tr><td colspan='4'>No analytics accounts configured.</td></tr>"
    )
    health = service.analytics_health()
    return f"""
    <section class="panel">
      <h2>Website Analytics Providers</h2>
      <table><thead><tr><th>Provider</th><th>Version</th><th>Access</th><th>Capabilities</th></tr></thead><tbody>{provider_rows}</tbody></table>
    </section>
    <section class="panel">
      <h2>Analytics Accounts</h2>
      <table><thead><tr><th>Account</th><th>Site</th><th>Status</th><th>Secret reference</th></tr></thead><tbody>{account_rows}</tbody></table>
    </section>
    <section class="panel">
      <h2>Data Quality</h2>
      <p>Publishing ready: {html.escape(str(health["publishing_ready"]))}</p>
      <p>Analytics ready: {html.escape(str(health["analytics_ready"]))}</p>
      <p>Freshness: {html.escape(str(health["data_freshness"]))}</p>
      <p>Attribution conflicts: {html.escape(str(health["attribution_conflicts"]))}</p>
    </section>
    """


def render_website_instrumentation_page() -> str:
    service = website_instrumentation_service()
    profiles = service.profiles_payload()["profiles"]
    configs = service.list_configs()["configs"]
    profile_rows = "".join(
        f"<tr><td>{html.escape(item['id'])}</td><td>{html.escape(item['website_framework'])}</td>"
        f"<td>{html.escape(item['analytics_provider_id'] or 'provider-neutral')}</td><td>{html.escape(item['consent_mode'])}</td></tr>"
        for item in profiles
    )
    config_rows = (
        "".join(
            f"<tr><td>{html.escape(item['id'])}</td><td>{html.escape(item['website_account_id'])}</td>"
            f"<td>{html.escape(item['analytics_account_id'])}</td><td>{html.escape(item['profile_id'])}</td></tr>"
            for item in configs
        )
        or "<tr><td colspan='4'>No instrumentation configs configured.</td></tr>"
    )
    health = service.operations_health()
    return f"""
    <section class="panel">
      <h2>Website Instrumentation</h2>
      <p>Instrumentation ready: {html.escape(str(health["instrumentation_ready"]))}</p>
      <p>Quality: {html.escape(str(health["quality"]))}</p>
      <p>Mapping drift: {html.escape(str(health["mapping_drift"]))}</p>
    </section>
    <section class="panel">
      <h2>Instrumentation Profiles</h2>
      <table><thead><tr><th>Profile</th><th>Framework</th><th>Provider</th><th>Consent</th></tr></thead><tbody>{profile_rows}</tbody></table>
    </section>
    <section class="panel">
      <h2>Instrumentation Configs</h2>
      <table><thead><tr><th>Config</th><th>Website</th><th>Analytics</th><th>Profile</th></tr></thead><tbody>{config_rows}</tbody></table>
    </section>
    """


def render_staging_analytics_page() -> str:
    service = staging_analytics_service()
    health = service.operations_health()
    profiles = service.list_profiles()["profiles"]
    runs = service.list_runs()["runs"]
    profile_rows = (
        "".join(
            f"<tr><td>{html.escape(item['id'])}</td><td>{html.escape(item['staging_origin_reference_id'])}</td>"
            f"<td>{html.escape(item['analytics_account_id'])}</td><td>{html.escape(str(item['enabled']))}</td></tr>"
            for item in profiles
        )
        or "<tr><td colspan='4'>No staging certification profiles configured.</td></tr>"
    )
    run_rows = (
        "".join(
            f"<tr><td>{html.escape(item['id'])}</td><td>{html.escape(item['status'])}</td>"
            f"<td>{html.escape(item['reconciliation_status'])}</td><td>{html.escape(item['run_id'])}</td></tr>"
            for item in runs[:10]
        )
        or "<tr><td colspan='4'>No staging certification runs.</td></tr>"
    )
    return f"""
    <section class="panel">
      <h2>Staging Analytics Certification</h2>
      <p>Latest status: {html.escape(str(health["latest_status"]))}</p>
      <p>Awaiting provider: {html.escape(str(health["awaiting_provider"]))}</p>
      <p>Uncertain browser events: {html.escape(str(health["uncertain_browser_events"]))}</p>
    </section>
    <section class="panel">
      <h2>Staging Profiles</h2>
      <table><thead><tr><th>Profile</th><th>Origin</th><th>Analytics</th><th>Enabled</th></tr></thead><tbody>{profile_rows}</tbody></table>
    </section>
    <section class="panel">
      <h2>Staging Runs</h2>
      <table><thead><tr><th>Run</th><th>Status</th><th>Reconciliation</th><th>Synthetic ID</th></tr></thead><tbody>{run_rows}</tbody></table>
    </section>
    """


def render_certification_evidence_page() -> str:
    service = certification_evidence_service()
    payload = service.list_evidence()
    readiness = service.readiness()
    signer_status = trusted_signer_service().status()
    ci_payload = ci_artifact_service().imports()
    ci_origins = ci_artifact_service().origins()
    evidence_rows = (
        "".join(
            f"<tr><td>{html.escape(item['package_id'])}</td><td>{html.escape(item['evidence_type'])}</td>"
            f"<td>{html.escape(item['trust_status'])}</td><td>{html.escape(item['freshness_status'])}</td>"
            f"<td>{html.escape(item['signature_status'])}</td><td>{html.escape((item.get('provenance') or {}).get('commit_sha', ''))}</td></tr>"
            for item in payload["evidence"]
        )
        or "<tr><td colspan='6'>No certification evidence imported.</td></tr>"
    )
    return f"""
    <section class="panel">
      <h2>Certification Evidence</h2>
      <p>Valid: {html.escape(str(readiness["certification_evidence_valid"]))}</p>
      <p>Trusted: {html.escape(str(readiness["certification_evidence_trusted"]))}</p>
      <p>Fresh: {html.escape(str(readiness["certification_evidence_fresh"]))}</p>
      <p>Remote CI: {html.escape(payload["remote_ci_status"]["artifact_status"])}</p>
      <p>Host signers: {html.escape(str(len(signer_status["signers"])))}</p>
      <p>CI origins: {html.escape(str(len(ci_origins["origins"])))}</p>
      <p>CI imports: {html.escape(str(len(ci_payload["imports"])))}</p>
    </section>
    <section class="panel">
      <h2>Evidence Packages</h2>
      <table><thead><tr><th>Evidence</th><th>Type</th><th>Trust</th><th>Freshness</th><th>Signature</th><th>Commit</th></tr></thead><tbody>{evidence_rows}</tbody></table>
    </section>
    """


def render_certification_operations_page() -> str:
    signers = trusted_signer_service().status()["signers"]
    secrets = managed_secrets_service().status()
    origins = ci_artifact_service().origins()["origins"]
    imports = ci_artifact_service().imports()["imports"]
    secret_rows = (
        "".join(
            f"<tr><td>{html.escape(item['id'])}</td><td>{html.escape(item['secret_type'])}</td>"
            f"<td>{html.escape(item['backend_id'])}</td><td>{html.escape(item['status'])}</td>"
            f"<td>{html.escape(', '.join(item.get('purpose_allowlist', ())))}</td>"
            f"<td>{html.escape(item.get('safe_fingerprint', '')[:16])}</td></tr>"
            for item in secrets["references"]
        )
        or "<tr><td colspan='6'>No managed secrets configured.</td></tr>"
    )
    signer_rows = (
        "".join(
            f"<tr><td>{html.escape(item['id'])}</td><td>{html.escape(item['algorithm_identifier'])}</td>"
            f"<td>{html.escape(item['status'])}</td><td>{html.escape(item.get('public_key_fingerprint', '')[:16])}</td>"
            f"<td>{html.escape('approved' if item.get('approved_by') else 'pending')}</td></tr>"
            for item in signers
        )
        or "<tr><td colspan='5'>No host signers configured.</td></tr>"
    )
    origin_rows = (
        "".join(
            f"<tr><td>{html.escape(item['id'])}</td>"
            f"<td>{html.escape(item['repository_owner'] + '/' + item['repository_name'])}</td>"
            f"<td>{html.escape(item['workflow_identity'])}</td><td>{html.escape(str(item['enabled']))}</td></tr>"
            for item in origins
        )
        or "<tr><td colspan='4'>No CI origins configured.</td></tr>"
    )
    import_rows = (
        "".join(
            f"<tr><td>{html.escape(item['id'])}</td><td>{html.escape(item['workflow_run_id'])}</td>"
            f"<td>{html.escape(item['artifact_id'])}</td><td>{html.escape(item['status'])}</td>"
            f"<td>{html.escape(item['expected_commit_sha'][:12])}</td></tr>"
            for item in imports
        )
        or "<tr><td colspan='5'>No CI imports requested.</td></tr>"
    )
    return f"""
    <section class="panel">
      <h2>Certification Operator Control</h2>
      <p>GitHub run success is not readiness until a concrete artifact is imported, verified, and reviewed.</p>
      <p>Managed secrets: {html.escape(str(secrets["managed_secrets_status"]))} · Vault: {html.escape(str(secrets["vault_health"].get("ready", False)))}</p>
    </section>
    <section class="panel">
      <h2>Managed Secrets</h2>
      <table><thead><tr><th>Reference</th><th>Type</th><th>Backend</th><th>Status</th><th>Purposes</th><th>Fingerprint</th></tr></thead><tbody>{secret_rows}</tbody></table>
    </section>
    <section class="panel">
      <h2>Signers</h2>
      <table><thead><tr><th>Signer</th><th>Algorithm</th><th>Status</th><th>Fingerprint</th><th>Approval</th></tr></thead><tbody>{signer_rows}</tbody></table>
    </section>
    <section class="panel">
      <h2>CI Origins</h2>
      <table><thead><tr><th>Origin</th><th>Repository</th><th>Workflow</th><th>Enabled</th></tr></thead><tbody>{origin_rows}</tbody></table>
    </section>
    <section class="panel">
      <h2>CI Imports</h2>
      <table><thead><tr><th>Import</th><th>Run</th><th>Artifact</th><th>Status</th><th>Commit</th></tr></thead><tbody>{import_rows}</tbody></table>
    </section>
    """


def render_github_ci_operator_page() -> str:
    service = ci_operator_service()
    status = service.status()
    readiness = status["readiness"]
    flows = status["flows"]
    dry_runs = status["dry_runs"]
    promotions = status["promotions"]
    flow_rows = (
        "".join(
            "<tr>"
            f"<td>{html.escape(item['id'])}</td><td>{html.escape(item['status'])}</td>"
            f"<td>{html.escape(item.get('expected_commit_sha', '')[:12])}</td>"
            f"<td>{html.escape(str(item.get('selected_run_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('selected_run_attempt', '')))}</td>"
            f"<td>{html.escape(str(item.get('selected_artifact_id', '')))}</td>"
            "</tr>"
            for item in flows
        )
        or "<tr><td colspan='6'>No GitHub CI operator flow has been started.</td></tr>"
    )
    dry_rows = (
        "".join(
            "<tr>"
            f"<td>{html.escape(item['id'])}</td><td>{html.escape(item['expected_result'])}</td>"
            f"<td>{html.escape(item['run_id'])}</td><td>{html.escape(str(item['run_attempt']))}</td>"
            f"<td>{html.escape(item['artifact_id'])}</td><td>{html.escape(item['provider_digest_status'])}</td>"
            "</tr>"
            for item in dry_runs
        )
        or "<tr><td colspan='6'>No dry-run report has been generated.</td></tr>"
    )
    promotion_rows = (
        "".join(
            "<tr>"
            f"<td>{html.escape(item['id'])}</td><td>{html.escape(item['target_commit_sha'][:12])}</td>"
            f"<td>{html.escape(item['trust_status'])}</td><td>{html.escape(item['freshness_status'])}</td>"
            "</tr>"
            for item in promotions
        )
        or "<tr><td colspan='4'>No CI evidence has been promoted for a commit.</td></tr>"
    )
    steps = [
        ("Managed credential", "complete" if readiness.get("remote_ci_status") != "credential_required" else "blocked"),
        ("CI-origin", "attention" if not flows else "complete"),
        ("Current commit", "complete"),
        ("Run discovery", "complete" if readiness["ci_run_found_for_current_commit"] else "not_started"),
        ("Artifact selection", "complete" if readiness["ci_artifact_selected_for_current_commit"] else "not_started"),
        ("Dry-run", "complete" if dry_runs else "not_started"),
        ("Import", "complete" if readiness["ci_artifact_imported_for_current_commit"] else "not_started"),
        ("Review", "complete" if readiness["ci_evidence_reviewed_for_current_commit"] else "not_started"),
        ("Promotion", "complete" if readiness["ci_evidence_promoted_for_current_commit"] else "not_started"),
    ]
    step_rows = "".join(
        f"<tr><td>{html.escape(label)}</td><td>{html.escape(state)}</td></tr>" for label, state in steps
    )
    return f"""
    <section class="panel">
      <h2>GitHub CI Evidence Operator Flow</h2>
      <p>Remote CI status: {html.escape(str(readiness["remote_ci_status"]))}</p>
      <p>Current commit: {html.escape(str(readiness.get("current_commit_sha", ""))[:12])}</p>
      <p>Artifact name is display only; identity uses origin, run, attempt and artifact ID.</p>
    </section>
    <section class="panel">
      <h2>Wizard Status</h2>
      <table><thead><tr><th>Step</th><th>Status</th></tr></thead><tbody>{step_rows}</tbody></table>
    </section>
    <section class="panel">
      <h2>Operator Flows</h2>
      <table><thead><tr><th>Flow</th><th>Status</th><th>Commit</th><th>Run</th><th>Attempt</th><th>Artifact ID</th></tr></thead><tbody>{flow_rows}</tbody></table>
    </section>
    <section class="panel">
      <h2>Dry-runs</h2>
      <table><thead><tr><th>Dry-run</th><th>Expected result</th><th>Run</th><th>Attempt</th><th>Artifact ID</th><th>Digest</th></tr></thead><tbody>{dry_rows}</tbody></table>
    </section>
    <section class="panel">
      <h2>Promotions</h2>
      <table><thead><tr><th>Promotion</th><th>Commit</th><th>Trust</th><th>Freshness</th></tr></thead><tbody>{promotion_rows}</tbody></table>
    </section>
    """


def render_owned_publication_operations_page() -> str:
    operations = owned_publication_operations_payload()
    readiness = operations["readiness"]
    worker_rows = "".join(
        "<tr>"
        f"<td>{html.escape(worker['worker_type'])}</td>"
        f"<td>{html.escape(worker['status'])}</td>"
        f"<td>{html.escape(worker['last_heartbeat'])}</td>"
        f"<td>{html.escape(str(worker['processed_items']))}</td>"
        f"<td>{html.escape(worker['last_error_code'])}</td>"
        "</tr>"
        for worker in operations["workers"]["workers"]
    )
    metrics_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(str(value))}</td></tr>"
        for name, value in operations["metrics"].items()
    )
    backup_rows = (
        "".join(
            "<tr>"
            f"<td>{html.escape(item['id'])}</td>"
            f"<td>{html.escape(item['status'])}</td>"
            f"<td>{html.escape(item['validation_status'])}</td>"
            f"<td>{html.escape(str(item['backup_size_bytes']))}</td>"
            "</tr>"
            for item in operations["backups"]["backups"]
        )
        or "<tr><td colspan='4'>No backups yet</td></tr>"
    )
    return f"""
      <section class="owned-operations" aria-labelledby="owned-operations-title">
        <h2 id="owned-operations-title">Owned publication operations</h2>
        <div class="workspace-grid">
          <article class="panel">
            <h3>Readiness</h3>
            <p>Owned operations: <strong>{html.escape(str(readiness["owned_publication_operations_ready"]))}</strong></p>
            <p>External plugin sandbox: <strong>{html.escape(str(readiness["external_plugin_sandbox_ready"]))}</strong></p>
            <p>Phase 20.2: {html.escape(str(operations["phase20_2"]["status"]))}</p>
          </article>
          <article class="panel">
            <h3>Storage</h3>
            <p>Ready: {html.escape(str(operations["storage"]["ready"]))}</p>
            <p>Schema: {html.escape(str(operations["storage"]["schema_version"]))} · Journal: {html.escape(str(operations["storage"]["journal_mode"]))}</p>
            <p>Database bytes: {html.escape(str(operations["storage"]["database_size_bytes"]))} · Free bytes: {html.escape(str(operations["storage"]["free_disk_bytes"]))}</p>
          </article>
          <article class="panel">
            <h3>Release gate</h3>
            <p>Browser certification: {html.escape(str(readiness["browser_certification_passed"]))}</p>
            <p>Worker certification: {html.escape(str(readiness["worker_certification_passed"]))}</p>
            <p>Required skips: {html.escape(str(readiness["required_certification_skips"]))}</p>
            <p>Evidence: {html.escape(str(readiness.get("deterministic_certification_status", "missing")))}</p>
            <p>Remote CI artifact: {html.escape(str(readiness.get("remote_ci_artifact_status", "artifact_not_imported")))}</p>
          </article>
        </div>
        <section class="panel"><h3>Workers</h3><table><thead><tr><th>Type</th><th>Status</th><th>Heartbeat</th><th>Processed</th><th>Error</th></tr></thead><tbody>{worker_rows}</tbody></table></section>
        <section class="panel"><h3>Backups</h3><table><thead><tr><th>ID</th><th>Status</th><th>Validation</th><th>Bytes</th></tr></thead><tbody>{backup_rows}</tbody></table></section>
        <section class="panel"><h3>Metrics</h3><table><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody>{metrics_rows}</tbody></table></section>
        {render_certification_evidence_page()}
        {render_certification_operations_page()}
        {render_github_ci_operator_page()}
      </section>
    """


def render_owned_publication_workspace_page() -> str:
    from src.core.owned_publication.validation import render_safe_markdown_preview

    workspace = owned_publication_service().workspace_payload()
    readiness = workspace["readiness"]
    variants = workspace["variants"]
    draft = workspace["draft"]
    timeline_rows = "".join(
        "<tr>"
        f"<td>{html.escape(event['timestamp'])}</td>"
        f"<td>{html.escape(event['phase'])}</td>"
        f"<td>{html.escape(event['mutation_state'])}</td>"
        f"<td>{html.escape(event['status'])}</td>"
        f"<td>{html.escape(event['safe_evidence_summary'])}</td>"
        "</tr>"
        for event in workspace["timeline"]
    )
    funnel_step_rows = []
    for step in workspace["funnel"]["steps"]:
        previous_rate = f"{step['rate_from_previous']:.1%}"
        first_rate = f"{step['rate_from_first']:.1%}"
        funnel_step_rows.append(
            "<tr>"
            f"<td>{html.escape(step['name'])}</td>"
            f"<td>{html.escape(str(step['count']))}</td>"
            f"<td>{html.escape(previous_rate)}</td>"
            f"<td>{html.escape(first_rate)}</td>"
            "</tr>"
        )
    funnel_steps = "".join(funnel_step_rows)
    dependency_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['predecessor_target_id'])}</td>"
        f"<td>{html.escape(item['required_state'])}</td>"
        f"<td>{html.escape(item['dependent_target_id'])}</td>"
        f"<td>{html.escape(str(workspace['dependency_graph']['claimable'].get(item['dependent_target_id'], False)))}</td>"
        "</tr>"
        for item in workspace["dependency_graph"]["dependencies"]
    )
    validation_rows = (
        "".join(
            "<li>"
            f"<strong>{html.escape(item['severity'])}</strong> "
            f"{html.escape(item['scope'])}: {html.escape(item['message'])}"
            "</li>"
            for item in workspace["validation"]
        )
        or "<li><strong>info</strong> workspace: ready</li>"
    )
    unsafe_preview_fixture = render_safe_markdown_preview(
        "Normal **Markdown**\n\n<script>window.__unsafe = true</script>\n"
        '<img src=x onerror="window.__unsafe = true">\n'
        '<a href="javascript:window.__unsafe=true">unsafe</a>\n'
        '<iframe src="https://example.invalid"></iframe>'
    )
    evidence_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['channel'])}</td>"
        f"<td>{html.escape(item['target_id'])}</td>"
        f"<td>{html.escape(item['verification_status'])}</td>"
        f"<td>{html.escape(item.get('relative_path') or item.get('public_url') or '')}</td>"
        "</tr>"
        for item in workspace["evidence"]
    )
    reconciliation_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['category'])}</td>"
        f"<td>{html.escape(item['severity'])}</td>"
        f"<td>{html.escape(item['recommended_read_only_check'])}</td>"
        f"<td>{html.escape(item['allowed_repair'])}</td>"
        "</tr>"
        for item in workspace["reconciliation_queue"]
    )
    return f"""
      <section class="owned-workspace" aria-labelledby="owned-workspace-title">
        <nav class="tabs" aria-label="Owned publication workflow">
          <a href="/content">Compose</a><a href="/content/{html.escape(workspace["content_item_id"])}/publish">Plan</a>
          <a href="/publications/{html.escape(workspace["publication_plan"]["id"])}">Publishing</a>
          <a href="/funnels/{html.escape(workspace["content_item_id"])}">Performance</a>
        </nav>
        <div class="workspace-grid">
          <article class="panel workspace-editor">
            <h2 id="owned-workspace-title">Article composer</h2>
            <form id="owned-composer-form" data-content-id="{html.escape(workspace["content_item_id"])}" data-version="{html.escape(str(draft["version"]))}">
              <label>Title <input id="owned-title" name="title" value="{html.escape(draft["title"])}" aria-describedby="title-validation"></label>
              <label for="owned-summary">Summary</label><textarea id="owned-summary" name="summary" rows="3">{html.escape(draft["summary"])}</textarea>
              <label for="owned-language">Language</label><select id="owned-language" name="language"><option selected>{html.escape(draft["language"])}</option><option>nl</option><option>en</option></select>
              <label for="owned-author">Author</label><input id="owned-author" name="author" value="{html.escape(draft["author"])}">
              <label for="owned-tags">Tags</label><input id="owned-tags" name="tags" value="{html.escape(", ".join(draft["tags"]))}">
              <label for="owned-hero">Hero image</label><select id="owned-hero" name="hero_media_asset_id"><option value="media-hero-fixture">Fixture hero image</option></select>
              <label for="owned-seo">SEO description</label><input id="owned-seo" name="seo_description" value="Durable owned publication operations">
              <label for="owned-cta">CTA label</label><input id="owned-cta" name="cta_label" value="Read the guide">
              <label for="owned-body">Markdown body</label><textarea id="owned-body" name="markdown_body" rows="12">{html.escape(draft["markdown_body"])}</textarea>
              <p id="autosave-status" class="meta" role="status" aria-live="polite">Autosave: debounced · saved · version {html.escape(str(draft["version"]))} · body is not written to operational logs.</p>
              <p id="conflict-status" class="meta" role="alert" tabindex="-1"></p>
              <button id="create-revision" type="button">Create immutable revision</button>
              <button id="create-plan" type="button">Create publication plan</button>
            </form>
            <p id="title-validation" class="meta">Active immutable revision {html.escape(workspace["active_revision"]["id"])} remains bound to scheduled targets until explicitly replaced.</p>
          </article>
          <article class="panel">
            <h2>Channel variants</h2>
            <div class="tabs" role="tablist" aria-label="Channel variants"><button role="tab" aria-selected="true" tabindex="0">Website</button><button role="tab" aria-selected="false" tabindex="-1">LinkedIn</button><button role="tab" aria-selected="false" tabindex="-1">Mastodon</button></div>
            <h3>Website</h3><label for="frontmatter-profile">Frontmatter profile</label><select id="frontmatter-profile"><option>generic_yaml</option><option>hugo</option></select><p>{html.escape(variants["website"]["checksum"])}</p>
            <h3>LinkedIn</h3><label for="linkedin-variant">LinkedIn variant</label><textarea id="linkedin-variant" rows="4">{html.escape(variants["linkedin"]["text"])}</textarea><p id="linkedin-attribution">UTM source linkedin · attribution attr-linkedin</p>
            <h3>Mastodon</h3><label for="mastodon-variant">Mastodon variant</label><textarea id="mastodon-variant" rows="4">{html.escape(variants["mastodon"]["text"])}</textarea><p id="mastodon-attribution">UTM source mastodon · attribution attr-mastodon</p>
            <p class="meta">Generation actions create draft variants only and require explicit acceptance.</p>
          </article>
          <article class="panel">
            <h2>Preview and validation</h2>
            <p><strong>Public URL</strong> {html.escape(workspace["website_preview"]["public_url"])}</p>
            <p><strong>Content path</strong> {html.escape(workspace["website_preview"]["relative_path"])}</p>
            <pre>{html.escape(workspace["frontmatter_preview"])}</pre>
            <div id="markdown-preview" aria-label="Markdown preview">{workspace["markdown_preview_html"]}</div>
            <div id="unsafe-preview-fixture" aria-label="Unsafe preview fixture">{unsafe_preview_fixture}</div>
            <ul id="validation-errors">{validation_rows}</ul>
            <p>Overall readiness: <strong>{html.escape(readiness["overall"])}</strong></p>
            <button id="publish-plan" type="button" aria-describedby="publish-help" disabled>Publish website</button>
            <p id="publish-help" class="meta">Disabled until validation and dependencies are ready.</p>
          </article>
        </div>
        <section class="panel"><h2>Dependency graph</h2><table><thead><tr><th>Predecessor</th><th>Required state</th><th>Dependent</th><th>Unlocked</th></tr></thead><tbody>{dependency_rows}</tbody></table></section>
        <section class="panel"><h2>Execution timeline</h2><table><thead><tr><th>Time</th><th>Phase</th><th>Mutation</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{timeline_rows}</tbody></table></section>
        <section class="panel"><h2>Evidence viewer</h2><table><thead><tr><th>Channel</th><th>Target</th><th>Status</th><th>Safe reference</th></tr></thead><tbody>{evidence_rows}</tbody></table></section>
        <section class="panel"><h2>Reconciliation queue</h2><button id="reconciliation-check" type="button">Run read-only reconciliation check</button><p id="reconciliation-status" role="status" aria-live="polite"></p><table><thead><tr><th>Category</th><th>Severity</th><th>Read-only check</th><th>Safe repair</th></tr></thead><tbody>{reconciliation_rows}</tbody></table></section>
        <section class="panel"><h2>Funnel dashboard</h2><table><thead><tr><th>Step</th><th>Count</th><th>From previous</th><th>From start</th></tr></thead><tbody>{funnel_steps}</tbody></table><p class="meta">No causality claim is made from correlated channel and website metrics.</p></section>
      </section>
      <script>
      (() => {{
        const form = document.querySelector("#owned-composer-form");
        if (!form) return;
        const status = document.querySelector("#autosave-status");
        const conflict = document.querySelector("#conflict-status");
        let version = Number(form.dataset.version || "1");
        let timer = 0;
        let requestCount = 0;
        window.__ownedPublicationAutosaveRequests = 0;
        window.__ownedPublicationMutationRequests = 0;
        const body = () => ({{
          expected_version: version,
          title: document.querySelector("#owned-title").value,
          summary: document.querySelector("#owned-summary").value,
          markdown_body: document.querySelector("#owned-body").value,
          language: document.querySelector("#owned-language").value,
          author: document.querySelector("#owned-author").value,
          tags: document.querySelector("#owned-tags").value.split(",").map((value) => value.trim()).filter(Boolean),
          idempotency_key: "browser-autosave-" + form.dataset.contentId + "-" + version + "-" + requestCount
        }});
        async function autosave() {{
          requestCount += 1;
          window.__ownedPublicationAutosaveRequests += 1;
          status.textContent = "Autosave: saving";
          try {{
            const response = await fetch("/api/content/" + encodeURIComponent(form.dataset.contentId), {{
              method: "PATCH",
              headers: {{"Content-Type": "application/json"}},
              body: JSON.stringify(body())
            }});
            const payload = await response.json();
            if (response.status === 409) {{
              conflict.textContent = "Conflict: newer draft version is available.";
              conflict.focus();
              status.textContent = "Autosave: conflict";
              return;
            }}
            if (!response.ok) throw new Error(payload.error ? payload.error.code : "autosave.failed");
            version = payload.draft.version;
            form.dataset.version = String(version);
            status.textContent = "Autosave: saved · version " + version;
            conflict.textContent = "";
          }} catch (error) {{
            status.textContent = "Autosave: error";
          }}
        }}
        function scheduleAutosave() {{
          status.textContent = "Autosave: pending";
          clearTimeout(timer);
          timer = setTimeout(autosave, 250);
        }}
        form.querySelectorAll("input, textarea, select").forEach((field) => field.addEventListener("input", scheduleAutosave));
        document.querySelectorAll('[role="tab"]').forEach((tab, index, tabs) => {{
          tab.addEventListener("keydown", (event) => {{
            if (!["ArrowRight", "ArrowLeft"].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : (index + tabs.length - 1) % tabs.length;
            tabs.forEach((item) => {{ item.setAttribute("aria-selected", "false"); item.tabIndex = -1; }});
            tabs[next].setAttribute("aria-selected", "true");
            tabs[next].tabIndex = 0;
            tabs[next].focus();
          }});
        }});
        document.querySelector("#create-revision").addEventListener("click", async () => {{
          const response = await fetch("/api/content/" + encodeURIComponent(form.dataset.contentId) + "/revisions", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{expected_version: version, idempotency_key: "browser-revision-" + version}})
          }});
          const payload = await response.json();
          status.textContent = response.ok ? "Revision created: " + payload.revision.id : "Revision error";
        }});
        document.querySelector("#create-plan").addEventListener("click", async () => {{
          const response = await fetch("/api/publication-plans", {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: "{{}}" }});
          window.__ownedPublicationMutationRequests += 1;
          status.textContent = response.ok ? "Publication plan created" : "Publication plan error";
        }});
        document.querySelector("#reconciliation-check").addEventListener("click", async () => {{
          const response = await fetch("/api/reconciliation/rec-deployment-pending/check", {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: "{{}}" }});
          const payload = await response.json();
          document.querySelector("#reconciliation-status").textContent = response.ok && payload.read_only ? "Read-only reconciliation resolved without mutation" : "Reconciliation check failed";
        }});
      }})();
      </script>
    """


def render_plugins_page() -> str:
    builtin_payload = plugin_compatibility_payload()
    registry_payload = plugin_registry_payload()
    installed_payload = plugin_installed_payload()
    host_payload = plugin_host_process_payload()
    sandbox_health = plugin_sandbox_health_payload()["health"]
    health = plugin_distribution_health_payload()["health"]
    sections = [
        "<nav class='tabs'><span>installed</span><span>available</span><span>updates</span><span>quarantined</span><span>registry health</span><span>Plugin Hosts</span><span>OS Sandbox</span></nav>",
        f"<article class='panel'><h3>Distribution</h3><p>{html.escape(health['status'])} · framework {html.escape(PLUGIN_DISTRIBUTION_FRAMEWORK_VERSION)}</p><p>signed != safe · installed != enabled · activation requires restart</p></article>",
        f"<article class='panel'><h3>Plugin Hosts</h3><p>framework {html.escape(PLUGIN_HOST_FRAMEWORK_VERSION)} · protocol {html.escape(PLUGIN_HOST_PROTOCOL_VERSION)}</p><p>External code runs out of process after restart. Virtualenv isolation is not a sandbox.</p></article>",
        f"<article class='panel'><h3>OS Sandbox</h3><p>{html.escape(str(sandbox_health['controller_status']))} · framework {html.escape(PLUGIN_SANDBOX_FRAMEWORK_VERSION)}</p><p>Direct network is blocked; HTTP and browser access are brokered callbacks.</p></article>",
    ]
    for row in installed_payload["plugins"]:
        perms = "".join(
            f"<span class='pill muted'>{html.escape(str(perm))}</span>" for perm in row.get("permissions", [])
        )
        sections.append(
            "<article class='panel plugin-card'>"
            f"<h3>{html.escape(str(row['plugin_id']))}</h3>"
            f"<p>{html.escape(str(row['plugin_version']))} · {html.escape(str(row['install_status']))} · artifact {html.escape(str(row['artifact_sha256']))}</p>"
            f"<div class='pill-row'>{perms}</div>"
            "<p>Actions remain separate: download and verify, review, install disabled, enable after restart.</p>"
            "</article>"
        )
    for host in host_payload["processes"]:
        sections.append(
            "<article class='panel plugin-card'>"
            f"<h3>{html.escape(str(host['plugin_id']))}</h3>"
            f"<p>{html.escape(str(host['plugin_version']))} · {html.escape(str(host['execution_mode']))} · {html.escape(str(host['process_status']))}</p>"
            f"<p>Environment: {html.escape(str(host['environment_status']))} · Protocol: {html.escape(str(host['protocol']))} · Heartbeat: {html.escape(str(host['heartbeat']))}</p>"
            f"<p>Calls: {html.escape(str(host['active_calls']))} · Memory: {html.escape(str(host['memory_status']))} · CPU: {html.escape(str(host['cpu_status']))}</p>"
            f"<p>Crashes: {html.escape(str(host['crash_count']))} · Backoff: {html.escape(str(host['restartbackoff']))} · Containment: {html.escape(str(host['resource_containment']))}</p>"
            f"<p>Crash classification: {html.escape(str(host['crashclassification'] or 'none'))}</p>"
            f"<p>Sandbox: {html.escape(str(sandbox_health['controller_status']))} · Filesystem isolation: allowlist · Network isolation: direct deny · Syscall isolation: platform attested</p>"
            "</article>"
        )
    for plugin in builtin_payload["plugins"]:
        caps = "".join(f"<span class='pill'>{html.escape(cap)}</span>" for cap in plugin["capabilities"])
        perms = "".join(f"<span class='pill muted'>{html.escape(perm)}</span>" for perm in plugin["permissions"])
        warnings = ", ".join(plugin["warnings"]) or "none"
        sections.append(
            "<article class='panel plugin-card'>"
            f"<h3>{html.escape(plugin['plugin_id'])}</h3>"
            f"<p>{html.escape(plugin['version'])} · {html.escape(plugin['distribution'])} · {html.escape(plugin['compatibility'])}</p>"
            f"<div class='pill-row'>{caps}</div>"
            f"<div class='pill-row'>{perms}</div>"
            f"<p>Fixture: {html.escape(plugin['fixture_status'])} · Doctor: {html.escape(plugin['doctor_status'])}</p>"
            f"<p>Warnings: {html.escape(warnings)}</p>"
            "</article>"
        )
    for entry in registry_payload["plugins"]:
        caps = "".join(f"<span class='pill'>{html.escape(cap)}</span>" for cap in entry["capabilities"])
        sections.append(
            "<article class='panel plugin-card'>"
            f"<h3>{html.escape(entry['plugin_id'])}</h3>"
            f"<p>{html.escape(entry['latest_version'])} · {html.escape(entry['distribution_status'])} · {html.escape(entry['sdk_compatibility'])}</p>"
            f"<div class='pill-row'>{caps}</div>"
            f"<p>Publisher identity: {html.escape(entry['signer_identity_summary'])}</p>"
            "</article>"
        )
    return "<section class='stack plugin-admin'>" + "".join(sections) + "</section>"


def render_main_content(
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
) -> tuple[str, str, str]:
    if route == ROUTE_EDITOR:
        return "", "", render_editor_page(config, content_items, selected_content_item)
    if route == ROUTE_DRAFTS:
        return "", "", render_drafts_page(config, content_items, selected_content_item)
    if route == ROUTE_SCHEDULER:
        return (
            "Scheduler",
            "Schedule Queue and Worker Runs",
            render_scheduler_page(all_records, queue, selected_record, selected_status),
        )
    if route == ROUTE_STATS:
        return "Stats", "Central analytics workspace for local content items", render_stats_page(content_items)
    if route == ROUTE_INSTAGRAM:
        return "Instagram", "Instagram workflow placeholder", render_instagram_page()
    if route == ROUTE_CONFIG:
        return "Config", "System and workflow configuration", render_config_page(config)
    if route == ROUTE_MEDIA:
        return (
            "Media Library",
            "Shared product media, relations, usage, and retention",
            render_media_library_page(config),
        )
    if route == ROUTE_CONTENT_PLANS:
        return (
            "Content Plans",
            "Canonical content, channel variants, and publication planning",
            render_content_planning_page(config),
        )
    if route == ROUTE_CONTENT_CALENDAR:
        return (
            "Execution Calendar",
            "Recurring schedules, occurrences, and campaign coordination",
            render_content_calendar_page(config),
        )
    if route == ROUTE_ANALYTICS:
        return (
            "Analytics",
            "Content-aware publication attribution and performance readmodels",
            render_analytics_page(config),
        )
    if route == ROUTE_CONTENT:
        return (
            "Content",
            "Owned publication workspace for article, website, social variants, and previews",
            render_owned_publication_workspace_page(),
        )
    if route == ROUTE_PUBLICATIONS:
        return (
            "Publications",
            "Website-first plans, dependencies, execution timeline, and evidence",
            render_owned_publication_workspace_page(),
        )
    if route == ROUTE_FUNNELS:
        return (
            "Funnels",
            "Website, social, CTA, and conversion performance tied to content revisions",
            render_owned_publication_workspace_page(),
        )
    if route == ROUTE_OPERATIONS:
        return (
            "Operations",
            "Release gates, workers, storage health, backups, and recovery",
            render_owned_publication_operations_page(),
        )
    if route == ROUTE_PLUGINS:
        return (
            "Plugins",
            "SDK compatibility, capabilities, and developer readiness",
            render_plugins_page(),
        )
    assert snapshot is not None
    return (
        "LinkedIn",
        "Current LinkedIn workflow and article drafting tools",
        render_linkedin_page(config, snapshot, preview, all_records),
    )


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
    page_title, page_intro, page_content = render_main_content(
        route,
        config,
        snapshot,
        all_records,
        queue,
        preview,
        selected_record,
        selected_status,
        content_items,
        selected_content_item,
    )
    header_markup = (
        '<header class="page-header">'
        f'<div><p class="page-kicker">{html.escape(route.strip("/") or "editor")}</p>'
        f'<h1 class="page-title">{html.escape(page_title)}</h1>'
        f'<p class="page-subtitle">{html.escape(page_intro)}</p></div>'
        f'<p class="page-feed meta">RSS feed <code>{html.escape(config.rss_url)}</code></p>'
        "</header>"
        if page_title or page_intro
        else ""
    )
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>SocialMediaManager</title>
  <style>
    :root {{
      --bg: #09090b;
      --bg-soft: #111113;
      --panel: #18181b;
      --panel-raised: #202124;
      --line: #3f3f46;
      --text: #f4f4f5;
      --muted: #a1a1aa;
      --muted-strong: #d4d4d8;
      --accent: #3f3f46;
      --accent-strong: #a1a1aa;
      --accent-2: #52525b;
      --danger: #a1a1aa;
      --info: #a1a1aa;
      --radius: 8px;
      --sidebar-width: 268px;
      --sidebar-collapsed-width: 76px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #111113 0%, var(--bg) 42%, #050505 100%);
      color: var(--text);
      line-height: 1.5;
    }}
    a {{ color: inherit; }}
    :focus-visible {{ outline: 2px solid var(--accent-strong); outline-offset: 3px; }}
    .skip-link {{
      position: fixed; left: 16px; top: 12px; z-index: 100; transform: translateY(-160%);
      background: var(--accent); color: #f4f4f5; padding: 10px 12px; border-radius: var(--radius);
      font-weight: 800; text-decoration: none; transition: transform 0.2s ease;
    }}
    .skip-link:focus {{ transform: translateY(0); }}
    .app-shell {{ display: flex; min-height: 100vh; }}
    .sidebar {{
      width: var(--sidebar-width);
      background: linear-gradient(180deg, rgba(12, 12, 14, 0.98), rgba(7, 7, 8, 0.94));
      border-right: 1px solid rgba(113, 113, 122, 0.20);
      padding: 14px 12px;
      position: sticky;
      top: 0;
      height: 100vh;
      transition: width 0.2s ease, transform 0.2s ease;
      z-index: 20;
    }}
    .sidebar-top {{ display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-bottom: 16px; }}
    .sidebar-toggle {{
      border: 1px solid rgba(113, 113, 122, 0.22); border-radius: var(--radius);
      background: rgba(31, 31, 35, 0.78); color: var(--text);
      width: 38px; height: 38px; cursor: pointer; font-size: 13px;
      transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
    }}
    .sidebar-toggle:hover {{
      background: rgba(39, 39, 42, 0.92);
      border-color: rgba(161, 161, 170, 0.24);
      transform: translateY(-1px);
    }}
    .sidebar-nav {{ display: grid; gap: 6px; }}
    .sidebar-section {{ display: grid; gap: 6px; }}
    .sidebar-section-summary {{
      display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 8px 10px;
      border: 1px solid transparent; border-radius: var(--radius); color: var(--muted);
      cursor: pointer; list-style: none; user-select: none;
      transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
    }}
    .sidebar-section-summary::-webkit-details-marker {{ display: none; }}
    .sidebar-section-summary:hover {{ background: rgba(244, 244, 245, 0.06); border-color: rgba(113, 113, 122, 0.20); color: var(--text); }}
    .sidebar-section-summary.active {{ background: rgba(63, 63, 70, 0.70); color: var(--text); border-color: rgba(161, 161, 170, 0.26); box-shadow: inset 3px 0 0 var(--accent); }}
    .sidebar-section-chevron {{
      width: 8px; height: 8px; margin-left: auto; border-right: 2px solid currentColor; border-bottom: 2px solid currentColor;
      transform: rotate(45deg); transition: transform 0.2s ease; opacity: 0.72; flex-shrink: 0;
    }}
    .sidebar-section[open] .sidebar-section-chevron {{ transform: rotate(225deg); }}
    .sidebar-subnav {{ display: grid; gap: 4px; padding-left: 18px; }}
    .sidebar-subnav .sidebar-link {{ min-height: 42px; }}
    .sidebar-link {{
      display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 8px 10px;
      border: 1px solid transparent; border-radius: var(--radius); text-decoration: none;
      color: var(--muted); transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
    }}
    .sidebar-link:hover {{ background: rgba(244, 244, 245, 0.06); border-color: rgba(113, 113, 122, 0.20); color: var(--text); }}
    .sidebar-link.active {{
      background: rgba(63, 63, 70, 0.70);
      color: var(--text); border-color: rgba(161, 161, 170, 0.26);
      box-shadow: inset 3px 0 0 var(--accent);
    }}
    .sidebar-icon {{
      width: 32px; height: 32px; border-radius: var(--radius); background: rgba(244, 244, 245, 0.07);
      display: inline-flex; align-items: center; justify-content: center; font-weight: 700; flex-shrink: 0;
      color: currentColor;
    }}
    .sidebar-icon svg {{
      width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.8;
      stroke-linecap: round; stroke-linejoin: round;
    }}
    .sidebar-fallback {{ font-size: 11px; letter-spacing: 0.08em; }}
    .sidebar-label {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 14px; font-weight: 600; }}
    .main-shell {{ flex: 1; min-width: 0; transition: margin 0.2s ease, width 0.2s ease; }}
    .wrap {{ max-width: 1360px; margin: 0 auto; padding: 28px 24px 40px; }}
    .page-header {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 18px; margin-bottom: 24px; padding-bottom: 18px; border-bottom: 1px solid rgba(113, 113, 122, 0.18); }}
    .page-kicker {{ margin: 0 0 7px; color: var(--accent-strong); font-size: 12px; font-weight: 800; text-transform: uppercase; }}
    .page-title {{ margin: 0; font-size: 30px; line-height: 1.1; }}
    .page-subtitle {{ margin: 8px 0 0; color: var(--muted); max-width: 68ch; }}
    .page-feed {{ max-width: min(460px, 42vw); overflow-wrap: anywhere; text-align: right; }}
    .page-grid {{ display: grid; gap: 20px; grid-template-columns: minmax(0, 1.15fr) minmax(320px, .85fr); }}
    .stack {{ display: grid; gap: 20px; align-content: start; }}
    .card {{
      position: relative;
      background: rgba(24, 24, 27, 0.94);
      border: 1px solid rgba(113, 113, 122, 0.18);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: 0 18px 48px rgba(6, 5, 4, 0.34);
      min-width: 0;
    }}
    .card::before {{ content: ""; position: absolute; inset: 0 auto 0 0; width: 3px; border-radius: var(--radius) 0 0 var(--radius); background: rgba(113, 113, 122, 0.18); }}
    .compact-card {{ padding: 18px 20px; }}
    .card-heading {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .meta {{ color: var(--muted); font-size: 14px; }}
    p {{ margin-top: 0; }}
    .teaser {{ white-space: pre-wrap; line-height: 1.6; word-break: break-word; }}
    .inline-link {{ color: var(--accent); text-decoration: none; }}
    label {{ display: block; margin: 14px 0 6px; color: var(--muted); font-size: 14px; }}
    input, select, textarea {{
      width: 100%; border-radius: var(--radius); border: 1px solid var(--line); background: #101012; color: var(--text); padding: 12px; font: inherit;
    }}
    textarea {{ min-height: 180px; resize: vertical; }}
    .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; }}
    .inline-form {{ margin: 0; }}
    button, .button {{
      border: 0; border-radius: var(--radius); background: var(--accent); color: #f4f4f5; padding: 11px 16px; font-weight: 800; cursor: pointer; text-decoration: none;
      min-height: 40px; display: inline-flex; align-items: center; justify-content: center;
    }}
    button:hover, .button:hover {{ filter: brightness(1.06); }}
    .secondary {{ background: rgba(63, 63, 70, 0.58); color: #f4f4f5; border: 1px solid rgba(161, 161, 170, 0.24); }}
    .nav-chip {{ background: rgba(244, 244, 245, 0.07); color: var(--text); border: 1px solid rgba(113, 113, 122, 0.18); }}
    .nav-chip.active {{ background: rgba(63, 63, 70, 0.76); outline: 1px solid rgba(161, 161, 170, 0.30); }}
    .filter-bar {{ align-items: center; padding: 10px; background: rgba(10, 10, 12, 0.52); border: 1px solid rgba(113, 113, 122, 0.16); border-radius: var(--radius); }}
    .summary-metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 10px; margin: 16px 0 6px; }}
    .summary-pill {{
      display: grid; gap: 4px; text-decoration: none; padding: 12px; border-radius: var(--radius);
      background: rgba(244, 244, 245, 0.06); border: 1px solid rgba(113, 113, 122, 0.16);
    }}
    .summary-pill.static {{ cursor: default; }}
    .summary-pill strong {{ font-size: 20px; }}
    .summary-pill span {{ color: var(--muted); font-size: 13px; }}
    .config-tabs {{ display: grid; gap: 14px; }}
    .config-tab-input {{ position: absolute; opacity: 0; pointer-events: none; }}
    .config-tab-list {{
      display: flex; gap: 6px; flex-wrap: wrap; padding: 6px; border-radius: var(--radius);
      background: rgba(10, 10, 12, 0.52); border: 1px solid rgba(113, 113, 122, 0.16);
    }}
    .config-tab-label {{
      display: inline-flex; align-items: center; justify-content: center; min-height: 36px; padding: 0 12px;
      border-radius: var(--radius); color: var(--muted); cursor: pointer; font-size: 13px; font-weight: 800;
      border: 1px solid transparent; user-select: none;
    }}
    .config-tab-label:hover {{ color: var(--text); background: rgba(244, 244, 245, 0.06); }}
    .config-tab-panels {{ min-width: 0; }}
    .config-tab-panel {{ display: none; }}
    #config-tab-overview:checked ~ .config-tab-list label[for="config-tab-overview"],
    #config-tab-system:checked ~ .config-tab-list label[for="config-tab-system"],
    #config-tab-browser:checked ~ .config-tab-list label[for="config-tab-browser"],
    #config-tab-article:checked ~ .config-tab-list label[for="config-tab-article"],
    #config-tab-channels:checked ~ .config-tab-list label[for="config-tab-channels"] {{
      color: var(--text); background: rgba(63, 63, 70, 0.76); border-color: rgba(161, 161, 170, 0.30);
    }}
    #config-tab-overview:checked ~ .config-tab-panels .config-panel-overview,
    #config-tab-system:checked ~ .config-tab-panels .config-panel-system,
    #config-tab-browser:checked ~ .config-tab-panels .config-panel-browser,
    #config-tab-article:checked ~ .config-tab-panels .config-panel-article,
    #config-tab-channels:checked ~ .config-tab-panels .config-panel-channels {{ display: block; }}
    .config-summary {{ display: grid; gap: 10px; }}
    .config-item {{
      display: grid; gap: 6px; padding: 12px 14px; border-radius: var(--radius);
      background: rgba(244, 244, 245, 0.055); border: 1px solid rgba(113, 113, 122, 0.16);
    }}
    .config-label {{ color: var(--muted); font-size: 13px; }}
    .readonly-config-list {{ display: grid; gap: 0; margin: 14px 0 0; }}
    .readonly-config-list div {{
      display: grid; grid-template-columns: minmax(150px, 220px) minmax(0, 1fr); gap: 12px;
      padding: 10px 0; border-top: 1px solid rgba(113, 113, 122, 0.16);
    }}
    .readonly-config-list div:first-child {{ border-top: 0; }}
    .readonly-config-list dt {{ color: var(--muted); font-size: 13px; font-weight: 700; }}
    .readonly-config-list dd {{ margin: 0; min-width: 0; overflow-wrap: anywhere; }}
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
    body.route-editor .editor-main > .card::before {{ display: none; }}
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
      background: rgba(12, 12, 14, 0.80);
      border: 1px solid rgba(113, 113, 122, 0.12);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 22px 60px rgba(2, 6, 23, 0.28);
    }}
    .editor-primary-fields-inline {{
      max-width: none;
      margin: 0;
      padding: 18px 24px 8px;
      border-bottom: 1px solid rgba(113, 113, 122, 0.10);
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
      color: #f4f4f5;
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
      color: #d4d4d8;
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
      background: rgba(18, 18, 20, 0.86);
      border: 1px solid rgba(113, 113, 122, 0.12);
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
      color: #e4e4e7;
    }}
    .editor-panel-icon {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 26px;
      height: 26px;
      border-radius: 8px;
      background: rgba(39, 39, 42, 0.86);
      color: #d4d4d8;
      border: 1px solid rgba(63, 63, 70, 0.88);
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
      border-right: 2px solid #a1a1aa;
      border-bottom: 2px solid #a1a1aa;
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
    .ai-chat-panel {{ gap: 8px; }}
    .editor-ai-prompt {{
      min-height: 72px;
      resize: vertical;
      border-radius: 12px;
      border: 1px solid rgba(63, 63, 70, 0.88);
      background: rgba(18, 18, 20, 0.90);
      color: #d4d4d8;
      padding: 10px 11px;
      font: inherit;
      line-height: 1.45;
    }}
    .ai-chat-actions {{ display: flex; justify-content: flex-end; }}
    .editor-panel-button {{
      justify-self: start;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border-radius: 10px;
      border: 1px solid rgba(161, 161, 170, 0.22);
      background: rgba(63, 63, 70, 0.42);
      color: #d4d4d8;
      font-size: 12px;
      font-weight: 700;
      transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
    }}
    .editor-panel-button:hover {{
      background: rgba(63, 63, 70, 0.58);
      border-color: rgba(161, 161, 170, 0.30);
      color: #f4f4f5;
    }}
    .editor-panel-button.subtle {{
      min-height: 30px;
      padding: 0 10px;
      border-color: rgba(82, 82, 91, 0.88);
      background: rgba(39, 39, 42, 0.86);
      color: #d4d4d8;
      font-weight: 600;
    }}
    .editor-ai-feedback {{
      margin: 0;
      min-height: 0;
    }}
    .editor-ai-feedback:empty {{ display: none; }}
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
      border-top: 1px solid rgba(63, 63, 70, 0.50);
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
      color: #e4e4e7;
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
      background: rgba(8, 8, 10, 0.96);
      border: 1px solid rgba(63, 63, 70, 0.88);
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
      border-left: 1px solid rgba(63, 63, 70, 0.88);
    }}
    .editor-toolbar button,
    .editor-toolbar a.editor-toolbar-action {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      background: rgba(39, 39, 42, 0.86);
      color: #d4d4d8;
      padding: 0;
      border-radius: 10px;
      border: 1px solid rgba(63, 63, 70, 0.88);
      font-weight: 600;
      text-decoration: none;
      transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
    }}
    .editor-toolbar button:hover,
    .editor-toolbar a.editor-toolbar-action:hover {{
      background: rgba(63, 63, 70, 0.95);
      border-color: rgba(82, 82, 91, 0.92);
      color: #f4f4f5;
      transform: translateY(-1px);
    }}
    .editor-toolbar button svg,
    .editor-toolbar a.editor-toolbar-action svg {{
      width: 17px;
      height: 17px;
      fill: currentColor;
      stroke: currentColor;
      stroke-width: 0.6;
      flex-shrink: 0;
    }}
    .editor-toolbar button.is-active {{
      background: rgba(10, 10, 12, 0.98);
      color: #a1a1aa;
      border-color: rgba(161, 161, 170, 0.30);
      box-shadow: inset 0 0 0 1px rgba(161, 161, 170, 0.18);
    }}
    .editor-toolbar-action {{
      background: rgba(18, 18, 20, 0.96);
    }}
    .editor-toolbar-action.secondary {{
      background: rgba(39, 39, 42, 0.86);
    }}
    .editor-drop-hint {{
      display: none;
      align-items: center;
      justify-content: center;
      padding: 16px;
      border-radius: 18px;
      border: 1px dashed rgba(161, 161, 170, 0.30);
      background: rgba(63, 63, 70, 0.32);
      color: #d4d4d8;
      font-size: 14px;
      font-weight: 600;
    }}
    .editor-column.drag-over .editor-drop-hint {{
      display: flex;
    }}
    .editor-column.drag-over .editor-writing-surface {{
      border-color: rgba(161, 161, 170, 0.30);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 0 0 3px rgba(161, 161, 170, 0.16), 0 22px 60px rgba(2, 6, 23, 0.28);
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
      color: #f4f4f5;
    }}
    .tiptap-editor .ProseMirror p.is-editor-empty:first-child::before {{
      color: #71717a;
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
      color: #f4f4f5;
    }}
    .tiptap-editor .ProseMirror h1 {{ font-size: 2.2rem; }}
    .tiptap-editor .ProseMirror h2 {{ font-size: 1.75rem; }}
    .tiptap-editor .ProseMirror h3 {{ font-size: 1.4rem; }}
    .tiptap-editor .ProseMirror blockquote {{
      margin: 1.5em 0;
      padding-left: 1.1rem;
      border-left: 3px solid rgba(161, 161, 170, 0.34);
      color: #d4d4d8;
    }}
    .tiptap-editor .ProseMirror pre {{
      background: #050505;
      border: 1px solid rgba(113, 113, 122, 0.16);
      color: #d4d4d8;
      padding: 16px 18px;
      border-radius: 16px;
      overflow-x: auto;
      font-size: 0.95rem;
      line-height: 1.65;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .tiptap-editor .ProseMirror code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      background: rgba(113, 113, 122, 0.14);
      border-radius: 6px;
      padding: 0.15em 0.35em;
      color: #d4d4d8;
    }}
    .tiptap-editor .ProseMirror pre code {{
      background: transparent;
      padding: 0;
      color: inherit;
    }}
    .tiptap-editor .ProseMirror hr {{
      border: 0;
      border-top: 1px solid rgba(113, 113, 122, 0.22);
      margin: 2.2rem 0;
    }}
    .tiptap-editor .ProseMirror img {{
      display: block;
      max-width: min(100%, 720px);
      border-radius: 18px;
      margin: 2rem auto;
      box-shadow: 0 20px 45px rgba(2, 6, 23, 0.42);
      border: 1px solid rgba(113, 113, 122, 0.16);
      background: rgba(18, 18, 20, 0.92);
    }}
    .tiptap-editor .ProseMirror img.ProseMirror-selectednode {{
      outline: 3px solid rgba(161, 161, 170, 0.30);
      outline-offset: 3px;
    }}
    .tiptap-editor .ProseMirror a {{
      color: #a1a1aa;
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
      border: 1px solid rgba(63, 63, 70, 0.88);
      background: rgba(8, 8, 10, 0.96);
      color: #d4d4d8;
      transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
    }}
    .editor-preview-back:hover {{
      background: rgba(39, 39, 42, 0.95);
      border-color: rgba(82, 82, 91, 0.92);
      color: #f4f4f5;
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
      background: rgba(24, 24, 27, 0.60);
      border: 1px solid rgba(63, 63, 70, 0.70);
      color: #d4d4d8;
    }}
    .cover-preview {{
      border-radius: 16px;
      overflow: hidden;
      background: rgba(24, 24, 27, 0.80);
      border: 1px solid rgba(113, 113, 122, 0.14);
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
    .checkbox-grid label {{ margin: 0; padding: 10px 12px; border: 1px solid rgba(113, 113, 122, 0.16); border-radius: 12px; background: rgba(113, 113, 122, 0.06); }}
    .content-list {{ display: grid; gap: 10px; }}
    .content-link {{
      display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 12px; border-radius: var(--radius);
      background: rgba(244, 244, 245, 0.05); border: 1px solid rgba(113, 113, 122, 0.16);
    }}
    .content-link-main {{ display: grid; gap: 4px; min-width: 0; flex: 1; text-decoration: none; }}
    .content-link span {{ color: var(--muted); font-size: 13px; }}
    .content-link.active {{ border-color: rgba(161, 161, 170, 0.30); background: rgba(63, 63, 70, 0.42); }}
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
      border-radius: var(--radius);
      background: rgba(18, 18, 20, 0.98);
      border: 1px solid rgba(113, 113, 122, 0.18);
      box-shadow: 0 18px 50px rgba(6, 5, 4, 0.45);
      z-index: 5;
    }}
    .content-link-menu-items form {{ margin: 0; }}
    .content-link-menu-items button {{
      width: 100%;
      padding: 10px 12px;
      border-radius: var(--radius);
      background: rgba(31, 31, 35, 0.92);
      color: var(--text);
      text-align: left;
      font-weight: 600;
    }}
    .content-link-menu-items button.danger {{
      background: rgba(39, 39, 42, 0.95);
      color: #f4f4f5;
    }}
    .markdown-preview {{
      border: 1px solid rgba(113, 113, 122, 0.18); border-radius: var(--radius); padding: 18px;
      background: rgba(18, 18, 20, 0.72); min-height: 320px;
    }}
    .markdown-preview h1, .markdown-preview h2, .markdown-preview h3 {{ margin-top: 0; }}
    .markdown-preview p, .markdown-preview li {{ line-height: 1.7; }}
    .markdown-preview pre, .frontmatter-preview {{
      overflow-x: auto; padding: 16px; border-radius: var(--radius); background: rgba(10, 10, 12, 0.92);
      border: 1px solid rgba(113, 113, 122, 0.16); color: var(--muted-strong); white-space: pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th, td {{ text-align: left; padding: 11px 8px; border-bottom: 1px solid rgba(113,113,122,0.18); vertical-align: top; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; font-weight: 800; }}
    tbody tr:hover td {{ background: rgba(244, 244, 245, 0.035); }}
    code {{ color: var(--accent-strong); overflow-wrap: anywhere; }}
    .status-ok {{ color: #d4d4d8; }}
    .status-warn {{ color: #a1a1aa; }}
    .status-bad {{ color: #d4d4d8; }}
    .status-badge {{
      display: inline-flex; align-items: center; min-height: 24px; padding: 3px 8px; border-radius: 999px;
      font-size: 12px; font-weight: 800; background: rgba(113, 113, 122, 0.16); color: var(--muted-strong);
      border: 1px solid rgba(113, 113, 122, 0.18); vertical-align: middle;
    }}
    .status-queued, .status-idle {{ background: rgba(63, 63, 70, 0.38); border-color: rgba(161, 161, 170, 0.22); color: #f4f4f5; }}
    .status-processing, .status-running {{ background: rgba(113, 113, 122, 0.20); border-color: rgba(161, 161, 170, 0.26); color: #d4d4d8; }}
    .status-done, .status-success {{ background: rgba(63, 63, 70, 0.42); border-color: rgba(161, 161, 170, 0.24); color: #f4f4f5; }}
    .status-failed {{ background: rgba(63, 63, 70, 0.38); border-color: rgba(161, 161, 170, 0.22); color: #f4f4f5; }}
    .empty-state {{ padding: 22px; border: 1px dashed rgba(113, 113, 122, 0.22); border-radius: var(--radius); color: var(--muted); background: rgba(10, 10, 12, 0.32); text-align: center; }}
    body.sidebar-collapsed .sidebar {{ width: var(--sidebar-collapsed-width); }}
    body.sidebar-collapsed .sidebar-label {{ display: none; }}
    body.sidebar-collapsed .sidebar-top {{ justify-content: center; }}
    body.sidebar-collapsed .sidebar-link {{ justify-content: center; padding-left: 0; padding-right: 0; }}
    body.sidebar-collapsed .sidebar-section-summary {{ justify-content: center; padding-left: 0; padding-right: 0; }}
    body.sidebar-collapsed .sidebar-section-chevron {{ display: none; }}
    body.sidebar-collapsed .sidebar-subnav {{ padding-left: 0; }}
    @media (max-width: 980px) {{
      .page-grid {{ grid-template-columns: 1fr; }}
      .editor-two-up, .checkbox-grid, .editor-studio, .writer-layout, .editor-workbench {{ grid-template-columns: 1fr; }}
      .editor-sidebar-panel, .editor-rail {{ position: static; }}
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
      .page-header {{ align-items: flex-start; flex-direction: column; }}
      .page-feed {{ max-width: 100%; text-align: left; }}
    }}
  </style>
</head>
<body class="route-{html.escape(route.strip("/") or "root")}">
  <a class=\"skip-link\" href=\"#main-content\">Skip to content</a>
  <div class=\"app-shell\">
    {render_sidebar(route)}
    <main class=\"main-shell\" id=\"main-content\" tabindex=\"-1\">
      <div class=\"wrap\">
        {header_markup}
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
            self.send_header(
                "Content-Type",
                (mime_type or "application/octet-stream")
                + ("; charset=utf-8" if (mime_type or "").startswith(("text/", "application/javascript")) else ""),
            )
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
                    "logs": [
                        record.__dict__ for record in list_channel_job_logs(channel_id=channel_id or None, limit=40)
                    ],
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
        if parsed.path == "/health/live":
            json_response(self, {"status": "alive", "liveness": True})
            return
        if parsed.path == "/health/ready":
            health = owned_publication_service().operations_health()
            status = HTTPStatus.OK if health["readiness"]["ready"] else HTTPStatus.SERVICE_UNAVAILABLE
            json_response(self, health["readiness"], status=status)
            return
        if parsed.path == "/api/operations/health":
            json_response(self, owned_publication_service().operations_health())
            return
        if parsed.path == "/api/operations/release-check":
            json_response(self, owned_publication_service().release_check_payload(require_certification=False))
            return
        if parsed.path == "/api/operations/backups":
            json_response(self, owned_publication_service().backup_list())
            return
        if parsed.path.startswith("/api/operations/backups/"):
            suffix = parsed.path.removeprefix("/api/operations/backups/")
            parts = suffix.split("/")
            if len(parts) == 1:
                json_response(self, owned_publication_service().backup_show(parts[0]))
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
        if parsed.path.startswith("/api/channels/mastodon"):
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            mastodon = runtime.get_plugin_service("channel.mastodon", "channel_runtime", require_ready=False)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == "/api/channels/mastodon/health":
                    json_response(self, {"health": mastodon.health_check()})
                    return
                if parsed.path == "/api/channels/mastodon/integrity":
                    json_response(self, mastodon.integrity())
                    return
                if parsed.path == "/api/channels/mastodon/oauth/callback":
                    account_id = query.get("channel_account_id", [""])[0]
                    workspace_id = query.get("workspace_id", ["mastodon"])[0]
                    payload = mastodon.complete_connect(
                        code=query.get("code", [""])[0],
                        state=query.get("state", [""])[0],
                        workspace_id=workspace_id,
                        channel_account_id=account_id,
                    )
                    json_response(self, {"account": payload})
                    return
                marker = "/api/channels/mastodon/accounts/"
                if parsed.path.startswith(marker):
                    suffix = parsed.path.removeprefix(marker)
                    parts = suffix.split("/")
                    account_id = parts[0]
                    action = parts[1] if len(parts) > 1 else "status"
                    if action == "status":
                        json_response(self, {"account": mastodon.status(channel_account_id=account_id)})
                        return
                    if action == "requirements":
                        json_response(
                            self,
                            {
                                "content": mastodon.resolve_content_requirements(channel_account_id=account_id),
                                "media": mastodon.resolve_media_requirements(channel_account_id=account_id),
                            },
                        )
                        return
                    if action == "health":
                        json_response(self, {"health": mastodon.health_check(channel_account_id=account_id)})
                        return
            except Exception as exc:
                json_response(
                    self,
                    {
                        "error": {
                            "code": getattr(exc, "code", "mastodon_api_error"),
                            "message": str(getattr(exc, "safe_message", str(exc))),
                        }
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if parsed.path == "/api/plugin-distribution/health":
            json_response(self, plugin_distribution_health_payload())
            return
        if parsed.path == "/api/plugin-distribution/integrity":
            json_response(self, plugin_distribution_integrity_payload())
            return
        if parsed.path == "/api/plugin-registry/sources":
            json_response(self, {"sources": [asdict(_fixture_registry_source())]})
            return
        if parsed.path == "/api/plugin-registry/plugins":
            json_response(self, plugin_registry_payload())
            return
        if parsed.path.startswith("/api/plugin-registry/plugins/"):
            suffix = parsed.path.removeprefix("/api/plugin-registry/plugins/")
            if suffix.endswith("/releases"):
                plugin_id = suffix.removesuffix("/releases")
                payload = plugin_registry_payload(plugin_id)
                versions = payload.get("plugin", {}).get("available_versions", []) if payload.get("plugin") else []
                json_response(self, {"releases": versions})
                return
            json_response(self, plugin_registry_payload(suffix))
            return
        if parsed.path.startswith("/api/plugin-registry/releases/") and parsed.path.endswith("/verification"):
            release_id = parsed.path.removeprefix("/api/plugin-registry/releases/").removesuffix("/verification")
            json_response(self, {"release_id": release_id, "status": "metadata_only", "code_imported": False})
            return
        if parsed.path.startswith("/api/plugin-registry/downloads/"):
            json_response(
                self,
                {
                    "download_id": parsed.path.rsplit("/", maxsplit=1)[-1],
                    "status": "metadata_only",
                    "code_imported": False,
                },
            )
            return
        if parsed.path == "/api/plugins/installed":
            json_response(self, plugin_installed_payload())
            return
        if parsed.path.startswith("/api/plugins/installed/"):
            json_response(self, plugin_installed_payload(parsed.path.removeprefix("/api/plugins/installed/")))
            return
        if parsed.path == "/api/plugin-host/health":
            json_response(self, plugin_host_health_payload())
            return
        if parsed.path == "/api/plugin-host/processes":
            json_response(self, plugin_host_process_payload())
            return
        if parsed.path.startswith("/api/plugin-host/processes/"):
            suffix = parsed.path.removeprefix("/api/plugin-host/processes/")
            parts = suffix.split("/")
            host_id = parts[0]
            if len(parts) == 1:
                json_response(self, plugin_host_process_payload(host_id))
                return
            leaf = parts[1]
            if leaf == "requests":
                json_response(self, {"host_id": host_id, "requests": []})
                return
            if leaf == "crashes":
                json_response(self, {"host_id": host_id, "crashes": []})
                return
            if leaf == "resources":
                json_response(
                    self,
                    {
                        "host_id": host_id,
                        "resources": PluginHostResourceController().to_public(),
                    },
                )
                return
        if parsed.path == "/api/plugin-host/integrity":
            json_response(self, plugin_host_integrity_payload())
            return
        if parsed.path == "/api/plugin-sandbox/health":
            json_response(self, plugin_sandbox_health_payload())
            return
        if parsed.path == "/api/plugin-sandbox/platform":
            json_response(self, plugin_sandbox_platform_payload())
            return
        if parsed.path == "/api/plugin-sandbox/policies":
            json_response(self, {"policies": plugin_sandbox_plan_payload()["plans"]})
            return
        if parsed.path.startswith("/api/plugin-sandbox/policies/"):
            json_response(self, {"policy_id": parsed.path.rsplit("/", maxsplit=1)[-1], "status": "metadata_only"})
            return
        if parsed.path == "/api/plugin-sandbox/plans":
            json_response(self, plugin_sandbox_plan_payload())
            return
        if parsed.path.startswith("/api/plugin-sandbox/plans/"):
            json_response(self, {"plan_id": parsed.path.rsplit("/", maxsplit=1)[-1], "status": "metadata_only"})
            return
        if parsed.path == "/api/plugin-sandbox/attestations":
            json_response(self, {"attestations": [], "status": "no_active_external_hosts"})
            return
        if parsed.path.startswith("/api/plugin-sandbox/attestations/"):
            json_response(self, {"attestation_id": parsed.path.rsplit("/", maxsplit=1)[-1], "status": "metadata_only"})
            return
        if parsed.path == "/api/plugin-sandbox/violations":
            json_response(
                self,
                {
                    "violations": [
                        asdict(item) for item in PluginSandboxIntegrityService(_plugin_sandbox_root()).violations.list()
                    ]
                },
            )
            return
        if parsed.path == "/api/plugin-sandbox/integrity":
            json_response(self, plugin_sandbox_health_payload())
            return
        if parsed.path == "/api/plugin-sdk/version":
            json_response(self, plugin_sdk_version_payload())
            return
        if parsed.path == "/api/plugins/compatibility":
            json_response(self, plugin_compatibility_payload())
            return
        if parsed.path.startswith("/api/plugins/") and parsed.path.endswith("/compatibility"):
            plugin_id = parsed.path.removeprefix("/api/plugins/").removesuffix("/compatibility").replace("%2E", ".")
            payload = plugin_compatibility_payload(plugin_id)
            status = HTTPStatus.NOT_FOUND if "error" in payload else HTTPStatus.OK
            json_response(self, payload, status=status)
            return
        if parsed.path == "/api/plugins/health":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            body = json.dumps(runtime.health_payload(), ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/channels/markdown-website/accounts":
            json_response(self, markdown_website_accounts_payload())
            return
        if parsed.path.startswith("/api/channels/markdown-website/accounts/"):
            suffix = parsed.path.removeprefix("/api/channels/markdown-website/accounts/")
            account_id = suffix.split("/", maxsplit=1)[0]
            json_response(self, markdown_website_accounts_payload(account_id))
            return
        if parsed.path == "/api/channels/markdown-website/profiles":
            json_response(self, markdown_website_profiles_payload())
            return
        if parsed.path.startswith("/api/channels/markdown-website/profiles/"):
            json_response(
                self,
                markdown_website_profiles_payload(parsed.path.removeprefix("/api/channels/markdown-website/profiles/")),
            )
            return
        if parsed.path == "/api/publication-dependencies":
            json_response(self, publication_dependencies_payload())
            return
        if parsed.path == "/api/analytics/funnels":
            json_response(self, funnel_payload())
            return
        if parsed.path == "/api/analytics/providers":
            json_response(self, website_analytics_service().providers_payload())
            return
        if parsed.path == "/api/analytics/staging/profiles":
            json_response(self, staging_analytics_service().list_profiles())
            return
        if parsed.path.startswith("/api/analytics/staging/profiles/"):
            profile_id = parsed.path.removeprefix("/api/analytics/staging/profiles/").split("/")[0]
            json_response(self, staging_analytics_service().profile(profile_id))
            return
        if parsed.path == "/api/analytics/staging/runs":
            json_response(self, staging_analytics_service().list_runs())
            return
        if parsed.path.startswith("/api/analytics/staging/runs/"):
            suffix = parsed.path.removeprefix("/api/analytics/staging/runs/")
            parts = suffix.split("/")
            run_id = parts[0]
            service = staging_analytics_service()
            if len(parts) == 1:
                json_response(self, service.run(run_id))
                return
            if parts[1] == "evidence":
                json_response(self, service.evidence(run_id))
                return
            if parts[1] == "report":
                json_response(self, service.report(run_id))
                return
        if parsed.path == "/api/certification/evidence":
            json_response(self, certification_evidence_service().list_evidence())
            return
        if parsed.path.startswith("/api/certification/evidence/"):
            evidence_id = parsed.path.removeprefix("/api/certification/evidence/").split("/")[0]
            json_response(self, certification_evidence_service().get_evidence(evidence_id))
            return
        if parsed.path == "/api/certification/policies":
            json_response(self, certification_evidence_service().policies())
            return
        if parsed.path == "/api/certification/github/operator-flow":
            json_response(self, ci_operator_service().status())
            return
        if parsed.path == "/api/certification/github/current-commit":
            json_response(self, ci_operator_service().current_commit())
            return
        if parsed.path == "/api/certification/github/runs":
            query = parse_qs(parsed.query)
            json_response(
                self,
                ci_operator_service().discover_runs(
                    query.get("origin_reference_id", ["github-actions-owned-publication"])[0],
                    commit_sha=query.get("commit", [""])[0],
                ),
            )
            return
        if parsed.path.startswith("/api/certification/github/runs/"):
            suffix = parsed.path.removeprefix("/api/certification/github/runs/")
            parts = suffix.split("/")
            query = parse_qs(parsed.query)
            origin_id = query.get("origin_reference_id", ["github-actions-owned-publication"])[0]
            run_id = parts[0]
            if len(parts) > 1 and parts[1] == "attempts":
                runs = [item for item in ci_artifact_service().list_runs(origin_id)["runs"] if item["run_id"] == run_id]
                json_response(self, {"run_id": run_id, "attempts": runs})
                return
            if len(parts) > 1 and parts[1] == "artifacts":
                attempt = int(query.get("attempt", ["1"])[0])
                json_response(self, ci_artifact_service().artifacts(origin_id, run_id, attempt))
                return
        if parsed.path.startswith("/api/certification/github/imports/"):
            suffix = parsed.path.removeprefix("/api/certification/github/imports/")
            import_id = suffix.split("/")[0]
            if suffix.endswith("/timeline"):
                json_response(self, ci_operator_service().import_timeline(import_id))
            else:
                json_response(self, ci_artifact_service().import_show(import_id))
            return
        if parsed.path == "/api/certification/github/readiness":
            json_response(self, ci_operator_service().readiness())
            return
        if parsed.path == "/api/secrets":
            json_response(self, managed_secrets_service().status())
            return
        if parsed.path == "/api/secrets/vault/health":
            json_response(self, managed_secrets_service().vault_health())
            return
        if parsed.path == "/api/secrets/audit":
            json_response(self, {"events": managed_secrets_service().repository.audit_events()})
            return
        if parsed.path.startswith("/api/secrets/"):
            suffix = parsed.path.removeprefix("/api/secrets/")
            secret_id = suffix.split("/")[0]
            service = managed_secrets_service()
            if suffix.endswith("/health"):
                json_response(self, service.health(secret_id))
            else:
                refs = [item for item in service.status()["references"] if item["id"] == secret_id]
                json_response(self, {"secret": refs[0] if refs else None})
            return
        if parsed.path.startswith("/operations/certification/github"):
            payload = render_page(
                ROUTE_OPERATIONS,
                self.config,
                None,
                [],
                {"total": 0, "queued": 0, "processing": 0, "done": 0, "failed": 0, "records": []},
                None,
                None,
                None,
                [],
                None,
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/api/certification/signers":
            json_response(self, trusted_signer_service().status())
            return
        if parsed.path.startswith("/api/certification/signers/"):
            suffix = parsed.path.removeprefix("/api/certification/signers/")
            signer_id = suffix.split("/")[0]
            service = trusted_signer_service()
            if suffix.endswith("/validate"):
                json_response(self, service.health(signer_id))
            elif suffix.endswith("/test"):
                json_response(self, service.test_sign(signer_id))
            else:
                signers = [item for item in service.status()["signers"] if item["id"] == signer_id]
                json_response(self, {"signer": signers[0] if signers else None})
            return
        if parsed.path == "/api/certification/ci-origins":
            json_response(self, ci_artifact_service().origins())
            return
        if parsed.path.startswith("/api/certification/ci-origins/"):
            suffix = parsed.path.removeprefix("/api/certification/ci-origins/")
            parts = suffix.split("/")
            origin_id = parts[0]
            service = ci_artifact_service()
            if len(parts) == 2 and parts[1] == "doctor":
                json_response(self, service.origin_doctor(origin_id))
            elif len(parts) == 2 and parts[1] == "runs":
                query = parse_qs(parsed.query)
                json_response(self, service.list_runs(origin_id, commit_sha=query.get("commit", [""])[0]))
            elif len(parts) == 4 and parts[1] == "runs" and parts[3] == "artifacts":
                json_response(self, service.artifacts(origin_id, parts[2]))
            else:
                origins = [item for item in service.origins()["origins"] if item["id"] == origin_id]
                json_response(self, {"origin": origins[0] if origins else None})
            return
        if parsed.path == "/api/certification/ci-imports":
            json_response(self, ci_artifact_service().imports())
            return
        if parsed.path.startswith("/api/certification/ci-imports/"):
            import_id = parsed.path.removeprefix("/api/certification/ci-imports/").split("/")[0]
            json_response(self, ci_artifact_service().import_show(import_id))
            return
        if parsed.path == "/api/analytics/instrumentation/profiles":
            json_response(self, website_instrumentation_service().profiles_payload())
            return
        if parsed.path.startswith("/api/analytics/instrumentation/profiles/"):
            profile_id = parsed.path.removeprefix("/api/analytics/instrumentation/profiles/")
            json_response(self, website_instrumentation_service().profiles_payload(profile_id))
            return
        if parsed.path == "/api/analytics/instrumentation/configs":
            json_response(self, website_instrumentation_service().list_configs())
            return
        if parsed.path.startswith("/api/analytics/instrumentation/configs/"):
            suffix = parsed.path.removeprefix("/api/analytics/instrumentation/configs/")
            parts = suffix.split("/")
            config_id = parts[0]
            service = website_instrumentation_service()
            try:
                if len(parts) == 1:
                    json_response(self, service.config(config_id))
                    return
                if parts[1] == "verification":
                    json_response(self, service.verify(config_id))
                    return
                if parts[1] == "quality":
                    json_response(self, {"quality": service.quality(config_id)})
                    return
                if parts[1] == "drift":
                    json_response(self, {"drift": service.drift(config_id)})
                    return
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "website_instrumentation.error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if parsed.path.startswith("/api/analytics/instrumentation/manifests/"):
            manifest_id = parsed.path.removeprefix("/api/analytics/instrumentation/manifests/")
            json_response(self, website_instrumentation_service().manifest(manifest_id))
            return
        if parsed.path == "/api/analytics/instrumentation/templates":
            json_response(self, website_instrumentation_service().templates())
            return
        if parsed.path.startswith("/api/analytics/instrumentation/templates/"):
            profile_id = parsed.path.removeprefix("/api/analytics/instrumentation/templates/")
            json_response(self, website_instrumentation_service().templates(profile_id))
            return
        if parsed.path.startswith("/api/analytics/providers/"):
            provider_id = parsed.path.removeprefix("/api/analytics/providers/")
            json_response(self, website_analytics_service().providers_payload(provider_id))
            return
        if parsed.path == "/api/analytics/accounts":
            json_response(self, website_analytics_service().list_accounts())
            return
        if parsed.path.startswith("/api/analytics/accounts/"):
            suffix = parsed.path.removeprefix("/api/analytics/accounts/")
            parts = suffix.split("/")
            account_id = parts[0]
            service = website_analytics_service()
            try:
                if len(parts) == 1:
                    json_response(self, service.account(account_id))
                    return
                if parts[1] == "doctor":
                    json_response(self, service.doctor(account_id))
                    return
                if parts[1] == "mappings":
                    json_response(self, service.mappings(account_id))
                    return
                if parts[1] == "sync":
                    json_response(self, service.sync_status(account_id))
                    return
                if parts[1] == "quality":
                    json_response(self, service.quality_report(account_id))
                    return
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "website_analytics.error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if parsed.path.startswith("/api/analytics/funnels/"):
            json_response(self, funnel_payload(parsed.path.removeprefix("/api/analytics/funnels/")))
            return
        if parsed.path.startswith("/api/funnels/") and parsed.path.endswith("/provider-data"):
            content_id = parsed.path.removeprefix("/api/funnels/").removesuffix("/provider-data").strip("/")
            json_response(self, website_analytics_service().provider_breakdown(content_id))
            return
        if parsed.path.startswith("/api/campaigns/") and parsed.path.endswith("/analytics-quality"):
            campaign_id = parsed.path.removeprefix("/api/campaigns/").removesuffix("/analytics-quality").strip("/")
            json_response(self, {"campaign_id": campaign_id, "quality": website_analytics_service().analytics_health()})
            return
        if parsed.path == "/api/content":
            json_response(self, {"content": owned_publication_service().list_content()})
            return
        if parsed.path == "/api/storage/health":
            json_response(self, owned_publication_service().storage_health())
            return
        if parsed.path == "/api/storage/migrations":
            json_response(self, owned_publication_service().migrations())
            return
        if parsed.path == "/api/operations/recovery":
            json_response(self, owned_publication_operations_payload())
            return
        if parsed.path == "/api/readmodels/status":
            json_response(self, owned_publication_service().readmodels_status())
            return
        if parsed.path == "/api/campaigns":
            json_response(self, owned_publication_service().list_campaigns(query.get("workspace_id", [""])[0]))
            return
        if parsed.path.startswith("/api/campaigns/"):
            suffix = parsed.path.removeprefix("/api/campaigns/")
            parts = suffix.split("/")
            campaign_id = parts[0]
            service = owned_publication_service()
            try:
                if len(parts) == 1:
                    json_response(self, service.campaign(campaign_id))
                    return
                if len(parts) == 2 and parts[1] in {"calendar", "performance"}:
                    json_response(
                        self,
                        {
                            "campaign_id": campaign_id,
                            "calendar": service.plan_payload()["plan"]["targets"],
                            "performance": service.funnel()["model"],
                            "durable": True,
                        },
                    )
                    return
            except OwnedPublicationError as exc:
                json_response(self, {"error": {"code": exc.code, "message": str(exc)}}, status=HTTPStatus.NOT_FOUND)
                return
        if parsed.path.startswith("/api/content/"):
            suffix = parsed.path.removeprefix("/api/content/")
            parts = suffix.split("/")
            content_id = parts[0]
            service = owned_publication_service()
            if len(parts) == 1:
                json_response(self, {"content": service.get_content(content_id)})
                return
            action = parts[1]
            if action == "revisions":
                json_response(self, service.list_revisions(content_id))
                return
            if action == "workspace":
                json_response(self, service.workspace_payload(content_id))
                return
            if action == "variants":
                json_response(self, service.variants(content_id))
                return
        if parsed.path.startswith("/api/publication-plans/"):
            suffix = parsed.path.removeprefix("/api/publication-plans/")
            parts = suffix.split("/")
            plan_id = parts[0]
            if len(parts) == 1:
                json_response(self, owned_publication_service().plan_payload(plan_id))
                return
            if len(parts) == 2 and parts[1] == "dependencies":
                json_response(self, owned_publication_service().plan_payload(plan_id)["dependencies"])
                return
        if parsed.path.startswith("/api/publications/"):
            suffix = parsed.path.removeprefix("/api/publications/")
            parts = suffix.split("/")
            publication_id = parts[0]
            if len(parts) == 2 and parts[1] == "timeline":
                json_response(self, owned_publication_service().timeline(publication_id))
                return
            if len(parts) == 2 and parts[1] == "evidence":
                json_response(self, owned_publication_service().evidence(publication_id))
                return
        if parsed.path == "/api/reconciliation":
            json_response(self, owned_publication_service().reconciliation())
            return
        if parsed.path.startswith("/api/reconciliation/"):
            json_response(self, owned_publication_service().reconciliation(parsed.path.rsplit("/", maxsplit=1)[-1]))
            return
        if parsed.path == "/api/funnels":
            json_response(self, funnel_payload())
            return
        if parsed.path.startswith("/api/funnels/"):
            suffix = parsed.path.removeprefix("/api/funnels/")
            parts = suffix.split("/")
            content_id = parts[0]
            service = owned_publication_service()
            if len(parts) == 1:
                json_response(self, service.funnel(content_id))
                return
            if parts[1] == "channels":
                json_response(self, service.channel_comparison(content_id))
                return
            if parts[1] == "revisions":
                json_response(self, service.revision_comparison(content_id))
                return
            if parts[1] == "quality":
                json_response(self, service.quality(content_id))
                return
        if parsed.path == "/api/browser-framework/conformance":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            body = json.dumps(runtime.browser_conformance_payload(), ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/browser-pilots":
            json_response(self, {"pilots": [record.__dict__ for record in list_browser_pilots()]})
            return
        if parsed.path.startswith("/api/browser-pilots/"):
            pilot_id = parsed.path.rsplit("/", maxsplit=1)[-1]
            pilot = get_browser_pilot(pilot_id)
            if pilot is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            json_response(self, {"pilot": pilot.__dict__})
            return
        if parsed.path == "/api/provider-state/history":
            query = parse_qs(parsed.query)
            channel_account_id = query.get("channel_account_id", [""])[0]
            json_response(
                self,
                {
                    "events": [
                        event.__dict__
                        for event in list_provider_state_events(channel_account_id=channel_account_id, limit=10)
                    ]
                },
            )
            return
        if parsed.path == "/api/browser-pilots/panel":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            conformance = runtime.browser_conformance_payload()
            latest_pilot = next(iter(list_browser_pilots()), None)
            linkedin_connection = get_channel_connection("linkedin")
            json_response(
                self,
                {
                    "active_provider": linkedin_connection.browser_provider_id if linkedin_connection else "",
                    "conformance": conformance,
                    "latest_pilot": latest_pilot.__dict__ if latest_pilot else {},
                    "recent_provider_events": [event.__dict__ for event in list_provider_state_events(limit=10)],
                    "kill_switches": {
                        "global": bool(getattr(self.config, "auto_browser_global_kill_switch", False)),
                        "accounts": list(getattr(self.config, "auto_browser_account_kill_switches", []) or []),
                    },
                },
            )
            return
        if parsed.path == "/api/providers/autobrowser/status":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            provider_runtime = runtime.runtimes.get("provider.browser.autobrowser")
            payload: dict[str, Any] = {
                "provider_id": "provider.browser.autobrowser",
                "registered": provider_runtime is not None,
            }
            if provider_runtime is not None:
                provider = provider_runtime.services.get("browser_provider")
                reconciliation = {}
                pilot_readiness = {}
                if provider is not None and hasattr(provider, "reconcile_sessions"):
                    try:
                        reconciliation = provider.reconcile_sessions()
                    except Exception:
                        reconciliation = {"status": "unavailable"}
                if provider is not None and hasattr(provider, "pilot_readiness"):
                    try:
                        pilot_readiness = provider.pilot_readiness()
                    except Exception:
                        pilot_readiness = {"status": "unknown"}
                payload.update(
                    {
                        "status": provider_runtime.status.value,
                        "health": provider_runtime.health,
                        "pilot_readiness": pilot_readiness,
                        "reconciliation": {
                            "status": reconciliation.get("status", ""),
                            "checked_at": reconciliation.get("checked_at", ""),
                            "orphaned_remote_count": reconciliation.get("orphaned_remote_count", 0),
                            "stale_mapping_count": reconciliation.get("stale_mapping_count", 0),
                        },
                    }
                )
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/media/providers/health":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            providers = []
            for plugin_id, plugin_runtime in sorted(runtime.runtimes.items()):
                if "media.storage" not in plugin_runtime.manifest.capabilities:
                    continue
                health = dict(plugin_runtime.health or {})
                providers.append(
                    {
                        "provider_id": plugin_id,
                        "status": plugin_runtime.status.value,
                        "contract_version": health.get("media_storage_provider_contract_version", ""),
                        "capabilities": list(plugin_runtime.manifest.capabilities),
                        "storage_type": health.get("storage_type", ""),
                        "configured": bool(health.get("configured", True)),
                        "readable": bool(health.get("readable", False)),
                        "writable": bool(health.get("writable", False)),
                        "materialization_available": bool(health.get("materialization_available", False)),
                        "last_error_code": health.get("code", ""),
                        "degraded_reason": "; ".join(health.get("messages", []) or []),
                    }
                )
            json_response(self, {"providers": providers})
            return
        if parsed.path == "/api/content/items":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            service = runtime.content_service(self.config)
            json_response(
                self,
                {
                    "items": [
                        _safe_content_payload(item)
                        for item in service.list_content(
                            workspace_id=query.get("workspace_id", [""])[0],
                            include_deleted=query.get("include_deleted", [""])[0].lower() in {"1", "true"},
                        )
                    ]
                },
            )
            return
        if parsed.path.startswith("/api/content/items/"):
            parts = [part for part in parsed.path.split("/") if part]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            service = runtime.content_service(self.config)
            query = parse_qs(parsed.query)
            workspace_id = query.get("workspace_id", [""])[0]
            content_id = parts[3] if len(parts) > 3 else ""
            try:
                item = service.get_content(content_id, workspace_id=workspace_id)
            except Exception:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if len(parts) == 4:
                json_response(self, {"item": _safe_content_payload(item)})
                return
            if len(parts) == 5 and parts[4] == "revisions":
                revisions = service.revision_repository.list_by_content(item.id)
                json_response(self, {"revisions": [_safe_revision_payload(revision) for revision in revisions]})
                return
            if len(parts) == 5 and parts[4] == "variants":
                variants = service.list_variants(item.id, workspace_id=item.workspace_id)
                json_response(self, {"variants": [_safe_variant_payload(variant) for variant in variants]})
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/content/requirements":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            requirements = runtime.content_service(self.config).requirement_registry.list_channel_requirements()
            json_response(self, {"requirements": [asdict(item) for item in requirements]})
            return
        if parsed.path.startswith("/api/content/requirements/"):
            channel_plugin_id = parsed.path.removeprefix("/api/content/requirements/")
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            requirements = runtime.content_service(self.config).requirement_registry.list_channel_requirements(
                channel_plugin_id
            )
            json_response(self, {"requirements": [asdict(item) for item in requirements]})
            return
        if parsed.path == "/api/publication-plans":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            planning = runtime.publication_planning_service(self.config)
            plans = planning.plan_repository.list_all(workspace_id=query.get("workspace_id", [""])[0])
            json_response(
                self,
                {
                    "plans": [
                        _safe_plan_payload(plan, planning.target_repository.list_by_plan(plan.id)) for plan in plans
                    ]
                },
            )
            return
        if parsed.path.startswith("/api/publication-plans/"):
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) < 3:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            plan_id = parts[2]
            query = parse_qs(parsed.query)
            workspace_id = query.get("workspace_id", [""])[0]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            planning = runtime.publication_planning_service(self.config)
            try:
                plan = planning.plan_repository.get(plan_id)
                if plan is None or (workspace_id and plan.workspace_id != workspace_id):
                    raise KeyError(plan_id)
                targets = planning.target_repository.list_by_plan(plan.id)
            except Exception:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if len(parts) == 3:
                json_response(self, {"plan": _safe_plan_payload(plan, targets)})
                return
            if len(parts) == 4 and parts[3] == "evidence":
                evidence = []
                for target in targets:
                    if target.job_id:
                        job = get_publish_job(target.job_id)
                        if job is not None:
                            evidence.append(
                                {
                                    "target_id": target.id,
                                    "job_id": job.id,
                                    "snapshot_checksum": target.snapshot_checksum[:16],
                                    "result_details": {
                                        "content_publication_evidence": job.result_details_json.get(
                                            "content_publication_evidence", {}
                                        )
                                    },
                                }
                            )
                json_response(self, {"evidence": evidence})
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/content/integrity":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            content_service = runtime.content_service(self.config)
            planning = runtime.publication_planning_service(self.config)
            issues = content_service.scan_integrity(workspace_id=query.get("workspace_id", [""])[0])
            issues.extend(planning.scan_integrity(workspace_id=query.get("workspace_id", [""])[0]))
            json_response(self, {"issues": [asdict(issue) for issue in issues]})
            return
        if parsed.path == "/api/content/health":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            json_response(
                self,
                {
                    "content": runtime.content_service(self.config).health_check(),
                    "planning": runtime.publication_planning_service(self.config).health_check(),
                },
            )
            return
        if parsed.path == "/api/publication-execution/health":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            json_response(self, {"health": runtime.publication_execution_service(self.config).health_check()})
            return
        if parsed.path == "/api/publication-execution/due":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            due = runtime.publication_execution_service(self.config).find_due_targets(
                workspace_id=query.get("workspace_id", [""])[0],
                batch_size=int(query.get("batch_size", ["25"])[0] or 25),
                dry_run=True,
            )
            json_response(self, {"due": [asdict(item) for item in due]})
            return
        if parsed.path.startswith("/api/publication-targets/") and parsed.path.endswith("/attempts"):
            target_id = parsed.path.split("/")[-2]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            attempts = runtime.publication_execution_service(self.config).attempt_repository.list_by_target(target_id)
            json_response(self, {"attempts": [_safe_attempt_payload(attempt) for attempt in attempts]})
            return
        if parsed.path.startswith("/api/publication-attempts/"):
            attempt_id = parsed.path.rsplit("/", maxsplit=1)[-1]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            attempt = runtime.publication_execution_service(self.config).attempt_repository.get(attempt_id)
            if attempt is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            json_response(self, {"attempt": _safe_attempt_payload(attempt)})
            return
        if parsed.path == "/api/publication-schedules":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            service = runtime.schedule_materialization_service(self.config)
            schedules = service.schedule_repository.list_all(workspace_id=query.get("workspace_id", [""])[0])
            json_response(self, {"schedules": [_safe_schedule_payload(schedule) for schedule in schedules]})
            return
        if parsed.path.startswith("/api/publication-schedules/"):
            parts = [part for part in parsed.path.split("/") if part]
            query = parse_qs(parsed.query)
            workspace_id = query.get("workspace_id", ["linkedin"])[0]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            service = runtime.schedule_materialization_service(self.config)
            schedule_id = parts[2] if len(parts) > 2 else ""
            schedule = service.schedule_repository.get(schedule_id)
            if schedule is None or schedule.workspace_id != workspace_id:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if len(parts) == 3:
                authorization = service.authorization_repository.get(schedule.authorization_id)
                json_response(
                    self,
                    {
                        "schedule": _safe_schedule_payload(schedule),
                        "authorization": _safe_authorization_payload(authorization) if authorization else {},
                    },
                )
                return
            if len(parts) == 4 and parts[3] == "occurrences":
                occurrences = service.occurrence_repository.list_by_schedule(schedule.id)
                json_response(self, {"occurrences": [_safe_occurrence_payload(item) for item in occurrences]})
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path.startswith("/api/publication-occurrences/"):
            occurrence_id = parsed.path.rsplit("/", maxsplit=1)[-1]
            query = parse_qs(parsed.query)
            workspace_id = query.get("workspace_id", ["linkedin"])[0]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            occurrence = runtime.schedule_materialization_service(self.config).occurrence_repository.get(occurrence_id)
            if occurrence is None or occurrence.workspace_id != workspace_id:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            json_response(self, {"occurrence": _safe_occurrence_payload(occurrence)})
            return
        if parsed.path == "/api/campaigns":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            campaign_service = runtime.campaign_service(self.config)
            campaigns = campaign_service.campaign_repository.list_all(workspace_id=query.get("workspace_id", [""])[0])
            json_response(
                self,
                {
                    "campaigns": [
                        _safe_campaign_payload(
                            campaign, campaign_service.member_repository.list_by_campaign(campaign.id)
                        )
                        for campaign in campaigns
                    ]
                },
            )
            return
        if parsed.path.startswith("/api/campaigns/"):
            parts = [part for part in parsed.path.split("/") if part]
            query = parse_qs(parsed.query)
            workspace_id = query.get("workspace_id", ["linkedin"])[0]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            campaign_service = runtime.campaign_service(self.config)
            campaign_id = parts[1] if len(parts) > 1 else ""
            campaign = campaign_service.campaign_repository.get(campaign_id)
            if campaign is None or campaign.workspace_id != workspace_id:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            json_response(
                self,
                {
                    "campaign": _safe_campaign_payload(
                        campaign, campaign_service.member_repository.list_by_campaign(campaign.id)
                    )
                },
            )
            return
        if parsed.path == "/api/execution-calendar":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            calendar_service = runtime.execution_calendar_service(self.config)
            now = datetime.now().astimezone()
            entries = calendar_service.list_calendar_entries(
                workspace_id=query.get("workspace_id", ["linkedin"])[0],
                start=query.get("start", [(now - timedelta(days=7)).isoformat(timespec="seconds")])[0],
                end=query.get("end", [(now + timedelta(days=45)).isoformat(timespec="seconds")])[0],
                timezone=query.get("timezone", ["UTC"])[0],
                channel_plugin_id=query.get("channel_plugin_id", [""])[0],
                campaign_id=query.get("campaign_id", [""])[0],
                status=query.get("status", [""])[0],
                attention_required=(
                    query.get("attention_required", [""])[0].lower() in {"1", "true"}
                    if query.get("attention_required", [""])[0]
                    else None
                ),
                limit=int(query.get("limit", ["200"])[0] or 200),
            )
            json_response(self, {"entries": [_safe_calendar_entry_payload(entry) for entry in entries]})
            return
        if parsed.path == "/api/scheduling/health":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            json_response(
                self,
                {
                    "scheduling": runtime.schedule_materialization_service(self.config).health_check(),
                    "calendar": runtime.execution_calendar_service(self.config).health_check(),
                    "campaigns": runtime.campaign_service(self.config).health_check(),
                },
            )
            return
        if parsed.path == "/api/scheduling/integrity":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            issues = runtime.schedule_materialization_service(self.config).scan_integrity(
                workspace_id=query.get("workspace_id", [""])[0]
            )
            json_response(self, {"issues": issues})
            return
        if parsed.path == "/api/analytics/health":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            json_response(self, {"health": runtime.analytics_bundle(self.config).health_check()})
            return
        if parsed.path == "/api/analytics/definitions":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            definitions = runtime.analytics_bundle(self.config).metric_registry.list_definitions()
            json_response(self, {"definitions": [asdict(item) for item in definitions]})
            return
        if parsed.path.startswith("/api/analytics/definitions/"):
            channel_plugin_id = parsed.path.removeprefix("/api/analytics/definitions/")
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            definitions = runtime.analytics_bundle(self.config).metric_registry.list_definitions(channel_plugin_id)
            json_response(self, {"definitions": [asdict(item) for item in definitions]})
            return
        if parsed.path == "/api/analytics/collection-runs":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            runs = runtime.analytics_bundle(self.config).collection_run_repository.list_all(
                workspace_id=query.get("workspace_id", [""])[0]
            )
            json_response(self, {"collection_runs": [asdict(run) for run in runs[:100]]})
            return
        if parsed.path.startswith("/api/analytics/collection-runs/"):
            run_id = parsed.path.rsplit("/", maxsplit=1)[-1]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            run = next(
                (
                    item
                    for item in runtime.analytics_bundle(self.config).collection_run_repository.list_all()
                    if item.id == run_id
                ),
                None,
            )
            if run is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            json_response(self, {"collection_run": asdict(run)})
            return
        if parsed.path == "/api/analytics/publications":
            query = parse_qs(parsed.query)
            workspace_id = query.get("workspace_id", ["linkedin"])[0]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            service = runtime.analytics_read_model_service(self.config)
            page_size = min(int(query.get("page_size", ["50"])[0] or 50), 100)
            performances = []
            for post in list_published_posts(channel_id=workspace_id)[:page_size]:
                try:
                    performances.append(
                        _safe_analytics_payload(service.publication_performance(post.id, workspace_id=workspace_id))
                    )
                except Exception:
                    performances.append({"publication_id": post.id, "completeness": {"status": "insufficient"}})
            json_response(self, {"publications": performances})
            return
        if parsed.path.startswith("/api/analytics/publications/"):
            publication_id = parsed.path.rsplit("/", maxsplit=1)[-1]
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            try:
                payload = runtime.analytics_read_model_service(self.config).publication_performance(
                    publication_id, workspace_id=query.get("workspace_id", [""])[0]
                )
            except Exception:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            json_response(self, {"publication": _safe_analytics_payload(payload)})
            return
        if parsed.path.startswith("/api/analytics/content/"):
            parts = [part for part in parsed.path.split("/") if part]
            content_item_id = parts[2] if len(parts) > 2 else ""
            query = parse_qs(parsed.query)
            workspace_id = query.get("workspace_id", [""])[0]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            service = runtime.analytics_read_model_service(self.config)
            if len(parts) == 3:
                json_response(
                    self,
                    {
                        "content": _safe_analytics_payload(
                            service.content_performance(content_item_id, workspace_id=workspace_id)
                        )
                    },
                )
                return
            if len(parts) == 4 and parts[3] == "revisions":
                json_response(
                    self,
                    {
                        "revisions": _safe_analytics_payload(
                            service.revision_performance(content_item_id, workspace_id=workspace_id)
                        )
                    },
                )
                return
            if len(parts) == 4 and parts[3] == "variants":
                json_response(
                    self,
                    {
                        "variants": _safe_analytics_payload(
                            service.variant_performance(content_item_id, workspace_id=workspace_id)
                        )
                    },
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path.startswith("/api/analytics/media/"):
            asset_id = parsed.path.rsplit("/", maxsplit=1)[-1]
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            payload = runtime.analytics_read_model_service(self.config).media_performance(
                asset_id, workspace_id=query.get("workspace_id", [""])[0]
            )
            json_response(self, {"media": _safe_analytics_payload(payload)})
            return
        if parsed.path.startswith("/api/analytics/campaigns/"):
            campaign_id = parsed.path.rsplit("/", maxsplit=1)[-1]
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            payload = runtime.analytics_read_model_service(self.config).campaign_performance(
                campaign_id, workspace_id=query.get("workspace_id", [""])[0]
            )
            json_response(self, {"campaign": _safe_analytics_payload(payload)})
            return
        if parsed.path == "/api/analytics/channels":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            payload = runtime.analytics_read_model_service(self.config).channel_performance(
                workspace_id=query.get("workspace_id", [""])[0],
                channel_plugin_id=query.get("channel_plugin_id", [""])[0],
            )
            json_response(self, {"channel": _safe_analytics_payload(payload)})
            return
        if parsed.path.startswith("/api/analytics/accounts/"):
            account_id = parsed.path.rsplit("/", maxsplit=1)[-1]
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            payload = runtime.analytics_read_model_service(self.config).channel_performance(
                workspace_id=query.get("workspace_id", [""])[0],
                channel_account_id=account_id,
            )
            json_response(self, {"account": _safe_analytics_payload(payload)})
            return
        if parsed.path == "/api/analytics/integrity":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            issues = runtime.analytics_integrity_service(self.config).scan(
                workspace_id=query.get("workspace_id", [""])[0]
            )
            json_response(self, {"issues": issues})
            return
        if parsed.path == "/api/media/library/health":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            json_response(self, {"health": runtime.media_library_service(self.config).health_check()})
            return
        if parsed.path == "/api/media/library":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            library = runtime.media_library_service(self.config)
            result = library.search_assets(
                workspace_id=query.get("workspace_id", ["linkedin"])[0],
                filters=_query_filters(query),
            )
            json_response(
                self,
                {
                    "assets": list(result.assets),
                    "page": result.page,
                    "page_size": result.page_size,
                    "total": result.total,
                    "has_next": result.has_next,
                },
            )
            return
        if parsed.path.startswith("/api/media/library/"):
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 4:
                asset_id = parts[3]
                query = parse_qs(parsed.query)
                workspace_id = query.get("workspace_id", ["linkedin"])[0]
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                library = runtime.media_library_service(self.config)
                try:
                    asset = library.get_asset(asset_id, workspace_id=workspace_id, include_deleted=True)
                    if len(parts) == 4:
                        counters = library.search_assets(
                            workspace_id=workspace_id,
                            filters={"deleted": True, "checksum": asset.checksum},
                        )
                        payload = next((item for item in counters.assets if item["id"] == asset.id), None)
                        json_response(self, {"asset": payload or _safe_media_asset_payload(asset)})
                        return
                    if len(parts) == 5 and parts[4] == "usage":
                        json_response(
                            self,
                            {
                                "usage": [
                                    _safe_usage_payload(item)
                                    for item in library.list_asset_usage(asset_id, workspace_id=workspace_id)
                                ]
                            },
                        )
                        return
                    if len(parts) == 5 and parts[4] == "relations":
                        json_response(
                            self,
                            {
                                "relations": [
                                    _safe_relation_payload(item)
                                    for item in library.relation_repository.list_by_asset(asset_id)
                                    if item.workspace_id == workspace_id
                                ]
                            },
                        )
                        return
                except Exception:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path.startswith("/api/media/assets/") and parsed.path.endswith("/preview"):
            asset_id = parsed.path.split("/")[-2]
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            library = runtime.media_library_service(self.config)
            try:
                data, _mime, headers = library.preview_asset(
                    asset_id,
                    workspace_id=query.get("workspace_id", ["linkedin"])[0],
                )
            except Exception:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/api/media/retention/preview":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            candidates = runtime.media_library_service(self.config).retention_preview(
                workspace_id=query.get("workspace_id", ["linkedin"])[0]
            )
            json_response(self, {"candidates": [candidate.__dict__ for candidate in candidates]})
            return
        if parsed.path.startswith("/api/media/retention/plans/"):
            plan_id = parsed.path.rsplit("/", maxsplit=1)[-1]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            plan = runtime.media_library_service(self.config).get_retention_plan(plan_id)
            if plan is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            json_response(self, {"plan": plan.__dict__})
            return
        if parsed.path == "/api/media/integrity":
            query = parse_qs(parsed.query)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            json_response(
                self,
                runtime.media_library_service(self.config).integrity_scan(
                    workspace_id=query.get("workspace_id", ["linkedin"])[0]
                ),
            )
            return
        if parsed.path == "/api/media/assets":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            media_runtime = runtime.media_runtime(self.config)
            json_response(
                self,
                {
                    "assets": [
                        _safe_media_asset_payload(asset)
                        for asset in media_runtime.list_assets(
                            workspace_id=parse_qs(parsed.query).get("workspace_id", [""])[0]
                        )
                    ]
                },
            )
            return
        if parsed.path.startswith("/api/media/assets/"):
            asset_id = parsed.path.rsplit("/", maxsplit=1)[-1]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            media_runtime = runtime.media_runtime(self.config)
            try:
                asset = media_runtime.get_asset(
                    asset_id, workspace_id=parse_qs(parsed.query).get("workspace_id", [""])[0]
                )
            except Exception:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            json_response(self, {"asset": _safe_media_asset_payload(asset)})
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
            if (
                parsed.path not in VALID_ROUTES
                and not parsed.path.startswith("/content/")
                and not parsed.path.startswith("/publications/")
                and not parsed.path.startswith("/funnels/")
                and not parsed.path.startswith("/campaigns/")
            ):
                self.send_error(HTTPStatus.NOT_FOUND)
                return

        try:
            ensure_studio_dirs(self.config.content_dir)
            content_items = list_content_items(self.config.content_dir)
            content_identifier = parse_qs(parsed.query).get("content", [None])[0]
            selected_content_item = select_content_item_for_route(
                self.config.content_dir,
                content_items,
                content_identifier,
                route,
            )
            snapshot = build_snapshot(self.config) if route == ROUTE_LINKEDIN else None
            all_queue = load_schedule()
            preview = load_preview()
            selected_status = parse_qs(parsed.query).get("status", [None])[0]
            detail_id = parse_qs(parsed.query).get("detail", [None])[0]
            selected_record = get_schedule_record(detail_id) if detail_id else None
            queue = queue_summary(filter_queue(all_queue, selected_status))
            payload = render_page(
                route,
                self.config,
                snapshot,
                all_queue,
                queue,
                preview,
                selected_record,
                selected_status,
                content_items,
                selected_content_item,
            ).encode("utf-8")
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
            self.send_header(
                "Content-Type",
                (mime_type or "application/octet-stream")
                + ("; charset=utf-8" if (mime_type or "").startswith(("text/", "application/javascript")) else ""),
            )
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
                content_asset = f"{slug}/assets/{safe_name}"
                payload = json.dumps(
                    {
                        "ok": True,
                        "slug": slug,
                        "filename": safe_name,
                        "content_asset": content_asset,
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
        json_body: dict[str, Any] = {}
        if content_type_header.startswith("application/json") and body.strip():
            try:
                parsed_body = json.loads(body)
                json_body = parsed_body if isinstance(parsed_body, dict) else {}
            except json.JSONDecodeError:
                json_response(
                    self,
                    {"error": {"code": "request.invalid_json", "message": "Invalid JSON body."}},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if path == "/api/content":
            json_response(self, {"content": owned_publication_service().create_content(json_body)})
            return
        if path == "/api/operations/recovery/run":
            json_response(self, owned_publication_service().recovery())
            return
        if path == "/api/operations/backups":
            json_response(self, owned_publication_service().backup_create(json_body), status=HTTPStatus.CREATED)
            return
        if path.startswith("/api/operations/backups/") and path.endswith("/validate"):
            backup_id = path.removeprefix("/api/operations/backups/").removesuffix("/validate").strip("/")
            json_response(self, owned_publication_service().backup_validate(backup_id))
            return
        if path == "/api/operations/retention/preview":
            json_response(self, owned_publication_service().retention_preview(json_body))
            return
        if path == "/api/operations/support-bundles":
            json_response(self, owned_publication_service().support_bundle_create(), status=HTTPStatus.CREATED)
            return
        if path == "/api/analytics/accounts":
            try:
                json_response(self, website_analytics_service().create_account(json_body), status=HTTPStatus.CREATED)
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "website_analytics.error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
            return
        if path == "/api/analytics/instrumentation/configs":
            try:
                json_response(
                    self, website_instrumentation_service().create_config(json_body), status=HTTPStatus.CREATED
                )
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "website_instrumentation.error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
            return
        if path == "/api/analytics/instrumentation/manifests/preview":
            json_response(
                self,
                website_instrumentation_service().preview_manifest(
                    str(json_body.get("config_id", "instrumentation-config-owned-1")),
                    dict(json_body.get("snapshot", {})),
                ),
            )
            return
        if path.startswith("/api/analytics/instrumentation/configs/"):
            suffix = path.removeprefix("/api/analytics/instrumentation/configs/")
            parts = suffix.split("/")
            config_id = parts[0]
            service = website_instrumentation_service()
            try:
                if len(parts) == 1:
                    json_response(self, service.update_config(config_id, json_body))
                    return
                if len(parts) == 2 and parts[1] == "verify":
                    json_response(self, service.verify(config_id))
                    return
            except Exception as exc:
                status = (
                    HTTPStatus.CONFLICT if getattr(exc, "code", "").endswith("conflict") else HTTPStatus.BAD_REQUEST
                )
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "website_instrumentation.error"), "message": str(exc)}},
                    status=status,
                )
                return
        if path == "/api/analytics/staging/profiles":
            try:
                json_response(self, staging_analytics_service().create_profile(json_body), status=HTTPStatus.CREATED)
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "staging_analytics.error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
            return
        if path.startswith("/api/analytics/staging/profiles/"):
            suffix = path.removeprefix("/api/analytics/staging/profiles/")
            parts = suffix.split("/")
            profile_id = parts[0]
            if len(parts) == 2 and parts[1] == "validate":
                try:
                    json_response(self, staging_analytics_service().validate_profile(profile_id))
                except Exception as exc:
                    json_response(
                        self,
                        {"error": {"code": getattr(exc, "code", "staging_analytics.error"), "message": str(exc)}},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if len(parts) == 2 and parts[1] == "dry-run":
                try:
                    json_response(self, certification_evidence_service().dry_run_staging_profile(profile_id))
                except Exception as exc:
                    json_response(
                        self,
                        {"error": {"code": getattr(exc, "code", "certification.error"), "message": str(exc)}},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if len(parts) == 2 and parts[1] == "execute":
                try:
                    json_response(
                        self,
                        certification_evidence_service().execute_staging_profile(
                            profile_id, confirm=bool(json_body.get("confirm", False))
                        ),
                        status=HTTPStatus.CREATED,
                    )
                except Exception as exc:
                    json_response(
                        self,
                        {"error": {"code": getattr(exc, "code", "certification.error"), "message": str(exc)}},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
        if path == "/api/analytics/staging/runs":
            execute = bool(json_body.get("execute_staging", False))
            try:
                json_response(
                    self,
                    staging_analytics_service().create_run(
                        str(json_body.get("profile_id", "staging-cert-profile-1")),
                        execute_staging=execute,
                        idempotency_key=str(json_body.get("idempotency_key", "")),
                    ),
                    status=HTTPStatus.CREATED,
                )
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "staging_analytics.error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
            return
        if path.startswith("/api/certification/github/"):
            service = ci_operator_service()
            try:
                if path == "/api/certification/github/operator-flow":
                    json_response(
                        self,
                        service.create_flow(
                            origin_reference_id=str(json_body.get("origin_reference_id", "")),
                            expected_commit_sha=str(json_body.get("expected_commit_sha", "")),
                            actor=str(json_body.get("actor", "release-operator")),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/certification/github/credential":
                    secret_service = managed_secrets_service()
                    json_response(
                        self,
                        secret_service.create_reference(
                            secret_type="github_read_only_token",
                            display_name=str(json_body.get("display_name", "GitHub Actions read credential")),
                            purpose_allowlist=("github_actions_read",),
                            created_by=str(json_body.get("created_by", "secret-operator")),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/certification/github/credential/request-approval":
                    json_response(
                        self, {"status": "approval_requested", "secret_reference_id": json_body.get("secret_id", "")}
                    )
                    return
                if path == "/api/certification/github/credential/approve":
                    secret_service = managed_secrets_service()
                    json_response(
                        self,
                        secret_service.approve(
                            str(json_body.get("secret_id", "")),
                            action_type="approve_github_credential",
                            requester_id=str(json_body.get("requester_id", "operator-a")),
                            approver_id=str(json_body.get("approver_id", "operator-b")),
                        ),
                    )
                    return
                if path == "/api/certification/github/origin":
                    json_response(self, ci_artifact_service().register_origin(json_body), status=HTTPStatus.CREATED)
                    return
                if path == "/api/certification/github/origin/doctor":
                    json_response(self, service.origin_doctor(str(json_body.get("origin_reference_id", ""))))
                    return
                if path == "/api/certification/github/import/dry-run":
                    flow_id = str(json_body.get("flow_id", ""))
                    if not flow_id:
                        flow = service.create_flow(
                            origin_reference_id=str(json_body.get("origin_reference_id", "")),
                            expected_commit_sha=str(json_body.get("expected_commit_sha", "")),
                            actor=str(json_body.get("actor", "release-operator")),
                        )["flow"]
                        service.select_run(
                            flow["id"],
                            run_id=str(json_body.get("run_id", "")),
                            run_attempt=int(json_body.get("run_attempt", 1)),
                        )
                        service.select_artifact(flow["id"], artifact_id=str(json_body.get("artifact_id", "")))
                        flow_id = flow["id"]
                    json_response(self, service.dry_run_import(flow_id))
                    return
                if path == "/api/certification/github/import/execute":
                    json_response(
                        self,
                        service.execute_import(
                            str(json_body.get("dry_run_id", "")),
                            confirmed_by=str(json_body.get("confirmed_by", "release-operator")),
                            signer_id=str(json_body.get("signer_id", "")),
                        ),
                    )
                    return
                if path.startswith("/api/certification/github/imports/"):
                    suffix = path.removeprefix("/api/certification/github/imports/")
                    parts = suffix.split("/")
                    import_id = parts[0]
                    action = parts[1] if len(parts) > 1 else ""
                    if action == "cancel":
                        request = ci_artifact_service().repository.get_request(import_id)
                        json_response(
                            self,
                            {"import_request": ci_artifact_service().repository.update_request(request, "cancelled")},
                        )
                        return
                    if action == "reconcile":
                        flow_id = str(json_body.get("flow_id", ""))
                        json_response(
                            self,
                            service.reconcile_flow(flow_id) if flow_id else ci_artifact_service().reconcile(import_id),
                        )
                        return
                    if action == "review":
                        json_response(
                            self,
                            service.review_import(
                                import_id,
                                reviewer_id=str(json_body.get("reviewer_id", "operator-b")),
                                requester_id=str(json_body.get("requester_id", "operator-a")),
                                decision=str(json_body.get("decision", "approved")),
                            ),
                        )
                        return
                    if action == "promote":
                        json_response(
                            self,
                            service.promote_import(
                                import_id, promoted_by=str(json_body.get("promoted_by", "release-operator"))
                            ),
                        )
                        return
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "github_ci_operator.error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if path.startswith("/api/certification/"):
            service = certification_evidence_service()
            try:
                if path == "/api/certification/signers":
                    signer_service = trusted_signer_service()
                    json_response(
                        self,
                        signer_service.enroll(
                            signer_id=str(json_body.get("id", "")),
                            display_name=str(json_body.get("display_name", "Host signer")),
                            private_key_secret_reference=str(json_body.get("private_key_secret_reference", "")),
                            operator_id=str(json_body.get("operator_id", "operator-a")),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/certification/signers/"):
                    signer_service = trusted_signer_service()
                    suffix = path.removeprefix("/api/certification/signers/")
                    parts = suffix.split("/")
                    signer_id = parts[0]
                    action = parts[1] if len(parts) > 1 else ""
                    if action == "approve":
                        json_response(
                            self,
                            signer_service.approve(
                                signer_id,
                                reviewer_id=str(json_body.get("reviewer_id", "operator-b")),
                                requester_id=str(json_body.get("requester_id", "operator-a")),
                            ),
                        )
                        return
                    if action == "activate":
                        json_response(self, signer_service.activate(signer_id))
                        return
                    if action == "rotate":
                        json_response(
                            self,
                            signer_service.rotate(
                                signer_id,
                                new_signer_id=str(json_body.get("new_signer_id", "")),
                                new_secret_reference=str(json_body.get("new_secret_reference", "")),
                            ),
                        )
                        return
                    if action == "revoke":
                        json_response(
                            self,
                            signer_service.revoke(
                                signer_id,
                                reason=str(json_body.get("reason", "administrative_retirement")),
                            ),
                        )
                        return
                    if action == "test":
                        json_response(self, signer_service.test_sign(signer_id))
                        return
                if path == "/api/certification/ci-origins":
                    json_response(self, ci_artifact_service().register_origin(json_body), status=HTTPStatus.CREATED)
                    return
                if path.startswith("/api/certification/signers/") and path.endswith("/activate-with-secret"):
                    signer_id = (
                        path.removeprefix("/api/certification/signers/")
                        .removesuffix("/activate-with-secret")
                        .strip("/")
                    )
                    json_response(self, trusted_signer_service().activate(signer_id))
                    return
                if path.startswith("/api/certification/ci-origins/") and path.endswith("/bind-credential"):
                    suffix = path.removeprefix("/api/certification/ci-origins/")
                    origin_id = suffix.removesuffix("/bind-credential").strip("/")
                    ci_service = ci_artifact_service()
                    origin = ci_service.repository.get_origin(origin_id)
                    origin["credential_secret_reference"] = str(json_body.get("secret_reference_id", ""))
                    json_response(self, ci_service.register_origin(origin))
                    return
                if path == "/api/certification/ci-imports":
                    json_response(
                        self,
                        ci_artifact_service().create_import_request(
                            origin_id=str(json_body.get("origin_reference_id", "")),
                            run_id=str(json_body.get("workflow_run_id", "")),
                            artifact_id=str(json_body.get("artifact_id", "")),
                            expected_commit_sha=str(json_body.get("expected_commit_sha", "")),
                            run_attempt=int(json_body.get("run_attempt", 1)),
                            requested_by=str(json_body.get("requested_by", "operator")),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/certification/ci-imports/"):
                    ci_service = ci_artifact_service()
                    suffix = path.removeprefix("/api/certification/ci-imports/")
                    parts = suffix.split("/")
                    import_id = parts[0]
                    action = parts[1] if len(parts) > 1 else ""
                    if action == "dry-run":
                        request = ci_service.repository.get_request(import_id)
                        json_response(
                            self,
                            ci_service.dry_run_import(
                                request["origin_reference_id"],
                                request["workflow_run_id"],
                                request["artifact_id"],
                                expected_commit_sha=request["expected_commit_sha"],
                            ),
                        )
                        return
                    if action == "reconcile":
                        json_response(self, ci_service.reconcile(import_id))
                        return
                    if action == "review":
                        json_response(
                            self,
                            ci_service.review_import(
                                import_id,
                                decision=str(json_body.get("decision", "approved")),
                                reviewer_id=str(json_body.get("reviewer_id", "operator")),
                            ),
                        )
                        return
                if path == "/api/certification/evidence/export":
                    json_response(self, service.export_evidence(str(json_body.get("evidence_id", ""))))
                    return
                if path == "/api/certification/evidence/import":
                    import base64

                    data = base64.b64decode(str(json_body.get("package_base64", "")))
                    json_response(self, service.import_evidence(data), status=HTTPStatus.CREATED)
                    return
                if path == "/api/certification/compare":
                    json_response(
                        self,
                        service.compare(str(json_body.get("left_id", "")), str(json_body.get("right_id", ""))),
                    )
                    return
                if path.startswith("/api/certification/evidence/"):
                    suffix = path.removeprefix("/api/certification/evidence/")
                    parts = suffix.split("/")
                    evidence_id = parts[0]
                    action = parts[1] if len(parts) > 1 else ""
                    if action == "verify":
                        json_response(self, service.verify(evidence_id))
                        return
                    if action == "review":
                        json_response(
                            self,
                            service.review(
                                evidence_id,
                                decision=str(json_body.get("decision", "approved")),
                                reviewer_id=str(json_body.get("reviewer_id", "operator")),
                                safe_comment=str(json_body.get("safe_comment", "")),
                            ),
                        )
                        return
                    if action == "revoke":
                        json_response(
                            self,
                            service.revoke(
                                evidence_id,
                                reason=str(json_body.get("reason", "operator_revoked")),
                                reviewer_id=str(json_body.get("reviewer_id", "operator")),
                            ),
                        )
                        return
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "certification.error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if path.startswith("/api/secrets"):
            secret_service = managed_secrets_service()
            try:
                if path == "/api/secrets":
                    json_response(
                        self,
                        secret_service.create_reference(
                            secret_type=str(json_body.get("secret_type", "")),
                            display_name=str(json_body.get("display_name", "")),
                            purpose_allowlist=tuple(json_body.get("purpose_allowlist", ())),
                            created_by=str(json_body.get("created_by", "operator")),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                suffix = path.removeprefix("/api/secrets/").strip("/")
                parts = suffix.split("/")
                secret_id = parts[0]
                action = parts[1] if len(parts) > 1 else ""
                if action == "set-value":
                    value = str(json_body.get("value", "")).encode("utf-8")
                    json_response(self, secret_service.set_value(secret_id, value))
                    return
                if action == "generate":
                    json_response(self, secret_service.generate_ed25519(secret_id))
                    return
                if action == "validate":
                    json_response(self, secret_service.validate(secret_id))
                    return
                if action == "request-approval":
                    json_response(self, {"status": "approval_request_recorded", "secret_reference_id": secret_id})
                    return
                if action == "approve":
                    json_response(
                        self,
                        secret_service.approve(
                            secret_id,
                            action_type=str(json_body.get("action_type", "approve_github_credential")),
                            requester_id=str(json_body.get("requester_id", "operator-a")),
                            approver_id=str(json_body.get("approver_id", "operator-b")),
                        ),
                    )
                    return
                if action == "activate":
                    json_response(
                        self,
                        secret_service.activate(
                            secret_id,
                            action_type=str(json_body.get("action_type", "approve_github_credential")),
                        ),
                    )
                    return
                if action == "rotate":
                    value = str(json_body.get("value", "")).encode("utf-8")
                    json_response(self, secret_service.rotate(secret_id, value))
                    return
                if action == "revoke":
                    json_response(self, secret_service.revoke(secret_id, reason=str(json_body.get("reason", ""))))
                    return
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "secret.error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if path.startswith("/api/analytics/staging/runs/"):
            suffix = path.removeprefix("/api/analytics/staging/runs/")
            parts = suffix.split("/")
            run_id = parts[0]
            service = staging_analytics_service()
            try:
                if len(parts) == 2 and parts[1] == "cancel":
                    json_response(self, service.mark_uncertain(run_id) | {"cancel_requested": True})
                    return
                if len(parts) == 2 and parts[1] == "reconcile":
                    json_response(
                        self, service.reconcile_run(run_id, observed_events=list(json_body.get("observed_events", [])))
                    )
                    return
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "staging_analytics.error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if path.startswith("/api/analytics/accounts/"):
            suffix = path.removeprefix("/api/analytics/accounts/")
            parts = suffix.split("/")
            account_id = parts[0]
            service = website_analytics_service()
            try:
                if len(parts) == 2 and parts[1] == "validate":
                    json_response(self, service.validate(account_id))
                    return
                if len(parts) == 2 and parts[1] == "disable":
                    json_response(
                        self,
                        service.enable(account_id, enabled=False, expected_version=int(json_body["expected_version"])),
                    )
                    return
                if len(parts) == 2 and parts[1] == "enable":
                    json_response(
                        self,
                        service.enable(account_id, enabled=True, expected_version=int(json_body["expected_version"])),
                    )
                    return
                if len(parts) == 2 and parts[1] == "mappings":
                    json_response(self, service.put_mappings(account_id, list(json_body.get("mappings", []))))
                    return
                if len(parts) == 2 and parts[1] == "sync":
                    json_response(self, service.sync(account_id))
                    return
            except Exception as exc:
                status = (
                    HTTPStatus.CONFLICT if getattr(exc, "code", "").endswith("conflict") else HTTPStatus.BAD_REQUEST
                )
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "website_analytics.error"), "message": str(exc)}},
                    status=status,
                )
                return
        if path == "/api/readmodels/rebuild":
            json_response(self, owned_publication_service().rebuild_readmodels(json_body))
            return
        if path == "/api/campaigns":
            json_response(self, owned_publication_service().create_campaign(json_body), status=HTTPStatus.CREATED)
            return
        if path.startswith("/api/campaigns/"):
            suffix = path.removeprefix("/api/campaigns/")
            parts = suffix.split("/")
            campaign_id = parts[0]
            service = owned_publication_service()
            try:
                if len(parts) == 2 and parts[1] == "pause":
                    json_response(self, service.pause_campaign(campaign_id, json_body))
                    return
                if len(parts) == 2 and parts[1] == "resume":
                    json_response(self, service.resume_campaign(campaign_id, json_body))
                    return
            except OwnedPublicationError as exc:
                json_response(self, {"error": {"code": exc.code, "message": str(exc)}}, status=HTTPStatus.CONFLICT)
                return
        if path.startswith("/api/content/"):
            suffix = path.removeprefix("/api/content/")
            parts = suffix.split("/")
            content_id = parts[0]
            service = owned_publication_service()
            try:
                if len(parts) == 1:
                    json_response(self, service.autosave(content_id, json_body))
                    return
                action = parts[1]
                if action == "validate":
                    json_response(self, service.validate_content(content_id))
                    return
                if action == "revisions":
                    json_response(self, service.create_revision(content_id, json_body))
                    return
                if action == "variants" and len(parts) >= 3:
                    json_response(self, service.put_variant(content_id, parts[2], json_body))
                    return
                if action == "preview" and len(parts) >= 3:
                    json_response(self, service.preview(content_id, parts[2]))
                    return
            except OwnedPublicationError as exc:
                json_response(self, {"error": {"code": exc.code, "message": str(exc)}}, status=HTTPStatus.CONFLICT)
                return
        if path == "/api/publication-plans":
            json_response(self, owned_publication_service().plan_payload())
            return
        if path.startswith("/api/publication-plans/"):
            suffix = path.removeprefix("/api/publication-plans/")
            parts = suffix.split("/")
            plan_id = parts[0]
            service = owned_publication_service()
            try:
                if len(parts) == 2 and parts[1] == "validate":
                    json_response(self, service.validate_plan(plan_id))
                    return
                if len(parts) == 2 and parts[1] == "publish":
                    json_response(self, service.publish_plan(plan_id))
                    return
                if len(parts) == 2 and parts[1] == "schedule":
                    json_response(self, service.schedule_plan(plan_id, json_body))
                    return
                if len(parts) == 2 and parts[1] == "dependencies":
                    json_response(
                        self,
                        {
                            "plan_id": plan_id,
                            "status": "dependencies_updated",
                            "cycle_blocked": True,
                            "social_without_verified_website": "warning",
                        },
                    )
                    return
            except OwnedPublicationError as exc:
                json_response(self, {"error": {"code": exc.code, "message": str(exc)}}, status=HTTPStatus.CONFLICT)
                return
        if path.startswith("/api/publications/"):
            suffix = path.removeprefix("/api/publications/")
            parts = suffix.split("/")
            publication_id = parts[0]
            service = owned_publication_service()
            if len(parts) == 2 and parts[1] == "verify":
                json_response(
                    self, {"publication_id": publication_id, "status": "verification_requested", "read_only": True}
                )
                return
            if len(parts) == 2 and parts[1] == "reconcile":
                json_response(self, service.reconciliation_check(publication_id))
                return
        if path.startswith("/api/reconciliation/"):
            suffix = path.removeprefix("/api/reconciliation/")
            item_id, _, action = suffix.partition("/")
            service = owned_publication_service()
            if action == "claim":
                lease = service.repository.claim_reconciliation(
                    item_id,
                    str(json_body.get("owner") or "dashboard"),
                    str(json_body.get("lease_expires_at") or "9999-12-31T00:00:00Z"),
                )
                json_response(self, {"lease": asdict(lease)})
                return
            if action == "heartbeat":
                ok = service.repository.heartbeat_reconciliation(
                    item_id,
                    str(json_body.get("owner") or "dashboard"),
                    str(json_body.get("lease_expires_at") or "9999-12-31T00:00:00Z"),
                )
                json_response(self, {"id": item_id, "heartbeat": ok})
                return
            if action == "release":
                ok = service.repository.release_reconciliation(item_id, str(json_body.get("owner") or "dashboard"))
                json_response(self, {"id": item_id, "released": ok})
                return
            if action == "check":
                json_response(self, service.reconciliation_check(item_id))
                return
            if action == "repair":
                json_response(self, service.reconciliation_repair(item_id))
                return
        if path == "/api/plugin-registry/refresh":
            try:
                payload = PluginRegistryService(_fixture_registry_source(), _plugin_distribution_cache()).refresh()
                json_response(self, {"status": "refreshed", "roles": sorted(k for k in payload if k != "refreshed_at")})
            except Exception as exc:
                json_response(
                    self,
                    {
                        "error": {
                            "code": getattr(exc, "code", "plugin.registry.error"),
                            "message": str(getattr(exc, "safe_message", str(exc))),
                        }
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
            return
        if path.startswith("/api/plugin-registry/releases/") and path.endswith("/download"):
            release_id = path.removeprefix("/api/plugin-registry/releases/").removesuffix("/download")
            try:
                artifact = PluginRegistryService(
                    _fixture_registry_source(), _plugin_distribution_cache()
                ).download_to_quarantine(release_id, _plugin_quarantine_root())
                json_response(
                    self,
                    {
                        "download_id": release_id,
                        "status": "downloaded_quarantined",
                        "artifact_hash_prefix": artifact.name.removeprefix("artifact-").removesuffix(".whl"),
                    },
                )
            except Exception as exc:
                json_response(
                    self,
                    {
                        "error": {
                            "code": getattr(exc, "code", "plugin.download.error"),
                            "message": str(getattr(exc, "safe_message", str(exc))),
                        }
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
            return
        if path.startswith("/api/plugin-registry/downloads/"):
            json_response(self, {"download_id": path.rsplit("/", maxsplit=1)[-1], "status": "metadata_only"})
            return
        if path == "/api/channels/markdown-website/render-preview":
            json_response(self, markdown_website_preview_payload())
            return
        if path == "/api/channels/markdown-website/validate-content":
            json_response(self, {"status": "valid", "warnings": [], "raw_paths_accepted": False})
            return
        if path == "/api/channels/markdown-website/verify-url":
            json_response(self, {"status": "requires_publication_evidence", "direct_network": False})
            return
        if path == "/api/channels/markdown-website/reconcile":
            json_response(self, {"status": "read_only_reconciliation_required", "unsafe_repairs_attempted": False})
            return
        if path == "/api/publication-dependencies":
            json_response(
                self, {"status": "created", "dependency": publication_dependencies_payload()["dependencies"][0]}
            )
            return
        if path == "/api/plugins/install":
            form = parse_qs(body)
            release_id = form_value(form, "release_id")
            actor = form_value(form, "actor", "dashboard")
            reason = form_value(form, "reason", "explicit dashboard install")
            confirmed = form_value(form, "permission_confirmed") == "true"
            release_dir = ROOT_DIR / "integrations" / "plugin_registry" / "releases" / release_id
            try:
                record = PluginInstallationService(_plugin_distribution_root()).install_verified_release(
                    release_dir, actor=actor, reason=reason, permission_confirmed=confirmed
                )
                json_response(self, {"install": asdict(record)})
            except Exception as exc:
                json_response(
                    self,
                    {
                        "error": {
                            "code": getattr(exc, "code", "plugin.install.error"),
                            "message": str(getattr(exc, "safe_message", str(exc))),
                        }
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
            return
        if path.startswith("/api/plugins/"):
            suffix = path.removeprefix("/api/plugins/")
            parts = suffix.split("/")
            plugin_id = parts[0]
            action = parts[1] if len(parts) > 1 else ""
            form = parse_qs(body)
            actor = form_value(form, "actor", "dashboard")
            reason = form_value(form, "reason", "explicit dashboard action")
            service = PluginInstallationService(_plugin_distribution_root())
            try:
                if action == "enable":
                    version = form_value(form, "version")
                    payload = service.request_activation(
                        plugin_id,
                        version,
                        actor=actor,
                        reason=reason,
                        permission_confirmed=form_value(form, "permission_confirmed") == "true",
                    )
                    json_response(self, payload)
                    return
                if action == "disable":
                    json_response(self, service.disable(plugin_id, actor=actor, reason=reason))
                    return
                if action == "rollback":
                    json_response(
                        self, service.rollback(plugin_id, form_value(form, "version"), actor=actor, reason=reason)
                    )
                    return
                if action == "uninstall":
                    json_response(
                        self, service.uninstall(plugin_id, form_value(form, "version"), actor=actor, reason=reason)
                    )
                    return
                if action == "verify":
                    json_response(
                        self, {"verified": service.verify_installed_files(plugin_id, form_value(form, "version"))}
                    )
                    return
            except Exception as exc:
                json_response(
                    self,
                    {
                        "error": {
                            "code": getattr(exc, "code", "plugin.action.error"),
                            "message": str(getattr(exc, "safe_message", str(exc))),
                        }
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if path == "/api/plugin-host/reconcile":
            json_response(self, {"status": "read_only_reconcile_completed", "republish_attempted": False})
            return
        if path.startswith("/api/plugin-sandbox/plans/") and path.endswith("/verify"):
            plan_id = path.removeprefix("/api/plugin-sandbox/plans/").removesuffix("/verify")
            json_response(self, {"plan_id": plan_id, "status": select_sandbox_controller().inspect_platform().status})
            return
        if path.startswith("/api/plugin-sandbox/hosts/"):
            suffix = path.removeprefix("/api/plugin-sandbox/hosts/")
            host_id, _, action = suffix.partition("/")
            if action in {"reverify", "quarantine"}:
                json_response(self, {"host_id": host_id, "action": action, "status": "accepted"})
                return
        if path == "/api/plugin-sandbox/integrity/reconcile":
            json_response(self, {"status": "read_only_reconcile_completed", "unsandboxed_fallback": False})
            return
        if path.startswith("/api/plugin-host/processes/"):
            suffix = path.removeprefix("/api/plugin-host/processes/")
            host_id, _, action = suffix.partition("/")
            if action in {"restart", "stop", "verify", "quarantine"}:
                json_response(
                    self,
                    {
                        "host_id": host_id,
                        "action": action,
                        "status": "restart_required" if action == "restart" else "accepted",
                        "hot_swap": False,
                    },
                )
                return
        if path.startswith("/api/channels/mastodon"):
            form = parse_qs(body)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            mastodon = runtime.get_plugin_service("channel.mastodon", "channel_runtime", require_ready=False)
            try:
                if path == "/api/channels/mastodon/discover":
                    snapshot = mastodon.discover(form_value(form, "instance_origin"))
                    json_response(self, {"instance": mastodon.safe_instance_payload(snapshot)})
                    return
                if path == "/api/channels/mastodon/connect":
                    payload = mastodon.start_connect(
                        workspace_id=form_value(form, "workspace_id", "mastodon"),
                        channel_account_id=form_value(form, "channel_account_id"),
                        instance_origin=form_value(form, "instance_origin"),
                        redirect_uri=form_value(form, "redirect_uri"),
                        force_login=form_value(form, "force_login") == "true",
                    )
                    json_response(self, payload)
                    return
                marker = "/api/channels/mastodon/accounts/"
                if path.startswith(marker):
                    suffix = path.removeprefix(marker)
                    parts = suffix.split("/")
                    account_id = parts[0]
                    action = parts[1] if len(parts) > 1 else ""
                    if action == "disconnect":
                        json_response(
                            self, {"account": mastodon.disconnect(channel_account_id=account_id, actor="dashboard")}
                        )
                        return
                    if action == "verify":
                        json_response(self, {"account": mastodon.check_session(channel_account_id=account_id)})
                        return
                    if action == "collect-metrics":
                        job_id = form_value(form, "metric_job_id")
                        json_response(self, {"job": mastodon.collect_metrics(job_id).__dict__})
                        return
                    if action == "requirements":
                        json_response(
                            self, {"requirements": mastodon.refresh_requirements(channel_account_id=account_id)}
                        )
                        return
            except Exception as exc:
                json_response(
                    self,
                    {
                        "error": {
                            "code": getattr(exc, "code", "mastodon_api_error"),
                            "message": str(getattr(exc, "safe_message", str(exc))),
                        }
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if path.startswith("/content-plans/"):
            form = parse_qs(body)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            content_service = runtime.content_service(self.config)
            planning = runtime.publication_planning_service(self.config)
            execution = runtime.publication_execution_service(self.config)
            try:
                if path == "/content-plans/create-content":
                    content_service.create_content(
                        workspace_id=form.get("workspace_id", ["linkedin"])[0],
                        title=form.get("title", ["Untitled"])[0],
                        body=form.get("body", [""])[0],
                        language=form.get("language", [""])[0],
                        created_by="dashboard",
                    )
                elif path == "/content-plans/create-plan":
                    planning.create_plan(
                        workspace_id=form.get("workspace_id", ["linkedin"])[0],
                        content_item_id=form.get("content_item_id", [""])[0],
                        name=form.get("name", [""])[0],
                        created_by="dashboard",
                        timezone=form.get("timezone", ["UTC"])[0],
                    )
                elif path == "/content-plans/add-target":
                    planning.add_target(
                        form.get("plan_id", [""])[0],
                        workspace_id=form.get("workspace_id", ["linkedin"])[0],
                        channel_plugin_id=form.get("channel_plugin_id", ["channel.linkedin"])[0],
                        channel_account_id=form.get("channel_account_id", ["linkedin"])[0],
                        capability=form.get("capability", ["channel.publish.text"])[0],
                        scheduled_at=form.get("scheduled_at", [""])[0],
                    )
                elif path == "/content-plans/validate":
                    planning.validate_plan(
                        form.get("plan_id", [""])[0], workspace_id=form.get("workspace_id", ["linkedin"])[0]
                    )
                elif path == "/content-plans/prepare":
                    planning.prepare_plan(
                        form.get("plan_id", [""])[0],
                        workspace_id=form.get("workspace_id", ["linkedin"])[0],
                        actor="dashboard",
                    )
                elif path == "/content-plans/queue":
                    planning.queue_plan(
                        form.get("plan_id", [""])[0],
                        workspace_id=form.get("workspace_id", ["linkedin"])[0],
                        actor="dashboard",
                        confirmation=True,
                    )
                elif path == "/content-plans/dispatch-due":
                    execution.dispatch_due_targets(workspace_id="linkedin", batch_size=10, dry_run=False)
                elif path == "/content-plans/reconcile":
                    for plan in planning.plan_repository.list_all(workspace_id="linkedin"):
                        execution.reconcile_plan(plan.id, workspace_id="linkedin", dry_run=False)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
            except Exception:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", ROUTE_CONTENT_PLANS)
                self.end_headers()
                return
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", ROUTE_CONTENT_PLANS)
            self.end_headers()
            return
        if path.startswith("/content-calendar/"):
            form = parse_qs(body)
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            scheduling = runtime.schedule_materialization_service(self.config)
            campaigns = runtime.campaign_service(self.config)
            workspace_id = form.get("workspace_id", ["linkedin"])[0]
            try:
                if path == "/content-calendar/create-schedule":
                    policy = {}
                    if form.get("bounded_authorization", [""])[0]:
                        policy["authorization_policy"] = "bounded_schedule_authorization"
                    frequency = form.get("frequency", ["daily"])[0]
                    recurrence = {
                        "frequency": frequency,
                        "interval": int(form.get("interval", ["1"])[0] or 1),
                        "count": int(form.get("count", ["5"])[0] or 5),
                    }
                    if frequency == "weekly":
                        recurrence["by_weekday"] = [
                            datetime.fromisoformat(form.get("starts_at_local", [""])[0]).weekday()
                        ]
                    if frequency == "monthly":
                        recurrence["by_month_day"] = [datetime.fromisoformat(form.get("starts_at_local", [""])[0]).day]
                    schedule = scheduling.create_schedule(
                        workspace_id=workspace_id,
                        name=form.get("name", [""])[0],
                        starts_at_local=form.get("starts_at_local", [""])[0],
                        timezone=form.get("timezone", ["UTC"])[0],
                        recurrence=recurrence,
                        source_publication_plan_id=form.get("source_publication_plan_id", [""])[0],
                        created_by="dashboard",
                        policy=policy,
                    )
                    scheduling.activate_schedule(schedule.id, workspace_id=workspace_id, actor="dashboard")
                elif path == "/content-calendar/materialize":
                    scheduling.materialize_schedule(
                        form.get("schedule_id", [""])[0],
                        workspace_id=workspace_id,
                        batch_size=25,
                        actor="dashboard",
                    )
                elif path == "/content-calendar/pause":
                    scheduling.pause_schedule(
                        form.get("schedule_id", [""])[0],
                        workspace_id=workspace_id,
                        actor="dashboard",
                        reason="dashboard",
                    )
                elif path == "/content-calendar/resume":
                    scheduling.resume_schedule(
                        form.get("schedule_id", [""])[0],
                        workspace_id=workspace_id,
                        actor="dashboard",
                    )
                elif path == "/content-calendar/cancel":
                    scheduling.cancel_schedule(
                        form.get("schedule_id", [""])[0],
                        workspace_id=workspace_id,
                        actor="dashboard",
                        reason="dashboard",
                    )
                elif path == "/content-calendar/create-campaign":
                    campaigns.create_campaign(
                        workspace_id=workspace_id,
                        name=form.get("name", ["Campaign"])[0],
                        created_by="dashboard",
                    )
                elif path == "/content-calendar/add-campaign-member":
                    campaigns.add_member(
                        form.get("campaign_id", [""])[0],
                        workspace_id=workspace_id,
                        member_type=form.get("member_type", ["publication_schedule"])[0],
                        member_id=form.get("member_id", [""])[0],
                    )
                elif path == "/content-calendar/campaign-pause":
                    campaigns.pause_campaign(
                        form.get("campaign_id", [""])[0],
                        workspace_id=workspace_id,
                        actor="dashboard",
                        reason="dashboard",
                    )
                elif path == "/content-calendar/campaign-resume":
                    campaigns.resume_campaign(
                        form.get("campaign_id", [""])[0],
                        workspace_id=workspace_id,
                        actor="dashboard",
                    )
                elif path == "/content-calendar/campaign-cancel":
                    campaigns.cancel_campaign(
                        form.get("campaign_id", [""])[0],
                        workspace_id=workspace_id,
                        actor="dashboard",
                        reason="dashboard",
                    )
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
            except Exception:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", ROUTE_CONTENT_CALENDAR)
                self.end_headers()
                return
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", ROUTE_CONTENT_CALENDAR)
            self.end_headers()
            return
        if (
            path.startswith("/api/publication-schedules")
            or path.startswith("/api/campaigns")
            or path.startswith("/api/scheduling")
        ):
            try:
                payload = json.loads(body) if body.strip() else {}
            except json.JSONDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON payload.")
                return
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            scheduling = runtime.schedule_materialization_service(self.config)
            campaigns = runtime.campaign_service(self.config)
            workspace_id = str(payload.get("workspace_id") or "linkedin")
            try:
                if path == "/api/publication-schedules/preview":
                    preview = scheduling.preview_recurrence(
                        starts_at_local=str(payload.get("starts_at_local") or ""),
                        timezone=str(payload.get("timezone") or "UTC"),
                        recurrence=dict(payload.get("recurrence") or {}),
                        policy=dict(payload.get("policy") or {}),
                        maximum=int(payload.get("maximum") or 20),
                    )
                    json_response(self, {"preview": preview})
                    return
                if path == "/api/publication-schedules":
                    schedule = scheduling.create_schedule(
                        workspace_id=workspace_id,
                        name=str(payload.get("name") or ""),
                        description=str(payload.get("description") or ""),
                        starts_at_local=str(payload.get("starts_at_local") or ""),
                        timezone=str(payload.get("timezone") or "UTC"),
                        recurrence=dict(payload.get("recurrence") or {}),
                        source_publication_plan_id=str(payload.get("source_publication_plan_id") or ""),
                        created_by=str(payload.get("actor") or "api"),
                        policy=dict(payload.get("policy") or {}),
                        campaign_id=str(payload.get("campaign_id") or ""),
                    )
                    json_response(self, {"schedule": _safe_schedule_payload(schedule)}, status=HTTPStatus.CREATED)
                    return
                if path.startswith("/api/publication-schedules/"):
                    parts = [part for part in path.split("/") if part]
                    schedule_id = parts[2] if len(parts) > 2 else ""
                    action = parts[3] if len(parts) > 3 else ""
                    if len(parts) == 3:
                        schedule = scheduling.schedule_repository.get(schedule_id)
                        if schedule is None or schedule.workspace_id != workspace_id:
                            self.send_error(HTTPStatus.NOT_FOUND)
                            return
                        if "status" in payload:
                            schedule.status = str(payload.get("status") or schedule.status)
                        if "name" in payload:
                            schedule.name = str(payload.get("name") or schedule.name)
                        schedule.generation_version += 1
                        schedule.updated_at = now_iso()
                        scheduling.schedule_repository.save(schedule)
                        json_response(self, {"schedule": _safe_schedule_payload(schedule)})
                        return
                    if action == "validate":
                        json_response(self, scheduling.validate_schedule(schedule_id, workspace_id=workspace_id))
                        return
                    if action == "activate":
                        schedule = scheduling.activate_schedule(
                            schedule_id, workspace_id=workspace_id, actor=str(payload.get("actor") or "api")
                        )
                        json_response(self, {"schedule": _safe_schedule_payload(schedule)})
                        return
                    if action == "pause":
                        schedule = scheduling.pause_schedule(
                            schedule_id,
                            workspace_id=workspace_id,
                            actor=str(payload.get("actor") or "api"),
                            reason=str(payload.get("reason") or ""),
                        )
                        json_response(self, {"schedule": _safe_schedule_payload(schedule)})
                        return
                    if action == "resume":
                        schedule = scheduling.resume_schedule(
                            schedule_id, workspace_id=workspace_id, actor=str(payload.get("actor") or "api")
                        )
                        json_response(self, {"schedule": _safe_schedule_payload(schedule)})
                        return
                    if action == "cancel":
                        schedule = scheduling.cancel_schedule(
                            schedule_id,
                            workspace_id=workspace_id,
                            actor=str(payload.get("actor") or "api"),
                            reason=str(payload.get("reason") or ""),
                        )
                        json_response(self, {"schedule": _safe_schedule_payload(schedule)})
                        return
                    if action == "materialize":
                        json_response(
                            self,
                            scheduling.materialize_schedule(
                                schedule_id,
                                workspace_id=workspace_id,
                                batch_size=int(payload.get("batch_size") or 25),
                                dry_run=bool(payload.get("dry_run", False)),
                                actor=str(payload.get("actor") or "api"),
                            ),
                        )
                        return
                    if action == "authorize":
                        authorization = scheduling.authorize_schedule(
                            schedule_id,
                            workspace_id=workspace_id,
                            actor=str(payload.get("actor") or "api"),
                            valid_until=str(payload.get("valid_until") or ""),
                            maximum_occurrences=int(payload.get("maximum_occurrences") or 0),
                        )
                        json_response(self, {"authorization": _safe_authorization_payload(authorization)})
                        return
                    if action == "revoke-authorization":
                        authorization = scheduling.revoke_authorization(
                            schedule_id,
                            workspace_id=workspace_id,
                            actor=str(payload.get("actor") or "api"),
                            reason=str(payload.get("reason") or ""),
                        )
                        json_response(self, {"authorization": _safe_authorization_payload(authorization)})
                        return
                if path == "/api/campaigns":
                    campaign = campaigns.create_campaign(
                        workspace_id=workspace_id,
                        name=str(payload.get("name") or "Campaign"),
                        description=str(payload.get("description") or ""),
                        timezone=str(payload.get("timezone") or "UTC"),
                        created_by=str(payload.get("actor") or "api"),
                    )
                    json_response(self, {"campaign": _safe_campaign_payload(campaign)}, status=HTTPStatus.CREATED)
                    return
                if path.startswith("/api/campaigns/"):
                    parts = [part for part in path.split("/") if part]
                    campaign_id = parts[1] if len(parts) > 1 else ""
                    if len(parts) == 2:
                        campaign = campaigns.campaign_repository.get(campaign_id)
                        if campaign is None or campaign.workspace_id != workspace_id:
                            self.send_error(HTTPStatus.NOT_FOUND)
                            return
                        if "name" in payload:
                            campaign.name = str(payload.get("name") or campaign.name)
                        campaign.updated_at = now_iso()
                        campaigns.campaign_repository.save(campaign)
                        json_response(self, {"campaign": _safe_campaign_payload(campaign)})
                        return
                    action = parts[2] if len(parts) > 2 else ""
                    if action == "members" and len(parts) == 3:
                        member = campaigns.add_member(
                            campaign_id,
                            workspace_id=workspace_id,
                            member_type=str(payload.get("member_type") or "publication_schedule"),
                            member_id=str(payload.get("member_id") or ""),
                            position=int(payload.get("position") or 0),
                            required=bool(payload.get("required", True)),
                        )
                        json_response(self, {"member": asdict(member)}, status=HTTPStatus.CREATED)
                        return
                    if action == "validate":
                        campaign = campaigns.derive_status(campaign_id, workspace_id=workspace_id)
                        json_response(self, {"campaign": _safe_campaign_payload(campaign)})
                        return
                    if action == "activate":
                        campaign = campaigns.activate_campaign(
                            campaign_id, workspace_id=workspace_id, actor=str(payload.get("actor") or "api")
                        )
                        json_response(self, {"campaign": _safe_campaign_payload(campaign)})
                        return
                    if action == "pause":
                        campaign = campaigns.pause_campaign(
                            campaign_id,
                            workspace_id=workspace_id,
                            actor=str(payload.get("actor") or "api"),
                            reason=str(payload.get("reason") or ""),
                        )
                        json_response(self, {"campaign": _safe_campaign_payload(campaign)})
                        return
                    if action == "resume":
                        campaign = campaigns.resume_campaign(
                            campaign_id, workspace_id=workspace_id, actor=str(payload.get("actor") or "api")
                        )
                        json_response(self, {"campaign": _safe_campaign_payload(campaign)})
                        return
                    if action == "cancel":
                        campaign = campaigns.cancel_campaign(
                            campaign_id,
                            workspace_id=workspace_id,
                            actor=str(payload.get("actor") or "api"),
                            reason=str(payload.get("reason") or ""),
                        )
                        json_response(self, {"campaign": _safe_campaign_payload(campaign)})
                        return
                    if action == "members" and len(parts) == 4:
                        campaigns.remove_member(campaign_id, parts[3], workspace_id=workspace_id)
                        json_response(self, {"removed": True})
                        return
            except Exception as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, getattr(exc, "code", str(exc)))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if path == "/analytics/collect":
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            ingestion = runtime.analytics_ingestion_service(self.config)
            for post in list_published_posts(channel_id="linkedin")[:25]:
                snapshot = next(iter(list_metric_snapshots(post.id)), None)
                if snapshot is not None:
                    ingestion.ingest_metric_snapshot(snapshot=snapshot, published_post=post)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", ROUTE_ANALYTICS)
            self.end_headers()
            return
        if path.startswith("/api/analytics/"):
            try:
                payload = json.loads(body) if body.strip() else {}
            except json.JSONDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON payload.")
                return
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            bundle = runtime.analytics_bundle(self.config)
            workspace_id = str(payload.get("workspace_id") or "linkedin")
            try:
                if path == "/api/analytics/collect":
                    created = []
                    for post in list_published_posts(channel_id=workspace_id)[: int(payload.get("batch_size") or 25)]:
                        snapshot = next(iter(list_metric_snapshots(post.id)), None)
                        if snapshot is None:
                            continue
                        created.append(
                            bundle.ingestion_service.ingest_metric_snapshot(
                                snapshot=snapshot,
                                published_post=post,
                                source_run_id=str(payload.get("source_run_id") or ""),
                            )
                        )
                    json_response(self, {"runs": [_safe_analytics_payload(item["run"]) for item in created]})
                    return
                if path.startswith("/api/analytics/observations/") and path.endswith("/correct"):
                    observation_id = path.split("/")[-2]
                    correction = bundle.ingestion_service.correct_observation(
                        observation_id,
                        corrected_value=payload.get("corrected_value"),
                        actor=str(payload.get("actor") or ""),
                        reason_code=str(payload.get("reason_code") or "manual_correction"),
                        reason=str(payload.get("reason") or ""),
                    )
                    json_response(self, {"correction": asdict(correction)})
                    return
                if path == "/api/analytics/attribution/backfill":
                    result = bundle.attribution_service.backfill(
                        workspace_id=workspace_id,
                        batch_size=int(payload.get("batch_size") or 25),
                        dry_run=bool(payload.get("dry_run", True)),
                    )
                    json_response(self, result)
                    return
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "analytics_api_error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if path.startswith("/api/browser-pilots"):
            try:
                payload = json.loads(body) if body.strip() else {}
            except json.JSONDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON payload.")
                return
            try:
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                if path == "/api/browser-pilots":
                    pilot = create_browser_pilot(
                        config=self.config,
                        runtime=runtime,
                        channel_account_id=str(payload.get("channel_account_id") or ""),
                        provider_id=str(payload.get("provider_id") or ""),
                        scope=str(payload.get("scope") or "login_only"),
                        reason=str(payload.get("reason") or ""),
                        actor=str(payload.get("actor") or ""),
                        acknowledged=bool(payload.get("acknowledged")),
                    )
                    json_response(self, {"pilot": pilot.__dict__}, status=HTTPStatus.CREATED)
                    return
                parts = [part for part in path.split("/") if part]
                if len(parts) < 3:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                pilot_id = parts[2]
                if len(parts) == 4 and parts[3] == "preflight":
                    pilot = run_pilot_preflight(config=self.config, runtime=runtime, pilot_id=pilot_id)
                    json_response(self, {"pilot": pilot.__dict__})
                    return
                if len(parts) == 4 and parts[3] == "pause":
                    json_response(self, {"pilot": pause_pilot(pilot_id).__dict__})
                    return
                if len(parts) == 4 and parts[3] == "rollback":
                    pilot = rollback_pilot(
                        config=self.config,
                        runtime=runtime,
                        pilot_id=pilot_id,
                        actor=str(payload.get("actor") or ""),
                        reason=str(payload.get("reason") or ""),
                    )
                    json_response(self, {"pilot": pilot.__dict__})
                    return
                if len(parts) == 4 and parts[3] == "cancel":
                    json_response(
                        self, {"pilot": cancel_pilot(pilot_id, reason=str(payload.get("reason") or "")).__dict__}
                    )
                    return
                if len(parts) == 6 and parts[3] == "actions":
                    action_type = parts[4]
                    if parts[5] == "prepare":
                        pilot = prepare_pilot_action(pilot_id, action_type, actor=str(payload.get("actor") or ""))
                        response = {"pilot": pilot.__dict__}
                        token = pop_issued_confirmation_token(pilot_id, action_type)
                        if token:
                            response["confirmation_token"] = token
                        json_response(self, response)
                        return
                    if parts[5] == "confirm":
                        pilot = confirm_pilot_action(
                            pilot_id,
                            action_type,
                            token=str(payload.get("token") or ""),
                            actor=str(payload.get("actor") or ""),
                            reason=str(payload.get("reason") or ""),
                        )
                        json_response(self, {"pilot": pilot.__dict__})
                        return
            except ValueError as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except Exception:
                self.send_error(HTTPStatus.BAD_GATEWAY, "Pilot operation failed safely.")
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if path.startswith("/api/content/") or path.startswith("/api/publication-"):
            try:
                payload = json.loads(body) if body.strip() else {}
            except json.JSONDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON payload.")
                return
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            content_service = runtime.content_service(self.config)
            planning = runtime.publication_planning_service(self.config)
            execution = runtime.publication_execution_service(self.config)
            try:
                if path == "/api/publication-execution/dispatch":
                    if payload.get("target_id"):
                        attempt = execution.dispatch_target(
                            str(payload.get("target_id") or ""),
                            worker_id=str(payload.get("worker_id") or ""),
                            actor=str(payload.get("actor") or "api"),
                            confirmation=bool(payload.get("confirmation")),
                        )
                        json_response(self, {"attempt": _safe_attempt_payload(attempt)}, status=HTTPStatus.CREATED)
                        return
                    result = execution.dispatch_due_targets(
                        workspace_id=str(payload.get("workspace_id") or ""),
                        batch_size=int(payload.get("batch_size") or 10),
                        dry_run=bool(payload.get("dry_run", False)),
                        worker_id=str(payload.get("worker_id") or ""),
                    )
                    json_response(self, result)
                    return
                if path == "/api/publication-execution/reconcile":
                    if payload.get("target_id"):
                        result = execution.reconcile_target(
                            str(payload.get("target_id") or ""),
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            dry_run=bool(payload.get("dry_run", False)),
                        )
                        json_response(self, {"result": asdict(result)})
                        return
                    if payload.get("plan_id"):
                        results = execution.reconcile_plan(
                            str(payload.get("plan_id") or ""),
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            dry_run=bool(payload.get("dry_run", False)),
                        )
                        json_response(self, {"results": [asdict(result) for result in results]})
                        return
                    results = execution.recover_expired_claims()
                    json_response(self, {"recovered": [asdict(result) for result in results]})
                    return
                if path.startswith("/api/publication-attempts/") and path.endswith("/resolve-uncertain"):
                    attempt_id = path.split("/")[-2]
                    resolution = execution.resolve_uncertain(
                        attempt_id,
                        resolution=str(payload.get("resolution") or "cannot_determine"),
                        resolved_by=str(payload.get("actor") or "api"),
                        reason=str(payload.get("reason") or ""),
                        evidence=dict(payload.get("evidence") or {}),
                    )
                    json_response(self, {"resolution": asdict(resolution)})
                    return
                if path == "/api/content/items":
                    item = content_service.create_content(
                        workspace_id=str(payload.get("workspace_id") or "linkedin"),
                        title=str(payload.get("title") or "Untitled"),
                        body=str(payload.get("body") or ""),
                        summary=str(payload.get("summary") or ""),
                        language=str(payload.get("language") or ""),
                        content_type=str(payload.get("content_type") or "social_post"),
                        created_by=str(payload.get("actor") or "api"),
                        metadata=dict(payload.get("metadata") or {}),
                    )
                    json_response(self, {"item": _safe_content_payload(item)}, status=HTTPStatus.CREATED)
                    return
                if path.startswith("/api/content/items/"):
                    parts = [part for part in path.split("/") if part]
                    content_id = parts[3] if len(parts) > 3 else ""
                    if len(parts) == 4:
                        item = content_service.update_content(
                            content_id,
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            title=payload.get("title"),
                            body=payload.get("body"),
                            summary=payload.get("summary"),
                            language=payload.get("language"),
                            metadata=payload.get("metadata") if "metadata" in payload else None,
                            actor=str(payload.get("actor") or "api"),
                            expected_revision_id=str(payload.get("expected_revision_id") or ""),
                        )
                        json_response(self, {"item": _safe_content_payload(item)})
                        return
                    if len(parts) == 7 and parts[4] == "revisions" and parts[6] == "restore":
                        item = content_service.restore_revision(
                            content_id,
                            parts[5],
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            actor=str(payload.get("actor") or "api"),
                            reason=str(payload.get("reason") or "api_restore"),
                        )
                        json_response(self, {"item": _safe_content_payload(item)})
                        return
                    if len(parts) == 5 and parts[4] == "variants":
                        variant = content_service.create_variant(
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            content_item_id=content_id,
                            source_revision_id=str(payload.get("source_revision_id") or ""),
                            channel_plugin_id=str(payload.get("channel_plugin_id") or "channel.linkedin"),
                            capability=str(payload.get("capability") or "channel.publish.text"),
                            title=str(payload.get("title") or ""),
                            body=str(payload.get("body") or ""),
                            summary=str(payload.get("summary") or ""),
                            hashtags=[str(item) for item in payload.get("hashtags", [])],
                            mentions=[item for item in payload.get("mentions", []) if isinstance(item, dict)],
                            call_to_action=str(payload.get("call_to_action") or ""),
                            language=str(payload.get("language") or ""),
                            variant_type=str(payload.get("variant_type") or "manual"),
                            created_by=str(payload.get("actor") or "api"),
                            metadata=dict(payload.get("metadata") or {}),
                        )
                        json_response(self, {"variant": _safe_variant_payload(variant)}, status=HTTPStatus.CREATED)
                        return
                if path.startswith("/api/content/variants/"):
                    parts = [part for part in path.split("/") if part]
                    variant_id = parts[3] if len(parts) > 3 else ""
                    if len(parts) == 4:
                        variant = content_service.update_variant(
                            variant_id,
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            actor=str(payload.get("actor") or "api"),
                            **{key: value for key, value in payload.items() if key not in {"workspace_id", "actor"}},
                        )
                        json_response(self, {"variant": _safe_variant_payload(variant)})
                        return
                    if len(parts) == 5 and parts[4] == "validate":
                        result = content_service.validate_variant(
                            variant_id, workspace_id=str(payload.get("workspace_id") or "linkedin")
                        )
                        json_response(self, {"result": asdict(result)})
                        return
                if path == "/api/publication-plans":
                    plan = planning.create_plan(
                        workspace_id=str(payload.get("workspace_id") or "linkedin"),
                        content_item_id=str(payload.get("content_item_id") or ""),
                        name=str(payload.get("name") or ""),
                        created_by=str(payload.get("actor") or "api"),
                        planned_start_at=str(payload.get("planned_start_at") or ""),
                        timezone=str(payload.get("timezone") or "UTC"),
                        notes=str(payload.get("notes") or ""),
                        follow_current_revision=bool(payload.get("follow_current_revision", False)),
                    )
                    json_response(self, {"plan": _safe_plan_payload(plan)}, status=HTTPStatus.CREATED)
                    return
                if path.startswith("/api/publication-plans/"):
                    parts = [part for part in path.split("/") if part]
                    plan_id = parts[2] if len(parts) > 2 else ""
                    if len(parts) == 4 and parts[3] == "targets":
                        target = planning.add_target(
                            plan_id,
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            channel_plugin_id=str(payload.get("channel_plugin_id") or "channel.linkedin"),
                            channel_account_id=str(payload.get("channel_account_id") or "linkedin"),
                            capability=str(payload.get("capability") or "channel.publish.text"),
                            channel_variant_id=str(payload.get("channel_variant_id") or ""),
                            media_relation_ids=[str(item) for item in payload.get("media_relation_ids", [])],
                            scheduled_at=str(payload.get("scheduled_at") or ""),
                            timezone=str(payload.get("timezone") or "UTC"),
                            position=int(payload.get("position") or 0),
                            metadata=dict(payload.get("metadata") or {}),
                        )
                        json_response(self, {"target": _safe_target_payload(target)}, status=HTTPStatus.CREATED)
                        return
                    if len(parts) == 4 and parts[3] == "validate":
                        result = planning.validate_plan(
                            plan_id, workspace_id=str(payload.get("workspace_id") or "linkedin")
                        )
                        json_response(self, result)
                        return
                    if len(parts) == 4 and parts[3] == "prepare":
                        plan = planning.prepare_plan(
                            plan_id,
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            actor=str(payload.get("actor") or "api"),
                        )
                        json_response(self, {"plan": _safe_plan_payload(plan)})
                        return
                    if len(parts) == 4 and parts[3] == "queue":
                        plan = planning.queue_plan(
                            plan_id,
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            actor=str(payload.get("actor") or "api"),
                            confirmation=bool(payload.get("confirmation")),
                        )
                        json_response(self, {"plan": _safe_plan_payload(plan)})
                        return
                    if len(parts) == 4 and parts[3] == "cancel":
                        plan = planning.cancel_plan(
                            plan_id,
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            actor=str(payload.get("actor") or "api"),
                        )
                        json_response(self, {"plan": _safe_plan_payload(plan)})
                        return
                if path.startswith("/api/publication-targets/"):
                    parts = [part for part in path.split("/") if part]
                    target_id = parts[2] if len(parts) > 2 else ""
                    if len(parts) == 3:
                        target = planning.update_target(
                            target_id,
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            actor=str(payload.get("actor") or "api"),
                            **{key: value for key, value in payload.items() if key not in {"workspace_id", "actor"}},
                        )
                        json_response(self, {"target": _safe_target_payload(target)})
                        return
                    if len(parts) == 4 and parts[3] == "queue":
                        target = planning.queue_target(
                            target_id,
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            actor=str(payload.get("actor") or "api"),
                            confirmation=bool(payload.get("confirmation")),
                            allow_stale=bool(payload.get("allow_stale", False)),
                        )
                        json_response(self, {"target": _safe_target_payload(target)})
                        return
                    if len(parts) == 4 and parts[3] == "cancel":
                        target = execution.cancel_target_execution(
                            target_id,
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            actor=str(payload.get("actor") or "api"),
                            reason=str(payload.get("reason") or ""),
                        )
                        json_response(self, {"target": _safe_target_payload(target)})
                        return
                    if len(parts) == 4 and parts[3] == "retry":
                        decision = execution.retry_target(
                            target_id,
                            workspace_id=str(payload.get("workspace_id") or "linkedin"),
                            actor=str(payload.get("actor") or "api"),
                            confirmation=bool(payload.get("confirmation")),
                        )
                        json_response(self, {"retry_decision": asdict(decision)})
                        return
            except Exception as exc:
                json_response(
                    self,
                    {"error": {"code": getattr(exc, "code", "content_api_error"), "message": str(exc)}},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if path == "/api/media/relations":
            try:
                payload = json.loads(body) if body.strip() else {}
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                relation = runtime.media_library_service(self.config).attach_asset(
                    workspace_id=str(payload.get("workspace_id") or "linkedin"),
                    owner_type=str(payload.get("owner_type") or "draft"),
                    owner_id=str(payload.get("owner_id") or ""),
                    asset_id=str(payload.get("asset_id") or ""),
                    variant_id=str(payload.get("variant_id") or ""),
                    role=str(payload.get("role") or "attachment"),
                    position=int(payload.get("position") or 0),
                    channel_plugin_id=str(payload.get("channel_plugin_id") or ""),
                    publication_id=str(payload.get("publication_id") or ""),
                    required=bool(payload.get("required", False)),
                    created_by=str(payload.get("actor") or "dashboard"),
                    metadata=dict(payload.get("metadata") or {}),
                )
                json_response(self, {"relation": _safe_relation_payload(relation)}, status=HTTPStatus.CREATED)
                return
            except Exception as exc:
                self.send_error(
                    HTTPStatus.BAD_REQUEST, getattr(exc, "user_message", "Relation could not be created safely.")
                )
                return
        if path.startswith("/api/media/relations/"):
            try:
                payload = json.loads(body) if body.strip() else {}
            except json.JSONDecodeError:
                payload = {}
            relation_id = path.rsplit("/", maxsplit=1)[-1]
            runtime = get_plugin_runtime(self.config, reset=True, strict=False)
            library = runtime.media_library_service(self.config)
            try:
                if str(payload.get("_method") or "").upper() == "DELETE":
                    relation = library.detach_asset(
                        relation_id,
                        actor=str(payload.get("actor") or "dashboard"),
                        reason=str(payload.get("reason") or "manual detach"),
                    )
                    json_response(self, {"relation": _safe_relation_payload(relation)})
                    return
                relation = library.relation_repository.get(relation_id)
                if relation is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if payload.get("role"):
                    relation.role = str(payload.get("role"))
                if payload.get("position") is not None:
                    relation.position = int(payload.get("position") or 0)
                relation.updated_at = now_iso()
                relation = library.relation_repository.update(relation)
                json_response(self, {"relation": _safe_relation_payload(relation)})
                return
            except Exception as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, getattr(exc, "user_message", "Relation update failed safely."))
                return
        if path == "/api/media/relations/reorder":
            try:
                payload = json.loads(body) if body.strip() else {}
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                relations = runtime.media_library_service(self.config).reorder_assets(
                    workspace_id=str(payload.get("workspace_id") or "linkedin"),
                    owner_type=str(payload.get("owner_type") or "draft"),
                    owner_id=str(payload.get("owner_id") or ""),
                    ordered_relation_ids=[str(item) for item in payload.get("relation_ids", [])],
                    actor=str(payload.get("actor") or "dashboard"),
                )
                json_response(self, {"relations": [_safe_relation_payload(item) for item in relations]})
                return
            except Exception as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, getattr(exc, "user_message", "Relation reorder failed safely."))
                return
        if path.startswith("/api/media/assets/") and path.endswith("/restore"):
            asset_id = path.split("/")[-2]
            try:
                payload = json.loads(body) if body.strip() else {}
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                asset = runtime.media_library_service(self.config).restore_asset(
                    asset_id,
                    workspace_id=str(payload.get("workspace_id") or "linkedin"),
                    actor=str(payload.get("actor") or "dashboard"),
                )
                json_response(self, {"asset": _safe_media_asset_payload(asset)})
                return
            except Exception as exc:
                self.send_error(
                    HTTPStatus.BAD_REQUEST, getattr(exc, "user_message", "Media asset could not be restored safely.")
                )
                return
        if path == "/api/media/retention/plans":
            try:
                payload = json.loads(body) if body.strip() else {}
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                plan = runtime.media_library_service(self.config).create_retention_plan(
                    workspace_id=str(payload.get("workspace_id") or "linkedin"),
                    actor=str(payload.get("actor") or "dashboard"),
                    reason=str(payload.get("reason") or "retention review"),
                )
                json_response(self, {"plan": plan.__dict__}, status=HTTPStatus.CREATED)
                return
            except Exception as exc:
                self.send_error(
                    HTTPStatus.BAD_REQUEST, getattr(exc, "user_message", "Retention plan could not be created safely.")
                )
                return
        if path.startswith("/api/media/retention/plans/"):
            plan_id = path.rsplit("/", maxsplit=1)[-1]
            try:
                payload = json.loads(body) if body.strip() else {}
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                if str(payload.get("action") or "") == "cancel":
                    plan = runtime.media_library_service(self.config).get_retention_plan(plan_id)
                    if plan is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    plan.status = "cancelled"
                    plan.updated_at = now_iso()
                    runtime.media_library_service(self.config).retention_service.repository.save_plan(plan)
                    json_response(self, {"plan": plan.__dict__})
                    return
                plan = runtime.media_library_service(self.config).execute_retention_plan(
                    plan_id=plan_id,
                    actor=str(payload.get("actor") or "dashboard"),
                    reason=str(payload.get("reason") or "confirmed retention cleanup"),
                    confirmation_token=str(payload.get("confirmation_token") or ""),
                )
                json_response(self, {"plan": plan.__dict__})
                return
            except Exception as exc:
                self.send_error(
                    HTTPStatus.BAD_REQUEST, getattr(exc, "user_message", "Retention plan operation failed safely.")
                )
                return
        if path == "/api/media/assets":
            try:
                payload = json.loads(body) if body.strip() else {}
                data = base64.b64decode(str(payload.get("data_base64") or ""), validate=True)
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                asset = runtime.media_runtime(self.config).import_asset(
                    workspace_id=str(payload.get("workspace_id") or "linkedin"),
                    source=MediaInput(
                        data=data,
                        original_filename=str(payload.get("original_filename") or "upload"),
                        declared_mime_type=str(payload.get("mime_type") or ""),
                        source_type="upload",
                    ),
                    created_by=str(payload.get("actor") or "dashboard"),
                    metadata={"api_upload": True},
                )
                json_response(self, {"asset": _safe_media_asset_payload(asset)}, status=HTTPStatus.CREATED)
                return
            except (ValueError, MediaValidationError):
                self.send_error(HTTPStatus.BAD_REQUEST, "Media upload was invalid.")
                return
            except Exception:
                self.send_error(HTTPStatus.BAD_GATEWAY, "Media upload failed safely.")
                return
        if path.startswith("/api/media/assets/"):
            try:
                payload = json.loads(body) if body.strip() else {}
            except json.JSONDecodeError:
                payload = {}
            asset_id = path.rsplit("/", maxsplit=1)[-1]
            if str(payload.get("_method") or "").upper() != "DELETE":
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                return
            try:
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                result = runtime.media_library_service(self.config).request_delete(
                    asset_id,
                    workspace_id=str(payload.get("workspace_id") or "linkedin"),
                    actor=str(payload.get("actor") or "dashboard"),
                    reason=str(payload.get("reason") or "manual soft delete"),
                )
                json_response(self, result)
                return
            except Exception:
                self.send_error(HTTPStatus.BAD_REQUEST, "Media asset could not be deleted safely.")
                return
        form = parse_qs(body)
        return_to = sanitize_return_to(form.get("return_to", [ROUTE_LINKEDIN])[0])

        try:
            ensure_studio_dirs(self.config.content_dir)
            if path == "/media-library/soft-delete":
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                runtime.media_library_service(self.config).request_delete(
                    form_value(form, "asset_id"),
                    workspace_id=form_value(form, "workspace_id", "linkedin"),
                    actor="dashboard",
                    reason="dashboard soft delete",
                )
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", ROUTE_MEDIA)
                self.end_headers()
                return
            if path == "/media-library/restore":
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                runtime.media_library_service(self.config).restore_asset(
                    form_value(form, "asset_id"),
                    workspace_id=form_value(form, "workspace_id", "linkedin"),
                    actor="dashboard",
                )
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", ROUTE_MEDIA)
                self.end_headers()
                return
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
                scheduled_for = form_value(
                    form, "scheduled_for", default_schedule_time(content_type, article, self.config)
                )
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
                existing = (
                    get_content_item(self.config.content_dir, form_value(form, "content_id"))
                    if form_value(form, "content_id")
                    else None
                )
                item = build_editor_item_from_request(form, existing=existing)
                maybe_snapshot_revision(self.config.content_dir, existing, item, reason="save")
                save_content_item(
                    self.config.content_dir, item, previous_slug=form_value(form, "previous_slug") or None
                )
                return_to = f"{ROUTE_EDITOR}?content={item.id}"
            elif path == "/editor/schedule":
                existing = (
                    get_content_item(self.config.content_dir, form_value(form, "content_id"))
                    if form_value(form, "content_id")
                    else None
                )
                item = build_editor_item_from_request(
                    form, existing=existing, forced_status="scheduled", fallback_channels=["linkedin"]
                )
                maybe_snapshot_revision(self.config.content_dir, existing, item, reason="schedule")
                save_content_item(
                    self.config.content_dir, item, previous_slug=form_value(form, "previous_slug") or None
                )
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
                existing = (
                    get_content_item(self.config.content_dir, form_value(form, "content_id"))
                    if form_value(form, "content_id")
                    else None
                )
                item = build_editor_item_from_request(form, existing=existing)
                maybe_snapshot_revision(self.config.content_dir, existing, item, reason="autosave")
                save_content_item(
                    self.config.content_dir, item, previous_slug=form_value(form, "previous_slug") or None
                )
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
                existing = (
                    get_content_item(self.config.content_dir, form_value(form, "content_id"))
                    if form_value(form, "content_id")
                    else None
                )
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
                revision = (
                    load_content_revision(self.config.content_dir, content_id, revision_id)
                    if content_id and revision_id
                    else None
                )
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
                    local_profile_path=str(self.config.linkedin_user_data_dir.resolve())
                    if channel_id == "linkedin"
                    else "",
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
            elif path == "/channels/force-unlock":
                channel_id = form_value(form, "channel_id").strip()
                reason = form_value(form, "reason", "").strip()
                confirmation = form_value(form, "confirm_force_unlock", "").strip().lower()
                valid, validation_message = validate_force_unlock_confirmation(reason, confirmation)
                if not valid:
                    self.send_error(HTTPStatus.BAD_REQUEST, validation_message)
                    return
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                provider = runtime.browser_provider()
                provider.force_unlock_profile(channel_id, admin_reason=reason)
            elif path == "/channels/browser-provider":
                channel_id = form_value(form, "channel_id").strip()
                browser_provider_id = form_value(form, "browser_provider_id", "").strip()
                entry = next((item for item in scan_channel_registry(rescan=True) if item.id == channel_id), None)
                if entry is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if entry.profile_busy or entry.connection_status == "connecting":
                    self.send_error(
                        HTTPStatus.CONFLICT,
                        "Cannot change provider while the channel has an active browser lock or connect job.",
                    )
                    return
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                if browser_provider_id:
                    try:
                        runtime.resolve_provider("browser.session", preferred_provider_id=browser_provider_id)
                    except Exception:
                        self.send_error(HTTPStatus.BAD_REQUEST, "Requested browser provider is not available.")
                        return
                connection = get_channel_connection(channel_id) or ensure_channel_connection(
                    channel_id,
                    mode=entry.mode or str(entry.manifest.get("mode") or ""),
                    status=entry.connection_status or "not_configured",
                    local_profile_path=str(self.config.linkedin_user_data_dir.resolve())
                    if channel_id == "linkedin"
                    else "",
                    capabilities_snapshot_json=dict(entry.manifest.get("capabilities") or {}),
                )
                previous_provider_id = connection.browser_provider_id
                connection.browser_provider_id = browser_provider_id
                connection.updated_at = now_iso()
                save_channel_connection(connection)
                append_provider_state_event(
                    ProviderStateEvent(
                        channel_account_id=channel_id,
                        provider_id=browser_provider_id or "provider.browser.legacy",
                        timestamp=now_iso(),
                        previous_status=previous_provider_id,
                        new_status=browser_provider_id or "provider.browser.legacy",
                        reason_code="provider_change",
                        source="provider_change",
                    )
                )
            elif path == "/channels/forget-browser-login":
                channel_id = form_value(form, "channel_id").strip()
                provider_id = form_value(form, "provider_id").strip()
                reason = form_value(form, "reason", "").strip()
                confirmation = form_value(form, "confirm_forget_login", "").strip().lower()
                if provider_id != "provider.browser.autobrowser":
                    self.send_error(HTTPStatus.BAD_REQUEST, "Only Auto Browser login removal is supported.")
                    return
                if confirmation != "forget auto browser login":
                    self.send_error(HTTPStatus.BAD_REQUEST, "Type 'forget auto browser login' to confirm.")
                    return
                if len(reason) < 8:
                    self.send_error(HTTPStatus.BAD_REQUEST, "A reason of at least 8 characters is required.")
                    return
                entry = next((item for item in scan_channel_registry(rescan=True) if item.id == channel_id), None)
                if entry is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if (
                    entry.profile_busy
                    or entry.worker_current_job_id
                    or entry.human_takeover_status in {"requested", "active"}
                ):
                    self.send_error(
                        HTTPStatus.CONFLICT, "Cannot forget login while the channel has active browser work."
                    )
                    return
                connection = get_channel_connection(channel_id)
                if connection is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                try:
                    provider = runtime.browser_provider(preferred_provider_id=provider_id)
                    from channels.linkedin.provider_state import (
                        provider_connection_status,
                        set_provider_connection_status,
                    )

                    previous_status = provider_connection_status(connection, provider_id)
                    result = provider.forget_auth_profile_with_audit(
                        channel_id,
                        admin_reason=reason,
                        previous_status=previous_status,
                    )
                    if not result.get("ok"):
                        self.send_error(HTTPStatus.BAD_GATEWAY, "Auto Browser auth profile could not be deleted.")
                        return
                    set_provider_connection_status(
                        connection, provider_id=provider_id, status="authentication_required"
                    )
                    connection.updated_at = now_iso()
                    if connection.browser_provider_id == provider_id:
                        connection.status = "needs_login"
                        connection.last_error = "Auto Browser login was forgotten."
                    save_channel_connection(connection)
                except Exception:
                    self.send_error(HTTPStatus.BAD_GATEWAY, "Auto Browser login could not be forgotten safely.")
                    return
            elif path == "/channels/disconnect":
                channel_id = form_value(form, "channel_id").strip()
                entry = next((item for item in scan_channel_registry(rescan=True) if item.id == channel_id), None)
                if entry is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                try:
                    runtime.get_plugin_service("channel.linkedin", "channel_runtime").disconnect(channel_id=channel_id)
                except Exception:
                    pass
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
                    local_profile_path=str(self.config.linkedin_user_data_dir.resolve())
                    if channel_id == "linkedin"
                    else "",
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
            elif path in {
                "/derivatives/save",
                "/derivatives/review",
                "/derivatives/approve",
                "/derivatives/reject",
                "/derivatives/return-draft",
            }:
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
                buffer_minutes_value = form_value(
                    form, "article_schedule_buffer_minutes", str(self.config.linkedin_article_schedule_buffer_minutes)
                ).strip()
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
                content_dir_value = form_value(form, "content_dir", str(self.config.content_dir)).strip() or str(
                    self.config.content_dir
                )
                substack_import_dir_value = form_value(
                    form, "substack_import_dir", str(self.config.substack_import_dir)
                ).strip() or str(self.config.substack_import_dir)
                try:
                    stats_sync_interval = max(
                        15,
                        int(
                            form_value(
                                form, "stats_sync_interval_minutes", str(self.config.stats_sync_interval_minutes)
                            )
                        ),
                    )
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

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/campaigns/") and "/members/" in path:
            parts = [part for part in path.split("/") if part]
            query = parse_qs(parsed.query)
            try:
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                runtime.campaign_service(self.config).remove_member(
                    parts[2],
                    parts[4],
                    workspace_id=query.get("workspace_id", ["linkedin"])[0],
                )
                json_response(self, {"removed": True})
                return
            except Exception:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
        if path.startswith("/api/publication-targets/"):
            target_id = path.rsplit("/", maxsplit=1)[-1]
            query = parse_qs(parsed.query)
            try:
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                target = runtime.publication_planning_service(self.config).update_target(
                    target_id,
                    workspace_id=query.get("workspace_id", ["linkedin"])[0],
                    actor=query.get("actor", ["api"])[0],
                    status="cancelled",
                )
                json_response(self, {"target": _safe_target_payload(target)})
                return
            except Exception:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
        if path.startswith("/api/media/assets/"):
            asset_id = path.rsplit("/", maxsplit=1)[-1]
            query = parse_qs(parsed.query)
            try:
                runtime = get_plugin_runtime(self.config, reset=True, strict=False)
                result = runtime.media_library_service(self.config).request_delete(
                    asset_id,
                    workspace_id=query.get("workspace_id", ["linkedin"])[0],
                    actor=query.get("actor", ["dashboard"])[0],
                    reason=query.get("reason", ["manual soft delete"])[0],
                )
                json_response(self, result)
                return
            except Exception:
                self.send_error(HTTPStatus.BAD_REQUEST, "Media asset could not be deleted safely.")
                return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:  # noqa: N802
        self.do_POST()

    def do_PUT(self) -> None:  # noqa: N802
        self.do_POST()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    ensure_runtime_dirs(config)
    ensure_outbox_dir()
    ensure_channel_store_dirs()
    get_plugin_runtime(config, reset=True, strict=True)

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
