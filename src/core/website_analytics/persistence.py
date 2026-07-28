"""SQLite persistence for website analytics provider accounts and sync state."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.core.owned_publication.persistence import DatabaseOwnedPublicationRepository, default_database_path

from .contracts import WEBSITE_ANALYTICS_PROVIDER_FRAMEWORK_VERSION
from .errors import WebsiteAnalyticsError
from .models import (
    ProviderMetricObservation,
    ProviderRateLimitState,
    WebsiteAnalyticsAccount,
    WebsiteAnalyticsAttribution,
    WebsiteAnalyticsDataQualityReport,
    WebsiteAnalyticsEventMapping,
    WebsiteAnalyticsSyncState,
    stable_checksum,
    utc_now_iso,
)

WEBSITE_ANALYTICS_SCHEMA_VERSION = 1
WEBSITE_ANALYTICS_MIGRATION_ID = "001_website_analytics_provider_framework"
WEBSITE_ANALYTICS_MIGRATION_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS website_analytics_schema_migrations (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_analytics_accounts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    origin_reference_id TEXT NOT NULL,
    site_identifier TEXT NOT NULL,
    secret_reference_id TEXT NOT NULL,
    timezone TEXT NOT NULL,
    default_date_granularity TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS website_analytics_event_mappings (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    provider_event_name TEXT NOT NULL,
    provider_property_filters_json TEXT NOT NULL,
    internal_event_type TEXT NOT NULL,
    cta_id TEXT NOT NULL,
    conversion_type TEXT NOT NULL,
    conversion_value_policy TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS website_analytics_sync_states (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    site_identifier TEXT NOT NULL,
    sync_type TEXT NOT NULL,
    status TEXT NOT NULL,
    cursor TEXT NOT NULL,
    high_watermark TEXT NOT NULL,
    correction_window_start TEXT NOT NULL,
    last_started_at TEXT NOT NULL,
    last_completed_at TEXT NOT NULL,
    last_successful_at TEXT NOT NULL,
    next_run_at TEXT NOT NULL,
    attempt_count INTEGER NOT NULL,
    last_error_code TEXT NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    version INTEGER NOT NULL,
    UNIQUE (workspace_id, account_id, site_identifier, sync_type)
);
CREATE TABLE IF NOT EXISTS website_analytics_sync_attempts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    safe_error_code TEXT NOT NULL,
    query_fingerprint TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_analytics_provider_cursors (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    site_identifier TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    cursor_json TEXT NOT NULL,
    cursor_checksum TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_analytics_rate_limits (
    account_id TEXT PRIMARY KEY,
    limit_value INTEGER NOT NULL,
    remaining INTEGER NOT NULL,
    reset_at TEXT NOT NULL,
    retry_after INTEGER NOT NULL,
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_analytics_attributions (
    observation_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    observed_value REAL NOT NULL,
    observation_checksum TEXT NOT NULL,
    correction_of_observation_id TEXT NOT NULL,
    attribution_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_analytics_quality_reports (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    site_identifier TEXT NOT NULL,
    period TEXT NOT NULL,
    report_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

ACCOUNT_COLUMNS = (
    "id, workspace_id, provider_id, display_name, origin_reference_id, site_identifier, secret_reference_id, "
    "timezone, default_date_granularity, enabled, status, created_at, updated_at, version"
)
MAPPING_COLUMNS = (
    "id, workspace_id, account_id, provider_event_name, provider_property_filters_json, internal_event_type, "
    "cta_id, conversion_type, conversion_value_policy, enabled, version"
)
SYNC_COLUMNS = (
    "id, workspace_id, account_id, site_identifier, sync_type, status, cursor, high_watermark, "
    "correction_window_start, last_started_at, last_completed_at, last_successful_at, next_run_at, "
    "attempt_count, last_error_code, lease_owner, lease_expires_at, version"
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def migration_checksum() -> str:
    return stable_checksum(WEBSITE_ANALYTICS_MIGRATION_SQL)


@contextmanager
def _connect(path: Path) -> Iterable[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
    finally:
        connection.close()


class DatabaseWebsiteAnalyticsRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or default_database_path()
        self.owned_repository = DatabaseOwnedPublicationRepository(self.database_path)
        self.migrate()

    def migrate(self) -> dict[str, Any]:
        checksum = migration_checksum()
        with _connect(self.database_path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS website_analytics_schema_migrations "
                "(id TEXT PRIMARY KEY, version INTEGER NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL, status TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT checksum, status FROM website_analytics_schema_migrations WHERE id=?",
                (WEBSITE_ANALYTICS_MIGRATION_ID,),
            ).fetchone()
            if row and (row["checksum"] != checksum or row["status"] != "applied"):
                raise WebsiteAnalyticsError(
                    "website_analytics.schema_incompatible", "Website analytics schema mismatch."
                )
            connection.executescript(WEBSITE_ANALYTICS_MIGRATION_SQL)
            connection.execute(
                "INSERT OR REPLACE INTO website_analytics_schema_migrations VALUES (?, ?, ?, ?, 'applied')",
                (WEBSITE_ANALYTICS_MIGRATION_ID, WEBSITE_ANALYTICS_SCHEMA_VERSION, checksum, utc_now_iso()),
            )
        return {
            "framework_version": WEBSITE_ANALYTICS_PROVIDER_FRAMEWORK_VERSION,
            "schema_version": WEBSITE_ANALYTICS_SCHEMA_VERSION,
            "checksum": checksum,
            "status": "current",
        }

    def create_account(self, account: WebsiteAnalyticsAccount) -> WebsiteAnalyticsAccount:
        if not account.secret_reference_id or account.secret_reference_id.startswith("raw:"):
            raise WebsiteAnalyticsError("website_analytics.secret_reference_required", "Use a secret reference.")
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO website_analytics_accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    account.id,
                    account.workspace_id,
                    account.provider_id,
                    account.display_name,
                    account.origin_reference_id,
                    account.site_identifier,
                    account.secret_reference_id,
                    account.timezone,
                    account.default_date_granularity,
                    int(account.enabled),
                    account.status,
                    account.created_at,
                    account.updated_at,
                    account.version,
                ),
            )
        return self.get_account(account.id)

    def list_accounts(self, workspace_id: str = "") -> list[WebsiteAnalyticsAccount]:
        sql = f"SELECT {ACCOUNT_COLUMNS} FROM website_analytics_accounts"
        params: list[Any] = []
        if workspace_id:
            sql += " WHERE workspace_id=?"
            params.append(workspace_id)
        sql += " ORDER BY id"
        with _connect(self.database_path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._account_from_row(row) for row in rows]

    def get_account(self, account_id: str) -> WebsiteAnalyticsAccount:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                f"SELECT {ACCOUNT_COLUMNS} FROM website_analytics_accounts WHERE id=?", (account_id,)
            ).fetchone()
        if not row:
            raise WebsiteAnalyticsError("website_analytics.account_not_found", "Analytics account was not found.")
        return self._account_from_row(row)

    def update_account_status(
        self, account_id: str, enabled: bool, *, expected_version: int
    ) -> WebsiteAnalyticsAccount:
        current = self.get_account(account_id)
        if current.version != expected_version:
            raise WebsiteAnalyticsError("website_analytics.conflict", "Analytics account version conflict.")
        with _connect(self.database_path) as connection:
            connection.execute(
                "UPDATE website_analytics_accounts SET enabled=?, status=?, version=version+1, updated_at=? WHERE id=?",
                (int(enabled), "enabled" if enabled else "disabled", utc_now_iso(), account_id),
            )
        return self.get_account(account_id)

    def put_mappings(
        self, account_id: str, workspace_id: str, mappings: list[WebsiteAnalyticsEventMapping]
    ) -> list[WebsiteAnalyticsEventMapping]:
        allowed = {"cta_click", "outbound_click", "signup", "contact", "download", "conversion", "custom"}
        with _connect(self.database_path) as connection:
            connection.execute("DELETE FROM website_analytics_event_mappings WHERE account_id=?", (account_id,))
            for mapping in mappings:
                if mapping.internal_event_type not in allowed:
                    raise WebsiteAnalyticsError("website_analytics.invalid_event_mapping", "Unsupported event mapping.")
                connection.execute(
                    "INSERT INTO website_analytics_event_mappings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        mapping.id,
                        workspace_id,
                        account_id,
                        mapping.provider_event_name,
                        _json(mapping.provider_property_filters),
                        mapping.internal_event_type,
                        mapping.cta_id,
                        mapping.conversion_type,
                        mapping.conversion_value_policy,
                        int(mapping.enabled),
                        mapping.version,
                    ),
                )
        return self.list_mappings(account_id)

    def list_mappings(self, account_id: str) -> list[WebsiteAnalyticsEventMapping]:
        with _connect(self.database_path) as connection:
            rows = connection.execute(
                f"SELECT {MAPPING_COLUMNS} FROM website_analytics_event_mappings WHERE account_id=? ORDER BY id",
                (account_id,),
            ).fetchall()
        return [self._mapping_from_row(row) for row in rows]

    def ensure_sync_state(
        self, account: WebsiteAnalyticsAccount, sync_type: str = "daily"
    ) -> WebsiteAnalyticsSyncState:
        state_id = f"sync-{stable_checksum(account.id + sync_type)[:12]}"
        now = utc_now_iso()
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO website_analytics_sync_states VALUES (?, ?, ?, ?, ?, 'scheduled', '', '', '', '', '', '', ?, 0, '', '', '', 1)",
                (state_id, account.workspace_id, account.id, account.site_identifier, sync_type, now),
            )
        return self.get_sync_state(state_id)

    def get_sync_state(self, state_id: str) -> WebsiteAnalyticsSyncState:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                f"SELECT {SYNC_COLUMNS} FROM website_analytics_sync_states WHERE id=?", (state_id,)
            ).fetchone()
        if not row:
            raise WebsiteAnalyticsError("website_analytics.sync_not_found", "Sync state was not found.")
        return self._sync_from_row(row)

    def list_sync_states(
        self, account_id: str = "", *, claimable: bool = False, limit: int = 100
    ) -> list[WebsiteAnalyticsSyncState]:
        sql = f"SELECT {SYNC_COLUMNS} FROM website_analytics_sync_states"
        clauses: list[str] = []
        params: list[Any] = []
        if account_id:
            clauses.append("account_id=?")
            params.append(account_id)
        if claimable:
            clauses.append("status IN ('scheduled', 'waiting', 'failed', 'rate_limited')")
            clauses.append("(lease_expires_at='' OR lease_expires_at<?)")
            params.append(utc_now_iso())
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY next_run_at LIMIT ?"
        params.append(limit)
        with _connect(self.database_path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._sync_from_row(row) for row in rows]

    def claim_sync_state(self, state_id: str, owner: str, lease_expires_at: str) -> bool:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT status, lease_expires_at FROM website_analytics_sync_states WHERE id=?", (state_id,)
            ).fetchone()
            if (
                not row
                or row["status"] not in {"scheduled", "waiting", "failed", "rate_limited"}
                or (row["lease_expires_at"] and row["lease_expires_at"] > utc_now_iso())
            ):
                return False
            updated = connection.execute(
                "UPDATE website_analytics_sync_states SET status='claimed', lease_owner=?, lease_expires_at=?, "
                "last_started_at=?, attempt_count=attempt_count+1, version=version+1 WHERE id=? "
                "AND status IN ('scheduled', 'waiting', 'failed', 'rate_limited') "
                "AND (lease_expires_at='' OR lease_expires_at<?)",
                (owner, lease_expires_at, utc_now_iso(), state_id, utc_now_iso()),
            ).rowcount
        return updated == 1

    def schedule_manual_sync(self, state_id: str) -> WebsiteAnalyticsSyncState:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT lease_expires_at FROM website_analytics_sync_states WHERE id=?", (state_id,)
            ).fetchone()
            if not row or (row["lease_expires_at"] and row["lease_expires_at"] > utc_now_iso()):
                raise WebsiteAnalyticsError("website_analytics.sync_busy", "Analytics sync is already claimed.")
            connection.execute(
                "UPDATE website_analytics_sync_states SET status='scheduled', next_run_at=?, version=version+1 WHERE id=?",
                (utc_now_iso(), state_id),
            )
        return self.get_sync_state(state_id)

    def heartbeat_sync_state(self, state_id: str, owner: str, lease_expires_at: str) -> bool:
        with _connect(self.database_path) as connection:
            updated = connection.execute(
                "UPDATE website_analytics_sync_states SET lease_expires_at=? WHERE id=? AND lease_owner=?",
                (lease_expires_at, state_id, owner),
            ).rowcount
        return updated == 1

    def complete_sync_state(
        self,
        state_id: str,
        owner: str,
        *,
        cursor: str,
        high_watermark: str,
        status: str = "completed",
        error_code: str = "",
    ) -> WebsiteAnalyticsSyncState:
        with _connect(self.database_path) as connection:
            updated = connection.execute(
                "UPDATE website_analytics_sync_states SET status=?, cursor=?, high_watermark=?, last_completed_at=?, "
                "last_successful_at=CASE WHEN ?='completed' THEN ? ELSE last_successful_at END, last_error_code=?, "
                "lease_owner='', lease_expires_at='', version=version+1 WHERE id=? AND lease_owner=?",
                (status, cursor, high_watermark, utc_now_iso(), status, utc_now_iso(), error_code, state_id, owner),
            ).rowcount
        if updated != 1:
            raise WebsiteAnalyticsError("website_analytics.sync_lease_lost", "Sync lease was not owned.")
        return self.get_sync_state(state_id)

    def record_rate_limit(self, state: ProviderRateLimitState) -> ProviderRateLimitState:
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO website_analytics_rate_limits VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    state.account_id,
                    state.limit,
                    state.remaining,
                    state.reset_at,
                    state.retry_after,
                    state.source,
                    state.observed_at,
                ),
            )
        return state

    def ingest_provider_observation(
        self,
        workspace_id: str,
        account_id: str,
        observation: ProviderMetricObservation,
        attribution: WebsiteAnalyticsAttribution,
    ) -> dict[str, Any]:
        observation_payload = asdict(observation)
        observation_payload.pop("collected_at", None)
        checksum = stable_checksum(observation_payload)
        with _connect(self.database_path) as connection:
            existing = connection.execute(
                "SELECT observation_id, observed_value, observation_checksum FROM website_analytics_attributions "
                "WHERE workspace_id=? AND account_id=? AND source_fingerprint=? AND metric_key=? "
                "ORDER BY created_at DESC, observation_id DESC LIMIT 1",
                (workspace_id, account_id, observation.source_fingerprint, observation.metric_key),
            ).fetchone()
            if existing and existing["observation_checksum"] == checksum:
                return {"status": "duplicate", "id": existing["observation_id"], "correction": False}
            correction_of = str(existing["observation_id"]) if existing else ""
            observation_id = f"web-obs-{stable_checksum(account_id + observation.source_fingerprint + checksum)[:12]}"
            connection.execute(
                "INSERT INTO website_analytics_attributions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    observation_id,
                    workspace_id,
                    account_id,
                    observation.source_fingerprint,
                    observation.metric_key,
                    observation.value,
                    checksum,
                    correction_of,
                    _json(asdict(attribution)),
                    utc_now_iso(),
                ),
            )
        self.owned_repository.ingest_observation(
            workspace_id,
            observation.metric_key,
            observation.value,
            attribution.content_item_id or observation.content_item_id,
            attribution.content_revision_id or observation.content_revision_id,
            attribution.website_target_id or observation.website_target_id,
            campaign_id=attribution.campaign_id or observation.campaign_id,
            source=observation.provider_id,
            idempotency_key="website-analytics-" + observation_id,
        )
        return {
            "status": "corrected" if correction_of else "ingested",
            "id": observation_id,
            "correction": bool(correction_of),
        }

    def save_quality_report(
        self, workspace_id: str, report: WebsiteAnalyticsDataQualityReport
    ) -> WebsiteAnalyticsDataQualityReport:
        report_id = f"quality-{stable_checksum(report.account_id + report.period + utc_now_iso())[:12]}"
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO website_analytics_quality_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report_id,
                    workspace_id,
                    report.account_id,
                    report.site_identifier,
                    report.period,
                    _json(asdict(report)),
                    report.status,
                    utc_now_iso(),
                ),
            )
        return report

    def latest_quality(self, account_id: str) -> WebsiteAnalyticsDataQualityReport | None:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT report_json FROM website_analytics_quality_reports WHERE account_id=? ORDER BY created_at DESC LIMIT 1",
                (account_id,),
            ).fetchone()
        return self._quality_from_json(row["report_json"]) if row else None

    def analytics_health(self) -> dict[str, Any]:
        accounts = self.list_accounts()
        syncs = self.list_sync_states(limit=1000)
        with _connect(self.database_path) as connection:
            attributions = connection.execute("SELECT attribution_json FROM website_analytics_attributions").fetchall()
            rate_limited = connection.execute(
                "SELECT account_id FROM website_analytics_rate_limits WHERE retry_after > 0"
            ).fetchall()
        conflicts = 0
        for row in attributions:
            payload = json.loads(row["attribution_json"])
            if payload.get("quality_status") == "conflicting":
                conflicts += 1
        enabled = [item for item in accounts if item.enabled]
        failed = [item for item in syncs if item.status in {"failed", "needs_attention"}]
        return {
            "framework_version": WEBSITE_ANALYTICS_PROVIDER_FRAMEWORK_VERSION,
            "enabled_analytics_accounts": len(enabled),
            "sync_worker_required": bool(enabled),
            "sync_queue_depth": len([item for item in syncs if item.status in {"scheduled", "waiting", "failed"}]),
            "oldest_pending_sync": syncs[0].next_run_at if syncs else "",
            "last_successful_sync": max(
                (item.last_successful_at for item in syncs if item.last_successful_at), default=""
            ),
            "failed_accounts": len(failed),
            "rate_limited_accounts": len(rate_limited),
            "stale_cursors": len([item for item in syncs if item.last_error_code == "cursor_incompatible"]),
            "partial_queries": len([item for item in syncs if item.last_error_code == "partial_result"]),
            "attribution_conflicts": conflicts,
            "data_freshness": "fresh" if enabled and not failed else ("not_configured" if not enabled else "degraded"),
            "provider_availability": "available" if not failed else "degraded",
        }

    def _account_from_row(self, row: sqlite3.Row) -> WebsiteAnalyticsAccount:
        return WebsiteAnalyticsAccount(
            id=row["id"],
            workspace_id=row["workspace_id"],
            provider_id=row["provider_id"],
            display_name=row["display_name"],
            origin_reference_id=row["origin_reference_id"],
            site_identifier=row["site_identifier"],
            secret_reference_id=row["secret_reference_id"],
            timezone=row["timezone"],
            default_date_granularity=row["default_date_granularity"],
            enabled=bool(row["enabled"]),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            version=int(row["version"]),
        )

    def _mapping_from_row(self, row: sqlite3.Row) -> WebsiteAnalyticsEventMapping:
        return WebsiteAnalyticsEventMapping(
            id=row["id"],
            workspace_id=row["workspace_id"],
            account_id=row["account_id"],
            provider_event_name=row["provider_event_name"],
            provider_property_filters=json.loads(row["provider_property_filters_json"]),
            internal_event_type=row["internal_event_type"],
            cta_id=row["cta_id"],
            conversion_type=row["conversion_type"],
            conversion_value_policy=row["conversion_value_policy"],
            enabled=bool(row["enabled"]),
            version=int(row["version"]),
        )

    def _sync_from_row(self, row: sqlite3.Row) -> WebsiteAnalyticsSyncState:
        return WebsiteAnalyticsSyncState(
            id=row["id"],
            workspace_id=row["workspace_id"],
            account_id=row["account_id"],
            site_identifier=row["site_identifier"],
            sync_type=row["sync_type"],
            status=row["status"],
            cursor=row["cursor"],
            high_watermark=row["high_watermark"],
            correction_window_start=row["correction_window_start"],
            last_started_at=row["last_started_at"],
            last_completed_at=row["last_completed_at"],
            last_successful_at=row["last_successful_at"],
            next_run_at=row["next_run_at"],
            attempt_count=int(row["attempt_count"]),
            last_error_code=row["last_error_code"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            version=int(row["version"]),
        )

    def _quality_from_json(self, raw: str) -> WebsiteAnalyticsDataQualityReport:
        payload = json.loads(raw)
        payload["missing_metrics"] = tuple(payload.get("missing_metrics", ()))
        payload["provider_warnings"] = tuple(payload.get("provider_warnings", ()))
        return WebsiteAnalyticsDataQualityReport(**payload)


__all__ = [
    "DatabaseWebsiteAnalyticsRepository",
    "WEBSITE_ANALYTICS_SCHEMA_VERSION",
    "migration_checksum",
]
