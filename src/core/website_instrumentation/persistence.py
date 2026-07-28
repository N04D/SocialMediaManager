"""SQLite persistence for website instrumentation configs and evidence."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.core.owned_publication.persistence import default_database_path

from .errors import WebsiteInstrumentationError
from .models import WebsiteInstrumentationConfig, WebsiteInstrumentationManifest, stable_checksum, utc_now_iso

WEBSITE_INSTRUMENTATION_SCHEMA_VERSION = 1
WEBSITE_INSTRUMENTATION_MIGRATION_ID = "001_website_analytics_instrumentation"
WEBSITE_INSTRUMENTATION_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS website_instrumentation_schema_migrations (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_instrumentation_profiles (
    id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_instrumentation_configs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    website_account_id TEXT NOT NULL,
    analytics_account_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    consent_mode TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    cta_event_name TEXT NOT NULL,
    outbound_event_name TEXT NOT NULL,
    conversion_event_name TEXT NOT NULL,
    attribution_policy TEXT NOT NULL,
    script_delivery_mode TEXT NOT NULL,
    expected_script_origin_reference TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_instrumentation_manifests (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    config_id TEXT NOT NULL,
    checksum TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_instrumentation_verifications (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    config_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    level TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_instrumentation_quality_reports (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    config_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_instrumentation_mapping_drift (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    config_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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


class DatabaseWebsiteInstrumentationRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or default_database_path()
        self.migrate()

    def migrate(self) -> dict[str, Any]:
        checksum = stable_checksum(WEBSITE_INSTRUMENTATION_MIGRATION_SQL)
        with _connect(self.database_path) as connection:
            connection.executescript(WEBSITE_INSTRUMENTATION_MIGRATION_SQL)
            row = connection.execute(
                "SELECT checksum, status FROM website_instrumentation_schema_migrations WHERE id=?",
                (WEBSITE_INSTRUMENTATION_MIGRATION_ID,),
            ).fetchone()
            if row and (row["checksum"] != checksum or row["status"] != "applied"):
                raise WebsiteInstrumentationError("website_instrumentation.schema", "Instrumentation schema mismatch.")
            connection.execute(
                "INSERT OR REPLACE INTO website_instrumentation_schema_migrations VALUES (?, ?, ?, ?, 'applied')",
                (WEBSITE_INSTRUMENTATION_MIGRATION_ID, WEBSITE_INSTRUMENTATION_SCHEMA_VERSION, checksum, utc_now_iso()),
            )
        return {"schema_version": WEBSITE_INSTRUMENTATION_SCHEMA_VERSION, "checksum": checksum, "status": "current"}

    def save_profile(self, profile: dict[str, Any]) -> None:
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO website_instrumentation_profiles VALUES (?, ?, ?)",
                (profile["id"], _json(profile), profile["checksum"]),
            )

    def create_config(self, config: WebsiteInstrumentationConfig) -> WebsiteInstrumentationConfig:
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO website_instrumentation_configs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    config.id,
                    config.workspace_id,
                    config.website_account_id,
                    config.analytics_account_id,
                    config.profile_id,
                    config.consent_mode,
                    int(config.enabled),
                    config.cta_event_name,
                    config.outbound_event_name,
                    config.conversion_event_name,
                    config.attribution_policy,
                    config.script_delivery_mode,
                    config.expected_script_origin_reference,
                    config.version,
                    config.created_at,
                    config.updated_at,
                ),
            )
        return self.get_config(config.id)

    def list_configs(self) -> list[WebsiteInstrumentationConfig]:
        with _connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT id, workspace_id, website_account_id, analytics_account_id, profile_id, consent_mode, enabled, "
                "cta_event_name, outbound_event_name, conversion_event_name, attribution_policy, script_delivery_mode, "
                "expected_script_origin_reference, version, created_at, updated_at FROM website_instrumentation_configs ORDER BY id"
            ).fetchall()
        return [self._config_from_row(row) for row in rows]

    def get_config(self, config_id: str) -> WebsiteInstrumentationConfig:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT id, workspace_id, website_account_id, analytics_account_id, profile_id, consent_mode, enabled, "
                "cta_event_name, outbound_event_name, conversion_event_name, attribution_policy, script_delivery_mode, "
                "expected_script_origin_reference, version, created_at, updated_at FROM website_instrumentation_configs WHERE id=?",
                (config_id,),
            ).fetchone()
        if not row:
            raise WebsiteInstrumentationError("website_instrumentation.config_not_found", "Config not found.")
        return self._config_from_row(row)

    def update_config(
        self, config_id: str, patch: dict[str, Any], *, expected_version: int
    ) -> WebsiteInstrumentationConfig:
        current = self.get_config(config_id)
        if current.version != expected_version:
            raise WebsiteInstrumentationError("website_instrumentation.conflict", "Config version conflict.")
        allowed = {"consent_mode", "enabled", "profile_id"}
        values = {key: value for key, value in patch.items() if key in allowed}
        if not values:
            return current
        assignments = ", ".join(f"{key}=?" for key in values)
        with _connect(self.database_path) as connection:
            connection.execute(
                f"UPDATE website_instrumentation_configs SET {assignments}, version=version+1, updated_at=? WHERE id=?",
                (*values.values(), utc_now_iso(), config_id),
            )
        return self.get_config(config_id)

    def save_manifest(self, config_id: str, manifest: WebsiteInstrumentationManifest) -> WebsiteInstrumentationManifest:
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO website_instrumentation_manifests VALUES (?, ?, ?, ?, ?, ?)",
                (
                    manifest.id,
                    manifest.workspace_id,
                    config_id,
                    manifest.checksum,
                    _json(asdict(manifest)),
                    manifest.created_at,
                ),
            )
        return manifest

    def get_manifest(self, manifest_id: str) -> dict[str, Any]:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM website_instrumentation_manifests WHERE id=?", (manifest_id,)
            ).fetchone()
        if not row:
            raise WebsiteInstrumentationError("website_instrumentation.manifest_not_found", "Manifest not found.")
        return json.loads(row["payload_json"])

    def save_record(
        self, table: str, workspace_id: str, config_id: str, manifest_id: str, status: str, payload: dict[str, Any]
    ) -> None:
        allowed = {
            "website_instrumentation_verifications",
            "website_instrumentation_quality_reports",
            "website_instrumentation_mapping_drift",
        }
        if table not in allowed:
            raise WebsiteInstrumentationError("website_instrumentation.table", "Unsupported derived record.")
        record_id = "instr-" + stable_checksum({"table": table, "payload": payload, "time": utc_now_iso()})[:16]
        if table == "website_instrumentation_verifications":
            columns = "(id, workspace_id, config_id, manifest_id, level, status, payload_json, created_at)"
            values = (
                record_id,
                workspace_id,
                config_id,
                manifest_id,
                payload.get("level", ""),
                status,
                _json(payload),
                utc_now_iso(),
            )
        elif table == "website_instrumentation_mapping_drift":
            columns = "(id, workspace_id, config_id, status, payload_json, created_at)"
            values = (record_id, workspace_id, config_id, status, _json(payload), utc_now_iso())
        else:
            columns = "(id, workspace_id, config_id, manifest_id, status, payload_json, created_at)"
            values = (record_id, workspace_id, config_id, manifest_id, status, _json(payload), utc_now_iso())
        with _connect(self.database_path) as connection:
            connection.execute(f"INSERT INTO {table} {columns} VALUES ({', '.join('?' for _ in values)})", values)

    def health(self) -> dict[str, Any]:
        with _connect(self.database_path) as connection:
            configs = connection.execute("SELECT count(*) AS count FROM website_instrumentation_configs").fetchone()[
                "count"
            ]
            quality = connection.execute(
                "SELECT status FROM website_instrumentation_quality_reports ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            drift = connection.execute(
                "SELECT status FROM website_instrumentation_mapping_drift ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return {
            "configured_websites": int(configs),
            "fully_instrumented_websites": 1 if quality and quality["status"] == "complete" else 0,
            "partial_websites": 1 if quality and quality["status"] in {"partial", "not_observed"} else 0,
            "mapping_drift": 1 if drift and drift["status"] == "drift" else 0,
            "instrumentation_ready": not drift or drift["status"] != "drift",
            "quality": quality["status"] if quality else "not_configured",
        }

    def _config_from_row(self, row: sqlite3.Row) -> WebsiteInstrumentationConfig:
        return WebsiteInstrumentationConfig(
            id=row["id"],
            workspace_id=row["workspace_id"],
            website_account_id=row["website_account_id"],
            analytics_account_id=row["analytics_account_id"],
            profile_id=row["profile_id"],
            consent_mode=row["consent_mode"],
            enabled=bool(row["enabled"]),
            cta_event_name=row["cta_event_name"],
            outbound_event_name=row["outbound_event_name"],
            conversion_event_name=row["conversion_event_name"],
            attribution_policy=row["attribution_policy"],
            script_delivery_mode=row["script_delivery_mode"],
            expected_script_origin_reference=row["expected_script_origin_reference"],
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


__all__ = [
    "DatabaseWebsiteInstrumentationRepository",
    "WEBSITE_INSTRUMENTATION_SCHEMA_VERSION",
    "WEBSITE_INSTRUMENTATION_MIGRATION_SQL",
]
