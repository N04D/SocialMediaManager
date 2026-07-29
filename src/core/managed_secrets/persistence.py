"""SQLite metadata persistence for managed secrets.

Secret material is intentionally not stored here; encrypted payloads live in the selected backend.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import (
    ManagedSecretApproval,
    ManagedSecretAuditEvent,
    ManagedSecretHealthReport,
    ManagedSecretReference,
    ManagedSecretVersion,
    OperatorRoleBinding,
)

SCHEMA_VERSION = 1


class ManagedSecretRepository:
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
                CREATE TABLE IF NOT EXISTS managed_secret_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_secret_references (
                    id TEXT PRIMARY KEY,
                    backend_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_secret_versions (
                    id TEXT PRIMARY KEY,
                    secret_reference_id TEXT NOT NULL,
                    secret_version INTEGER NOT NULL,
                    backend_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_secret_approvals (
                    id TEXT PRIMARY KEY,
                    secret_reference_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    approver_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_secret_consumers (
                    id TEXT PRIMARY KEY,
                    secret_reference_id TEXT NOT NULL,
                    consumer TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_secret_health_checks (
                    id TEXT PRIMARY KEY,
                    secret_reference_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_secret_rotation_records (
                    id TEXT PRIMARY KEY,
                    secret_reference_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_secret_revocations (
                    id TEXT PRIMARY KEY,
                    secret_reference_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_secret_audit_events (
                    id TEXT PRIMARY KEY,
                    resource_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operator_role_bindings (
                    operator_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    workspace_id_or_host_scope TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(operator_id, role, workspace_id_or_host_scope)
                );
                CREATE TABLE IF NOT EXISTS operator_approval_policies (
                    action_type TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO managed_secret_schema_migrations VALUES (?, ?, datetime('now'))",
                (SCHEMA_VERSION, "phase30-managed-secrets-v1"),
            )

    def save_reference(self, reference: ManagedSecretReference) -> dict[str, Any]:
        payload = asdict(reference)
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO managed_secret_references VALUES (?, ?, ?, ?, ?)",
                (reference.id, reference.backend_id, reference.status, _json(payload), reference.version),
            )
        return payload

    def get_reference(self, reference_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM managed_secret_references WHERE id = ?", (reference_id,)
            ).fetchone()
        if row is None:
            raise KeyError(reference_id)
        return json.loads(row["payload_json"])

    def list_references(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM managed_secret_references ORDER BY id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def save_version(self, version: ManagedSecretVersion) -> dict[str, Any]:
        payload = asdict(version)
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO managed_secret_versions VALUES (?, ?, ?, ?, ?)",
                (
                    version.id,
                    version.secret_reference_id,
                    version.secret_version,
                    version.backend_id,
                    _json(payload),
                ),
            )
        return payload

    def list_versions(self, reference_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM managed_secret_versions WHERE secret_reference_id = ? ORDER BY secret_version",
                (reference_id,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def save_approval(self, approval: ManagedSecretApproval) -> dict[str, Any]:
        payload = asdict(approval)
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO managed_secret_approvals VALUES (?, ?, ?, ?, ?)",
                (
                    approval.id,
                    approval.secret_reference_id,
                    approval.action_type,
                    approval.approver_id,
                    _json(payload),
                ),
            )
        return payload

    def approvals(self, reference_id: str, action_type: str = "") -> list[dict[str, Any]]:
        query = "SELECT payload_json FROM managed_secret_approvals WHERE secret_reference_id = ?"
        params: tuple[Any, ...] = (reference_id,)
        if action_type:
            query += " AND action_type = ?"
            params = (reference_id, action_type)
        query += " ORDER BY id"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def bind_role(self, binding: OperatorRoleBinding) -> dict[str, Any]:
        payload = asdict(binding)
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO operator_role_bindings VALUES (?, ?, ?, ?)",
                (binding.operator_id, binding.role, binding.workspace_id_or_host_scope, _json(payload)),
            )
        return payload

    def roles(self, operator_id: str) -> tuple[str, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT role FROM operator_role_bindings WHERE operator_id = ? ORDER BY role",
                (operator_id,),
            ).fetchall()
        return tuple(row["role"] for row in rows)

    def save_health(self, health: ManagedSecretHealthReport) -> dict[str, Any]:
        payload = asdict(health)
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO managed_secret_health_checks VALUES (?, ?, ?, ?)",
                (
                    f"{health.secret_reference_id}:{health.checked_at}",
                    health.secret_reference_id,
                    health.status,
                    _json(payload),
                ),
            )
        return payload

    def audit(self, event: ManagedSecretAuditEvent) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO managed_secret_audit_events VALUES (?, ?, ?, ?)",
                (event.id, event.resource_id, event.action, _json(asdict(event))),
            )

    def audit_events(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload_json FROM managed_secret_audit_events ORDER BY id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = ["ManagedSecretRepository", "SCHEMA_VERSION"]
