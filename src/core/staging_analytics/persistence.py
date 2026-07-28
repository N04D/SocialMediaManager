"""SQLite persistence for staging analytics certification."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.core.owned_publication.persistence import default_database_path

from .errors import StagingAnalyticsError
from .models import (
    ProviderObservedReconciliationResult,
    StagingAnalyticsCertificationProfile,
    StagingAnalyticsCertificationReport,
    StagingAnalyticsCertificationRun,
    StagingBrowserRequestEvidence,
    stable_checksum,
    utc_now_iso,
)

STAGING_ANALYTICS_SCHEMA_VERSION = 1
STAGING_ANALYTICS_MIGRATION_ID = "001_staging_analytics_certification"
STAGING_ANALYTICS_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS staging_analytics_schema_migrations (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staging_analytics_profiles (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    version INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staging_analytics_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staging_browser_evidence (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_name TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staging_provider_reconciliations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staging_certification_reports (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
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


class DatabaseStagingAnalyticsRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or default_database_path()
        self.migrate()

    def migrate(self) -> dict[str, Any]:
        checksum = stable_checksum(STAGING_ANALYTICS_MIGRATION_SQL)
        with _connect(self.database_path) as connection:
            connection.executescript(STAGING_ANALYTICS_MIGRATION_SQL)
            row = connection.execute(
                "SELECT checksum, status FROM staging_analytics_schema_migrations WHERE id=?",
                (STAGING_ANALYTICS_MIGRATION_ID,),
            ).fetchone()
            if row and (row["checksum"] != checksum or row["status"] != "applied"):
                raise StagingAnalyticsError("staging_analytics.schema", "Staging analytics schema mismatch.")
            connection.execute(
                "INSERT OR REPLACE INTO staging_analytics_schema_migrations VALUES (?, ?, ?, ?, 'applied')",
                (STAGING_ANALYTICS_MIGRATION_ID, STAGING_ANALYTICS_SCHEMA_VERSION, checksum, utc_now_iso()),
            )
        return {"schema_version": STAGING_ANALYTICS_SCHEMA_VERSION, "checksum": checksum, "status": "current"}

    def save_profile(self, profile: StagingAnalyticsCertificationProfile) -> StagingAnalyticsCertificationProfile:
        payload = asdict(profile)
        checksum = stable_checksum(payload)
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO staging_analytics_profiles VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    profile.id,
                    profile.workspace_id,
                    _json(payload),
                    profile.version,
                    checksum,
                    profile.created_at,
                    profile.updated_at,
                ),
            )
        return self.get_profile(profile.id)

    def list_profiles(self) -> list[StagingAnalyticsCertificationProfile]:
        with _connect(self.database_path) as connection:
            rows = connection.execute("SELECT payload_json FROM staging_analytics_profiles ORDER BY id").fetchall()
        return [StagingAnalyticsCertificationProfile(**json.loads(row["payload_json"])) for row in rows]

    def get_profile(self, profile_id: str) -> StagingAnalyticsCertificationProfile:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM staging_analytics_profiles WHERE id=?", (profile_id,)
            ).fetchone()
        if not row:
            raise StagingAnalyticsError("staging_analytics.profile_not_found", "Staging profile was not found.")
        return StagingAnalyticsCertificationProfile(**json.loads(row["payload_json"]))

    def save_run(self, run: StagingAnalyticsCertificationRun) -> StagingAnalyticsCertificationRun:
        payload = asdict(run)
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO staging_analytics_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    run.workspace_id,
                    run.profile_id,
                    run.run_id,
                    run.status,
                    _json(payload),
                    run.checksum,
                    run.started_at,
                ),
            )
        return self.get_run(run.id)

    def list_runs(self) -> list[StagingAnalyticsCertificationRun]:
        with _connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM staging_analytics_runs ORDER BY created_at DESC"
            ).fetchall()
        return [StagingAnalyticsCertificationRun(**json.loads(row["payload_json"])) for row in rows]

    def get_run(self, run_or_id: str) -> StagingAnalyticsCertificationRun:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM staging_analytics_runs WHERE id=? OR run_id=?", (run_or_id, run_or_id)
            ).fetchone()
        if not row:
            raise StagingAnalyticsError("staging_analytics.run_not_found", "Staging run was not found.")
        return StagingAnalyticsCertificationRun(**json.loads(row["payload_json"]))

    def save_browser_evidence(
        self, workspace_id: str, evidence: StagingBrowserRequestEvidence
    ) -> StagingBrowserRequestEvidence:
        payload = asdict(evidence)
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO staging_browser_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence.id,
                    workspace_id,
                    evidence.run_id,
                    evidence.event_type,
                    evidence.event_name,
                    _json(payload),
                    evidence.checksum,
                    evidence.occurred_at,
                ),
            )
        return evidence

    def list_browser_evidence(self, run_id: str) -> list[StagingBrowserRequestEvidence]:
        with _connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM staging_browser_evidence WHERE run_id=? ORDER BY created_at", (run_id,)
            ).fetchall()
        return [StagingBrowserRequestEvidence(**json.loads(row["payload_json"])) for row in rows]

    def save_reconciliation(
        self, workspace_id: str, result: ProviderObservedReconciliationResult
    ) -> ProviderObservedReconciliationResult:
        payload = asdict(result)
        checksum = stable_checksum(payload)
        record_id = "stg-recon-" + checksum[:16]
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO staging_provider_reconciliations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record_id,
                    workspace_id,
                    result.run_id,
                    result.quality_status,
                    _json(payload),
                    checksum,
                    result.reconciled_at,
                ),
            )
        return result

    def latest_reconciliation(self, run_id: str) -> dict[str, Any] | None:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM staging_provider_reconciliations WHERE run_id=? ORDER BY created_at DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def save_report(
        self, workspace_id: str, report: StagingAnalyticsCertificationReport
    ) -> StagingAnalyticsCertificationReport:
        payload = asdict(report)
        with _connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO staging_certification_reports VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "stg-report-" + report.checksum[:16],
                    workspace_id,
                    report.run_id,
                    "passed" if report.certification_passed else report.provider_observed_status,
                    _json(payload),
                    report.checksum,
                    report.completed_at,
                ),
            )
        return report

    def latest_report(self, run_id: str) -> dict[str, Any] | None:
        with _connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM staging_certification_reports WHERE run_id=? ORDER BY created_at DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def health(self) -> dict[str, Any]:
        with _connect(self.database_path) as connection:
            profiles = connection.execute("SELECT count(*) AS count FROM staging_analytics_profiles").fetchone()[
                "count"
            ]
            runs = connection.execute(
                "SELECT status, count(*) AS count FROM staging_analytics_runs GROUP BY status"
            ).fetchall()
            reports = connection.execute(
                "SELECT status FROM staging_certification_reports ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        counts = {row["status"]: int(row["count"]) for row in runs}
        return {
            "enabled_staging_profiles": int(profiles),
            "open_runs": sum(
                count
                for status, count in counts.items()
                if status not in {"provider_observed", "timed_out", "failed", "cancelled"}
            ),
            "awaiting_provider": counts.get("awaiting_provider", 0),
            "partial_observed": counts.get("provider_partially_observed", 0),
            "timed_out": counts.get("timed_out", 0),
            "uncertain_browser_events": counts.get("browser_mutation_uncertain", 0),
            "latest_status": reports["status"] if reports else "staging_provider_certification_not_run",
            "staging_certification_ready": bool(reports and reports["status"] == "passed"),
        }


__all__ = ["DatabaseStagingAnalyticsRepository", "STAGING_ANALYTICS_SCHEMA_VERSION"]
