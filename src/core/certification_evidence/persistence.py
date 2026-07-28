"""SQLite persistence for certification evidence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .errors import CertificationEvidenceError
from .models import (
    CertificationEvidenceComparison,
    CertificationEvidenceReview,
    CertificationImportRecord,
    CertificationRevocation,
)

SCHEMA_VERSION = 1


class DatabaseCertificationEvidenceRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or Path("studio_data/owned_publication.sqlite")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS certification_evidence_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS certification_evidence_packages (
                    package_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    package_checksum TEXT NOT NULL,
                    trust_status TEXT NOT NULL,
                    freshness_status TEXT NOT NULL,
                    signature_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS certification_artifacts (
                    package_id TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (package_id, artifact_path)
                );
                CREATE TABLE IF NOT EXISTS certification_provenance (
                    package_id TEXT PRIMARY KEY,
                    commit_sha TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    repository_identity TEXT NOT NULL,
                    workflow_identity TEXT NOT NULL,
                    required_skips INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS certification_signers (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS certification_trust_policies (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS certification_freshness_policies (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS certification_import_records (
                    package_id TEXT PRIMARY KEY,
                    package_checksum TEXT NOT NULL,
                    signer_reference_id TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    import_source TEXT NOT NULL,
                    trust_status TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS certification_reviews (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    evidence_checksum TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS certification_revocations (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS certification_comparisons (
                    id TEXT PRIMARY KEY,
                    left_evidence_id TEXT NOT NULL,
                    right_evidence_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO certification_evidence_schema_migrations(version, checksum, applied_at) VALUES (?, ?, datetime('now'))",
                (SCHEMA_VERSION, "phase28-certification-evidence-v1"),
            )

    def save_package(
        self,
        *,
        package: dict[str, Any],
        artifacts: dict[str, Any],
        provenance: dict[str, Any],
        trust_status: str,
        freshness_status: str,
        signature_status: str,
    ) -> dict[str, Any]:
        package_id = package["package_id"]
        checksum = package["package_checksum"]
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT package_checksum FROM certification_evidence_packages WHERE package_id = ?", (package_id,)
            ).fetchone()
            if existing and existing["package_checksum"] != checksum:
                raise CertificationEvidenceError(
                    "certification.replay_conflict", "Package ID was replayed with another checksum."
                )
            connection.execute(
                """
                INSERT OR REPLACE INTO certification_evidence_packages
                (package_id, workspace_id, evidence_type, package_checksum, trust_status, freshness_status, signature_status, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package_id,
                    package["workspace_id"],
                    package["evidence_type"],
                    checksum,
                    trust_status,
                    freshness_status,
                    signature_status,
                    _json(package),
                    package["generated_at"],
                ),
            )
            for path, payload in artifacts.items():
                manifest = next((item for item in package["artifact_manifest"] if item["artifact_path"] == path), None)
                if manifest is None:
                    continue
                connection.execute(
                    """
                    INSERT OR REPLACE INTO certification_artifacts
                    (package_id, artifact_path, artifact_type, checksum, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (package_id, path, manifest["artifact_type"], manifest["checksum"], payload.decode("utf-8")),
                )
            connection.execute(
                """
                INSERT OR REPLACE INTO certification_provenance
                (package_id, commit_sha, source_type, repository_identity, workflow_identity, required_skips, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package_id,
                    provenance["commit_sha"],
                    provenance["source_type"],
                    provenance["repository_identity"],
                    provenance["test_suite_id"],
                    provenance["required_skips"],
                    _json(provenance),
                ),
            )
        return self.get_package(package_id)

    def get_package(self, package_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json, trust_status, freshness_status, signature_status FROM certification_evidence_packages WHERE package_id = ?",
                (package_id,),
            ).fetchone()
        if row is None:
            raise CertificationEvidenceError("certification.not_found", "Evidence package was not found.")
        payload = json.loads(row["payload_json"])
        payload["trust_status"] = row["trust_status"]
        payload["freshness_status"] = row["freshness_status"]
        payload["signature_status"] = row["signature_status"]
        return payload

    def list_packages(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT package_id FROM certification_evidence_packages ORDER BY created_at, package_id"
            ).fetchall()
        return [self.get_package(row["package_id"]) for row in rows]

    def save_import_record(self, record: CertificationImportRecord) -> None:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT package_checksum FROM certification_import_records WHERE package_id = ?", (record.package_id,)
            ).fetchone()
            if existing and existing["package_checksum"] != record.package_checksum:
                raise CertificationEvidenceError("certification.replay_conflict", "Package replay checksum mismatch.")
            connection.execute(
                """
                INSERT OR IGNORE INTO certification_import_records
                (package_id, package_checksum, signer_reference_id, imported_at, import_source, trust_status, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.package_id,
                    record.package_checksum,
                    record.signer_reference_id,
                    record.imported_at,
                    record.import_source,
                    record.trust_status,
                    record.first_seen_at,
                ),
            )

    def save_review(self, review: CertificationEvidenceReview) -> dict[str, Any]:
        package = self.get_package(review.evidence_id)
        if package["trust_status"] == "invalid" and review.decision == "approved":
            raise CertificationEvidenceError(
                "certification.invalid_review", "Review cannot make invalid evidence valid."
            )
        if review.evidence_checksum != package["package_checksum"]:
            raise CertificationEvidenceError("certification.review_checksum", "Review evidence checksum mismatch.")
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO certification_reviews(id, workspace_id, evidence_id, evidence_checksum, payload_json) VALUES (?, ?, ?, ?, ?)",
                (review.id, review.workspace_id, review.evidence_id, review.evidence_checksum, _json(asdict(review))),
            )
        return asdict(review)

    def list_reviews(self, evidence_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM certification_reviews WHERE evidence_id = ? ORDER BY id", (evidence_id,)
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def save_revocation(self, revocation: CertificationRevocation) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO certification_revocations(id, workspace_id, target_type, target_id, payload_json) VALUES (?, ?, ?, ?, ?)",
                (
                    revocation.id,
                    revocation.workspace_id,
                    revocation.target_type,
                    revocation.target_id,
                    _json(asdict(revocation)),
                ),
            )
            if revocation.target_type == "evidence_package":
                connection.execute(
                    "UPDATE certification_evidence_packages SET trust_status = 'revoked' WHERE package_id = ?",
                    (revocation.target_id,),
                )
        return asdict(revocation)

    def save_comparison(self, comparison: CertificationEvidenceComparison) -> dict[str, Any]:
        comparison_id = f"cmp-{comparison.left_evidence_id}-{comparison.right_evidence_id}"[:120]
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO certification_comparisons(id, left_evidence_id, right_evidence_id, payload_json) VALUES (?, ?, ?, ?)",
                (comparison_id, comparison.left_evidence_id, comparison.right_evidence_id, _json(asdict(comparison))),
            )
        return asdict(comparison)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


__all__ = ["DatabaseCertificationEvidenceRepository", "SCHEMA_VERSION"]
