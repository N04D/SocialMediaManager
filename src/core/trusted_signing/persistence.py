"""SQLite persistence for trusted signer records."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import SignerApproval, SignerAuditEvent, SignerHealthReport, SignerRotationRecord, TrustedSignerReference

SCHEMA_VERSION = 1


class TrustedSignerRepository:
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
                CREATE TABLE IF NOT EXISTS trusted_signer_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trusted_signer_references (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    public_key_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trusted_signer_approvals (
                    id TEXT PRIMARY KEY,
                    signer_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trusted_signer_health_checks (
                    id TEXT PRIMARY KEY,
                    signer_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trusted_signer_rotations (
                    id TEXT PRIMARY KEY,
                    old_signer_id TEXT NOT NULL,
                    new_signer_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trusted_signer_audit_events (
                    id TEXT PRIMARY KEY,
                    signer_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO trusted_signer_schema_migrations VALUES (?, ?, datetime('now'))",
                (SCHEMA_VERSION, "phase29-trusted-signers-v1"),
            )

    def save_signer(self, signer: TrustedSignerReference) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO trusted_signer_references(id, status, public_key_fingerprint, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (signer.id, signer.status, signer.public_key_fingerprint, _json(asdict(signer))),
            )
        return asdict(signer)

    def get_signer(self, signer_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM trusted_signer_references WHERE id = ?", (signer_id,)
            ).fetchone()
        if row is None:
            raise KeyError(signer_id)
        return json.loads(row["payload_json"])

    def list_signers(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM trusted_signer_references ORDER BY id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def save_approval(self, approval: SignerApproval) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO trusted_signer_approvals VALUES (?, ?, ?, ?, ?)",
                (approval.id, approval.signer_id, approval.reviewer_id, approval.decision, _json(asdict(approval))),
            )
        return asdict(approval)

    def approvals(self, signer_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM trusted_signer_approvals WHERE signer_id = ? ORDER BY id", (signer_id,)
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def save_health(self, report: SignerHealthReport) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO trusted_signer_health_checks VALUES (?, ?, ?, ?)",
                (f"{report.signer_id}:{report.checked_at}", report.signer_id, report.status, _json(asdict(report))),
            )
        return asdict(report)

    def save_rotation(self, record: SignerRotationRecord) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO trusted_signer_rotations VALUES (?, ?, ?, ?)",
                (record.id, record.old_signer_id, record.new_signer_id, _json(asdict(record))),
            )
        return asdict(record)

    def audit(self, event: SignerAuditEvent) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO trusted_signer_audit_events VALUES (?, ?, ?, ?)",
                (event.id, event.signer_id, event.action, _json(asdict(event))),
            )


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = ["TrustedSignerRepository"]
