"""SQLite persistence for CI artifact imports."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.core.certification_evidence.models import utc_now_iso

from .errors import CiArtifactError
from .models import CiArtifactImportAttestation, CiArtifactImportRequest, CiImportAuditEvent

SCHEMA_VERSION = 1


class CiArtifactRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or Path("studio_data/owned_publication.sqlite")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ci_artifact_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_artifact_origins (
                    id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_artifact_import_requests (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    origin_reference_id TEXT NOT NULL,
                    workflow_run_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_artifact_download_records (
                    id TEXT PRIMARY KEY,
                    import_request_id TEXT NOT NULL,
                    downloaded_checksum TEXT NOT NULL,
                    provider_digest_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_artifact_import_attestations (
                    id TEXT PRIMARY KEY,
                    import_request_id TEXT NOT NULL,
                    evidence_package_id TEXT NOT NULL,
                    trust_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_artifact_import_leases (
                    import_request_id TEXT PRIMARY KEY,
                    lease_owner TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_artifact_retention_policies (
                    workspace_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_artifact_reconciliation_records (
                    id TEXT PRIMARY KEY,
                    import_request_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_artifact_audit_events (
                    id TEXT PRIMARY KEY,
                    import_request_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_evidence_operator_flows (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    expected_commit_sha TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_artifact_import_dry_runs (
                    id TEXT PRIMARY KEY,
                    flow_id TEXT NOT NULL,
                    expected_commit_sha TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    run_attempt INTEGER NOT NULL,
                    artifact_id TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_evidence_promotions (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    evidence_package_id TEXT NOT NULL,
                    import_attestation_id TEXT NOT NULL,
                    target_commit_sha TEXT NOT NULL,
                    trust_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ci_operator_audit_events (
                    id TEXT PRIMARY KEY,
                    flow_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO ci_artifact_schema_migrations VALUES (?, ?, datetime('now'))",
                (SCHEMA_VERSION, "phase29-ci-artifacts-v1"),
            )

    def save_origin(self, origin: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO ci_artifact_origins VALUES (?, ?, ?, ?)",
                (origin["id"], origin["provider_id"], _json(origin), origin.get("version", 1)),
            )
        return origin

    def list_origins(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM ci_artifact_origins ORDER BY id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def get_origin(self, origin_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM ci_artifact_origins WHERE id = ?", (origin_id,)
            ).fetchone()
        if row is None:
            raise CiArtifactError("ci.origin_not_found", "CI origin is not registered.")
        return json.loads(row["payload_json"])

    def save_request(self, request: CiArtifactImportRequest) -> dict[str, Any]:
        payload = asdict(request)
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM ci_artifact_import_requests WHERE id = ?", (request.id,)
            ).fetchone()
            if existing:
                return json.loads(existing["payload_json"])
            connection.execute(
                "INSERT INTO ci_artifact_import_requests VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    request.id,
                    request.workspace_id,
                    request.origin_reference_id,
                    request.workflow_run_id,
                    request.artifact_id,
                    request.status,
                    _json(payload),
                ),
            )
        return payload

    def update_request(self, request: dict[str, Any], status: str) -> dict[str, Any]:
        request = dict(request)
        request["status"] = status
        with self.connect() as connection:
            connection.execute(
                "UPDATE ci_artifact_import_requests SET status = ?, payload_json = ? WHERE id = ?",
                (status, _json(request), request["id"]),
            )
        return request

    def get_request(self, request_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM ci_artifact_import_requests WHERE id = ?", (request_id,)
            ).fetchone()
        if row is None:
            raise CiArtifactError("ci.import_not_found", "CI import request was not found.")
        return json.loads(row["payload_json"])

    def list_requests(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM ci_artifact_import_requests ORDER BY id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def claim_next(self, *, worker_id: str, lease_seconds: int = 60) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM ci_artifact_import_requests
                WHERE status IN ('prepared', 'validated', 'downloaded', 'uncertain')
                ORDER BY id LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            request = json.loads(row["payload_json"])
            request["lease_owner"] = worker_id
            request["lease_expires_at"] = utc_now_iso()
            request["status"] = "validated" if request["status"] == "prepared" else request["status"]
            connection.execute(
                "INSERT OR REPLACE INTO ci_artifact_import_leases VALUES (?, ?, datetime('now', ?))",
                (request["id"], worker_id, f"+{lease_seconds} seconds"),
            )
            connection.execute(
                "UPDATE ci_artifact_import_requests SET status = ?, payload_json = ? WHERE id = ?",
                (request["status"], _json(request), request["id"]),
            )
            return request

    def save_download_record(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO ci_artifact_download_records VALUES (?, ?, ?, ?, ?)",
                (
                    record["id"],
                    record["import_request_id"],
                    record["downloaded_checksum"],
                    record["provider_digest_status"],
                    _json(record),
                ),
            )
        return record

    def save_attestation(self, attestation: CiArtifactImportAttestation) -> dict[str, Any]:
        payload = asdict(attestation)
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM ci_artifact_import_attestations WHERE id = ?", (attestation.id,)
            ).fetchone()
            if existing:
                return json.loads(existing["payload_json"])
            connection.execute(
                "INSERT INTO ci_artifact_import_attestations VALUES (?, ?, ?, ?, ?)",
                (
                    attestation.id,
                    attestation.import_request_id,
                    attestation.evidence_package_id,
                    attestation.trust_status,
                    _json(payload),
                ),
            )
        return payload

    def attestations(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM ci_artifact_import_attestations ORDER BY id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def audit(self, event: CiImportAuditEvent) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO ci_artifact_audit_events VALUES (?, ?, ?, ?)",
                (event.id, event.import_request_id, event.action, _json(asdict(event))),
            )

    def save_operator_flow(self, flow: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM ci_evidence_operator_flows WHERE id = ?", (flow["id"],)
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE ci_evidence_operator_flows
                    SET status = ?, payload_json = ?, version = ?
                    WHERE id = ?
                    """,
                    (flow["status"], _json(flow), int(flow.get("version", 1)), flow["id"]),
                )
            else:
                connection.execute(
                    "INSERT INTO ci_evidence_operator_flows VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        flow["id"],
                        flow["workspace_id"],
                        flow["expected_commit_sha"],
                        flow["status"],
                        _json(flow),
                        int(flow.get("version", 1)),
                    ),
                )
        return flow

    def get_operator_flow(self, flow_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM ci_evidence_operator_flows WHERE id = ?", (flow_id,)
            ).fetchone()
        if row is None:
            raise CiArtifactError("ci.operator_flow_not_found", "CI evidence operator flow was not found.")
        return json.loads(row["payload_json"])

    def list_operator_flows(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM ci_evidence_operator_flows ORDER BY id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def save_dry_run(self, dry_run: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO ci_artifact_import_dry_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dry_run["id"],
                    dry_run["flow_id"],
                    dry_run["expected_commit_sha"],
                    dry_run["run_id"],
                    int(dry_run["run_attempt"]),
                    dry_run["artifact_id"],
                    dry_run["checksum"],
                    _json(dry_run),
                ),
            )
        return dry_run

    def get_dry_run(self, dry_run_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM ci_artifact_import_dry_runs WHERE id = ?", (dry_run_id,)
            ).fetchone()
        if row is None:
            raise CiArtifactError("ci.dry_run_not_found", "CI import dry-run was not found.")
        return json.loads(row["payload_json"])

    def dry_runs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM ci_artifact_import_dry_runs ORDER BY id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def save_promotion(self, promotion: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM ci_evidence_promotions WHERE id = ?", (promotion["id"],)
            ).fetchone()
            if existing:
                return json.loads(existing["payload_json"])
            connection.execute(
                "INSERT INTO ci_evidence_promotions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    promotion["id"],
                    promotion["workspace_id"],
                    promotion["evidence_package_id"],
                    promotion["import_attestation_id"],
                    promotion["target_commit_sha"],
                    promotion["trust_status"],
                    _json(promotion),
                ),
            )
        return promotion

    def promotions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM ci_evidence_promotions ORDER BY id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def operator_audit(self, event: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO ci_operator_audit_events VALUES (?, ?, ?, ?)",
                (event["id"], event["flow_id"], event["action"], _json(event)),
            )

    def operator_audit_events(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM ci_operator_audit_events ORDER BY id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = ["CiArtifactRepository"]
