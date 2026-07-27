"""SQLite persistence for owned-publication operations.

The repository is intentionally small and boring: domain services call typed
methods, this module owns SQL, and all records are workspace-scoped.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import mkstemp
from typing import Any

from .contracts import (
    CAMPAIGN_WORKSPACE_CONTRACT_VERSION,
    FUNNEL_READMODEL_CONTRACT_VERSION,
    OWNED_PUBLICATION_MIGRATION_CONTRACT_VERSION,
    OWNED_PUBLICATION_PERSISTENCE_VERSION,
    OWNED_PUBLICATION_STORAGE_CONTRACT_VERSION,
    PUBLICATION_EVIDENCE_STORAGE_CONTRACT_VERSION,
    RECONCILIATION_LEASE_CONTRACT_VERSION,
)
from .errors import OwnedPublicationError
from .models import (
    ChannelVariantDraft,
    ContentDraft,
    ContentRevision,
    ExecutionTimelineEvent,
    PublicationEvidenceSummary,
    PublicationPlan,
    PublicationTarget,
    ReconciliationItem,
    stable_checksum,
    utc_now_iso,
)

SCHEMA_VERSION = 1
MIGRATION_ID = "001_owned_publication_persistence"
MIGRATION_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS owned_publication_schema_migrations (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS owned_publication_idempotency (
    workspace_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload_checksum TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, operation, idempotency_key)
);
CREATE TABLE IF NOT EXISTS owned_publication_drafts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    content_item_id TEXT NOT NULL UNIQUE,
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    markdown_body TEXT NOT NULL,
    language TEXT NOT NULL,
    author TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    hero_media_asset_id TEXT NOT NULL DEFAULT '',
    website_fields_json TEXT NOT NULL DEFAULT '{}',
    social_fields_json TEXT NOT NULL DEFAULT '{}',
    seo_json TEXT NOT NULL DEFAULT '{}',
    cta_json TEXT NOT NULL DEFAULT '{}',
    last_saved_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS owned_publication_revisions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    content_item_id TEXT NOT NULL,
    source_draft_id TEXT NOT NULL,
    source_draft_version INTEGER NOT NULL,
    revision_number INTEGER NOT NULL,
    content_payload_json TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    UNIQUE (workspace_id, idempotency_key),
    UNIQUE (workspace_id, content_item_id, revision_number)
);
CREATE TABLE IF NOT EXISTS owned_publication_variants (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    content_item_id TEXT NOT NULL,
    content_revision_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_checksum TEXT NOT NULL,
    generation_metadata_json TEXT NOT NULL,
    supersedes_variant_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    UNIQUE (workspace_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS owned_publication_snapshots (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    publication_plan_id TEXT NOT NULL,
    content_item_id TEXT NOT NULL,
    content_revision_id TEXT NOT NULL,
    variant_bindings_json TEXT NOT NULL,
    media_bindings_json TEXT NOT NULL,
    profile_bindings_json TEXT NOT NULL,
    target_bindings_json TEXT NOT NULL,
    snapshot_checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    UNIQUE (workspace_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS publication_plans (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    content_item_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    UNIQUE (workspace_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS publication_targets (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    schedule_id TEXT NOT NULL,
    verification_policy TEXT NOT NULL,
    status TEXT NOT NULL,
    execution_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, plan_id, channel_id, account_id)
);
CREATE TABLE IF NOT EXISTS publication_target_dependencies (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    predecessor_target_id TEXT NOT NULL,
    dependent_target_id TEXT NOT NULL,
    required_state TEXT NOT NULL,
    dependency_type TEXT NOT NULL,
    timeout_policy TEXT NOT NULL,
    failure_policy TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, predecessor_target_id, dependent_target_id)
);
CREATE TABLE IF NOT EXISTS publication_schedules (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    timezone TEXT NOT NULL,
    planned_for TEXT NOT NULL,
    recurrence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publication_occurrences (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    schedule_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    planned_for TEXT NOT NULL,
    timezone TEXT NOT NULL,
    status TEXT NOT NULL,
    dependency_status TEXT NOT NULL,
    claim_after TEXT NOT NULL,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS publication_execution_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    publication_attempt_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    phase TEXT NOT NULL,
    mutation_state TEXT NOT NULL,
    safe_summary TEXT NOT NULL,
    evidence_reference_ids_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    UNIQUE (workspace_id, publication_attempt_id, sequence_number),
    UNIQUE (workspace_id, publication_attempt_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS publication_evidence (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    content_revision_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_checksum TEXT NOT NULL,
    previous_evidence_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    UNIQUE (workspace_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS reconciliation_items (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    category TEXT NOT NULL,
    publication_plan_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    mutation_state TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    safe_summary_json TEXT NOT NULL,
    evidence_reference_ids_json TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    next_check_at TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT NOT NULL DEFAULT '',
    resolution TEXT NOT NULL DEFAULT '',
    resolved_at TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT NOT NULL,
    UNIQUE (workspace_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS reconciliation_attempts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    reconciliation_item_id TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    safe_summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconciliation_leases (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    reconciliation_item_id TEXT NOT NULL UNIQUE,
    owner TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS integrity_findings (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    safe_summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS integrity_repairs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    repair_type TEXT NOT NULL,
    status TEXT NOT NULL,
    safe_summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    timezone TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    default_utm_campaign TEXT NOT NULL,
    goals_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_content_items (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    content_item_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, campaign_id, content_item_id)
);
CREATE TABLE IF NOT EXISTS funnel_observations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    content_item_id TEXT NOT NULL,
    content_revision_id TEXT NOT NULL,
    publication_target_id TEXT NOT NULL,
    publication_attempt_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    dimensions_json TEXT NOT NULL,
    correction_of TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL,
    UNIQUE (workspace_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS funnel_attributions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    source_publication_target_id TEXT NOT NULL,
    website_publication_target_id TEXT NOT NULL,
    content_revision_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    attribution_id TEXT NOT NULL,
    quality TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS funnel_readmodels (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    readmodel_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_watermark TEXT NOT NULL,
    build_version TEXT NOT NULL,
    built_at TEXT NOT NULL,
    completeness TEXT NOT NULL,
    stale INTEGER NOT NULL,
    errors_json TEXT NOT NULL,
    current INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_audit_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    safe_summary_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    UNIQUE (workspace_id, idempotency_key)
);
"""


def default_database_path() -> Path:
    return Path.home() / ".local" / "share" / "socialmediamanager" / "owned-publication.sqlite3"


def migration_checksum() -> str:
    return stable_checksum(MIGRATION_SQL)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_json(value: str) -> Any:
    if not value:
        return {}
    return json.loads(value)


def _payload_checksum(payload: Any) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


MIGRATION_COLUMNS = "id, version, checksum, applied_at, status"
DRAFT_COLUMNS = (
    "id, workspace_id, content_item_id, version, title, summary, markdown_body, language, author, tags_json, "
    "hero_media_asset_id, website_fields_json, social_fields_json, seo_json, cta_json, last_saved_at, created_at, "
    "updated_at, checksum"
)
REVISION_COLUMNS = (
    "id, workspace_id, content_item_id, source_draft_id, source_draft_version, revision_number, "
    "content_payload_json, content_checksum, created_by, created_at, idempotency_key"
)
VARIANT_COLUMNS = (
    "id, workspace_id, content_item_id, content_revision_id, channel_id, version, payload_json, payload_checksum, "
    "generation_metadata_json, supersedes_variant_id, created_at, idempotency_key"
)
PLAN_COLUMNS = (
    "id, workspace_id, campaign_id, version, status, content_item_id, snapshot_id, created_by, created_at, "
    "updated_at, idempotency_key"
)
TARGET_COLUMNS = (
    "id, workspace_id, plan_id, channel_id, account_id, variant_id, schedule_id, verification_policy, status, "
    "execution_state, created_at, updated_at"
)
DEPENDENCY_COLUMNS = (
    "id, workspace_id, plan_id, predecessor_target_id, dependent_target_id, required_state, dependency_type, "
    "timeout_policy, failure_policy, created_at"
)
EVENT_COLUMNS = (
    "id, workspace_id, publication_attempt_id, target_id, event_type, phase, mutation_state, safe_summary, "
    "evidence_reference_ids_json, occurred_at, sequence_number, idempotency_key"
)
EVIDENCE_COLUMNS = (
    "id, workspace_id, evidence_type, publication_id, target_id, channel_id, content_revision_id, payload_json, "
    "payload_checksum, previous_evidence_id, created_at, idempotency_key"
)
RECONCILIATION_COLUMNS = (
    "id, workspace_id, category, publication_plan_id, target_id, attempt_id, mutation_state, severity, status, "
    "safe_summary_json, evidence_reference_ids_json, detected_at, next_check_at, attempt_count, max_attempts, "
    "lease_owner, lease_expires_at, resolution, resolved_at, version, idempotency_key"
)
CAMPAIGN_COLUMNS = (
    "id, workspace_id, name, description, status, timezone, start_at, end_at, default_utm_campaign, goals_json, "
    "created_at, updated_at, version"
)


@dataclass(frozen=True)
class StorageHealth:
    status: str
    database: str
    schema_version: int
    pending_migrations: tuple[str, ...]
    wal_enabled: bool
    foreign_keys: bool
    production_source: str


@dataclass(frozen=True)
class ReconciliationLease:
    item_id: str
    owner: str
    expires_at: str
    status: str


@dataclass(frozen=True)
class CampaignRecord:
    id: str
    workspace_id: str
    name: str
    description: str
    status: str
    timezone: str
    start_at: str
    end_at: str
    default_utm_campaign: str
    goals: dict[str, Any]
    version: int


class DatabaseOwnedPublicationRepository:
    """SQLite repository for durable owned-publication operations."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path) if database_path else default_database_path()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def _connect(self) -> Iterable[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterable[sqlite3.Connection]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def migrate(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path, timeout=30, isolation_level=None) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='owned_publication_schema_migrations'"
            ).fetchone()
            checksum = migration_checksum()
            if row:
                existing = connection.execute(
                    "SELECT checksum, status FROM owned_publication_schema_migrations WHERE id=?", (MIGRATION_ID,)
                ).fetchone()
                if existing and existing[1] == "started":
                    raise OwnedPublicationError("storage.interrupted_migration", "Interrupted migration detected.")
                if existing and existing[0] != checksum:
                    raise OwnedPublicationError("storage.migration_checksum", "Migration checksum mismatch.")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS owned_publication_schema_migrations "
                "(id TEXT PRIMARY KEY, version INTEGER NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL, status TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO owned_publication_schema_migrations VALUES (?, ?, ?, ?, ?)",
                (MIGRATION_ID, SCHEMA_VERSION, checksum, utc_now_iso(), "started"),
            )
            connection.executescript(MIGRATION_SQL)
            connection.execute(
                "UPDATE owned_publication_schema_migrations SET status='applied', applied_at=?, checksum=? WHERE id=?",
                (utc_now_iso(), checksum, MIGRATION_ID),
            )

    def health(self) -> StorageHealth:
        with self._connect() as connection:
            migrations = connection.execute("SELECT version FROM owned_publication_schema_migrations").fetchall()
            wal = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
            fk = int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        return StorageHealth(
            "ready",
            "host-owned sqlite",
            max([int(row[0]) for row in migrations] or [0]),
            (),
            wal,
            fk,
            "database-backed",
        )

    def migrations(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {MIGRATION_COLUMNS} FROM owned_publication_schema_migrations ORDER BY version"
            ).fetchall()
        return {
            "contract_version": OWNED_PUBLICATION_MIGRATION_CONTRACT_VERSION,
            "migrations": [dict(row) for row in rows],
            "checksum": migration_checksum(),
        }

    def save_draft(
        self,
        draft: ContentDraft,
        *,
        expected_version: int | None,
        idempotency_key: str,
        actor: str = "system",
    ) -> ContentDraft:
        idempotency_payload = {
            "id": draft.id,
            "workspace_id": draft.workspace_id,
            "title": draft.title,
            "summary": draft.summary,
            "markdown_body": draft.markdown_body,
            "language": draft.language,
            "author": draft.author,
            "tags": list(draft.tags),
            "status": draft.status,
            "expected_version": expected_version,
        }
        result = self._idempotent(
            draft.workspace_id,
            "draft.save",
            idempotency_key,
            idempotency_payload,
            lambda connection: self._save_draft_tx(connection, draft, expected_version, actor),
        )
        return self.get_draft(str(result["id"]))

    def _save_draft_tx(
        self, connection: sqlite3.Connection, draft: ContentDraft, expected_version: int | None, actor: str
    ) -> dict[str, Any]:
        row = connection.execute("SELECT version FROM owned_publication_drafts WHERE id=?", (draft.id,)).fetchone()
        now = utc_now_iso()
        if row:
            if expected_version is None or int(row["version"]) != expected_version:
                raise OwnedPublicationError("workspace.conflict", "Draft version conflict.")
            version = expected_version + 1
            connection.execute(
                """
                UPDATE owned_publication_drafts
                   SET version=?, title=?, summary=?, markdown_body=?, language=?, author=?, tags_json=?,
                       last_saved_at=?, updated_at=?, checksum=?
                 WHERE id=?
                """,
                (
                    version,
                    draft.title,
                    draft.summary,
                    draft.markdown_body,
                    draft.language,
                    draft.author,
                    _json(list(draft.tags)),
                    now,
                    now,
                    draft.checksum,
                    draft.id,
                ),
            )
        else:
            version = draft.version
            connection.execute(
                """
                INSERT INTO owned_publication_drafts (
                    id, workspace_id, content_item_id, version, title, summary, markdown_body, language,
                    author, tags_json, last_saved_at, created_at, updated_at, checksum
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.id,
                    draft.workspace_id,
                    draft.id,
                    version,
                    draft.title,
                    draft.summary,
                    draft.markdown_body,
                    draft.language,
                    draft.author,
                    _json(list(draft.tags)),
                    draft.updated_at or now,
                    now,
                    now,
                    draft.checksum,
                ),
            )
        self._audit_tx(connection, draft.workspace_id, "draft updated", actor, draft.id, {"version": version})
        return {"id": draft.id, "version": version}

    def get_draft(self, draft_id: str) -> ContentDraft:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {DRAFT_COLUMNS} FROM owned_publication_drafts WHERE id=?", (draft_id,)
            ).fetchone()
        if not row:
            raise OwnedPublicationError("workspace.not_found", "Draft not found.")
        return self._draft_from_row(row)

    def list_drafts(self, workspace_id: str = "") -> list[ContentDraft]:
        sql = f"SELECT {DRAFT_COLUMNS} FROM owned_publication_drafts"
        params: tuple[Any, ...] = ()
        if workspace_id:
            sql += " WHERE workspace_id=?"
            params = (workspace_id,)
        sql += " ORDER BY updated_at DESC"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._draft_from_row(row) for row in rows]

    def create_revision(
        self, draft_id: str, *, expected_version: int, idempotency_key: str, actor: str = "system"
    ) -> ContentRevision:
        draft = self.get_draft(draft_id)
        payload = {"draft_id": draft_id, "expected_version": expected_version, "draft_checksum": draft.checksum}
        result = self._idempotent(
            draft.workspace_id,
            "revision.create",
            idempotency_key,
            payload,
            lambda connection: self._create_revision_tx(connection, draft, expected_version, idempotency_key, actor),
        )
        return self.get_revision(str(result["id"]))

    def _create_revision_tx(
        self,
        connection: sqlite3.Connection,
        draft: ContentDraft,
        expected_version: int,
        idempotency_key: str,
        actor: str,
    ) -> dict[str, Any]:
        if draft.version != expected_version:
            raise OwnedPublicationError("workspace.conflict", "Revision source version conflict.")
        number = int(
            connection.execute(
                "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM owned_publication_revisions WHERE content_item_id=?",
                (draft.id,),
            ).fetchone()[0]
        )
        revision_id = f"{draft.id}-rev-{number}"
        payload = {
            "title": draft.title,
            "summary": draft.summary,
            "markdown_body": draft.markdown_body,
            "tags": list(draft.tags),
            "language": draft.language,
            "author": draft.author,
        }
        checksum = stable_checksum(_json(payload))
        now = utc_now_iso()
        connection.execute(
            """
            INSERT INTO owned_publication_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                draft.workspace_id,
                draft.id,
                draft.id,
                draft.version,
                number,
                _json(payload),
                checksum,
                actor,
                now,
                idempotency_key,
            ),
        )
        self._audit_tx(connection, draft.workspace_id, "revision created", actor, revision_id, {"checksum": checksum})
        return {"id": revision_id}

    def get_revision(self, revision_id: str) -> ContentRevision:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {REVISION_COLUMNS} FROM owned_publication_revisions WHERE id=?", (revision_id,)
            ).fetchone()
        if not row:
            raise OwnedPublicationError("workspace.not_found", "Revision not found.")
        payload = _load_json(row["content_payload_json"])
        checksum = stable_checksum(_json(payload))
        if checksum != row["content_checksum"]:
            raise OwnedPublicationError("storage.checksum_mismatch", "Revision checksum mismatch.")
        return ContentRevision(
            row["id"],
            row["content_item_id"],
            row["workspace_id"],
            str(payload["title"]),
            str(payload["summary"]),
            str(payload["markdown_body"]),
            tuple(payload.get("tags") or ()),
            str(payload["language"]),
            str(payload["author"]),
            int(row["source_draft_version"]),
            row["content_checksum"],
            row["created_at"],
        )

    def list_revisions(self, content_item_id: str) -> list[ContentRevision]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM owned_publication_revisions WHERE content_item_id=? ORDER BY revision_number",
                (content_item_id,),
            ).fetchall()
        return [self.get_revision(str(row["id"])) for row in rows]

    def create_variant(
        self,
        revision: ContentRevision,
        channel_id: str,
        text: str,
        *,
        idempotency_key: str,
        generation_metadata: dict[str, Any] | None = None,
        supersedes_variant_id: str = "",
    ) -> ChannelVariantDraft:
        payload = {
            "revision": revision.id,
            "channel_id": channel_id,
            "text": text,
            "generation_metadata": generation_metadata or {},
            "supersedes_variant_id": supersedes_variant_id,
        }
        result = self._idempotent(
            revision.workspace_id,
            "variant.create",
            idempotency_key,
            payload,
            lambda connection: self._create_variant_tx(
                connection,
                revision,
                channel_id,
                text,
                idempotency_key,
                generation_metadata or {},
                supersedes_variant_id,
            ),
        )
        return self.get_variant(str(result["id"]))

    def _create_variant_tx(
        self,
        connection: sqlite3.Connection,
        revision: ContentRevision,
        channel_id: str,
        text: str,
        idempotency_key: str,
        generation_metadata: dict[str, Any],
        supersedes_variant_id: str,
    ) -> dict[str, Any]:
        version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM owned_publication_variants "
                "WHERE content_revision_id=? AND channel_id=?",
                (revision.id, channel_id),
            ).fetchone()[0]
        )
        variant_id = f"{revision.id}-{channel_id.replace('.', '-')}-v{version}"
        payload = {"text": text, "accepted": True, "generated": bool(generation_metadata)}
        checksum = _payload_checksum(payload)
        connection.execute(
            """
            INSERT INTO owned_publication_variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                variant_id,
                revision.workspace_id,
                revision.content_item_id,
                revision.id,
                channel_id,
                version,
                _json(payload),
                checksum,
                _json(generation_metadata),
                supersedes_variant_id,
                utc_now_iso(),
                idempotency_key,
            ),
        )
        return {"id": variant_id}

    def get_variant(self, variant_id: str) -> ChannelVariantDraft:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {VARIANT_COLUMNS} FROM owned_publication_variants WHERE id=?", (variant_id,)
            ).fetchone()
        if not row:
            raise OwnedPublicationError("workspace.not_found", "Variant not found.")
        payload = _load_json(row["payload_json"])
        return ChannelVariantDraft(
            row["id"],
            row["content_item_id"],
            row["content_revision_id"],
            row["channel_id"],
            str(payload["text"]),
            row["payload_checksum"],
            bool(payload.get("accepted")),
            bool(payload.get("generated")),
            _load_json(row["generation_metadata_json"]),
            {"version": str(row["version"]), "supersedes_variant_id": row["supersedes_variant_id"]},
        )

    def list_variants(self, content_item_id: str) -> list[ChannelVariantDraft]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM owned_publication_variants WHERE content_item_id=? ORDER BY created_at",
                (content_item_id,),
            ).fetchall()
        return [self.get_variant(str(row["id"])) for row in rows]

    def create_snapshot(
        self,
        workspace_id: str,
        plan_id: str,
        content_item_id: str,
        content_revision_id: str,
        variant_bindings: dict[str, str],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "plan_id": plan_id,
            "content_item_id": content_item_id,
            "content_revision_id": content_revision_id,
            "variant_bindings": variant_bindings,
        }
        return self._idempotent(
            workspace_id,
            "snapshot.create",
            idempotency_key,
            payload,
            lambda connection: self._create_snapshot_tx(
                connection,
                workspace_id,
                plan_id,
                content_item_id,
                content_revision_id,
                variant_bindings,
                idempotency_key,
            ),
        )

    def _create_snapshot_tx(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        plan_id: str,
        content_item_id: str,
        content_revision_id: str,
        variant_bindings: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        snapshot_id = f"snapshot-{stable_checksum(plan_id + content_revision_id)[:12]}"
        checksum = _payload_checksum({"content_revision_id": content_revision_id, "variant_bindings": variant_bindings})
        connection.execute(
            "INSERT INTO owned_publication_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot_id,
                workspace_id,
                plan_id,
                content_item_id,
                content_revision_id,
                _json(variant_bindings),
                "{}",
                "{}",
                "{}",
                checksum,
                utc_now_iso(),
                idempotency_key,
            ),
        )
        return {"id": snapshot_id, "snapshot_checksum": checksum}

    def create_plan(
        self,
        workspace_id: str,
        content_item_id: str,
        content_revision_id: str,
        targets: list[dict[str, str]],
        dependencies: list[dict[str, str]],
        *,
        campaign_id: str = "",
        idempotency_key: str,
        actor: str = "system",
    ) -> PublicationPlan:
        payload = {
            "content_item_id": content_item_id,
            "content_revision_id": content_revision_id,
            "targets": targets,
            "dependencies": dependencies,
            "campaign_id": campaign_id,
        }
        result = self._idempotent(
            workspace_id,
            "plan.create",
            idempotency_key,
            payload,
            lambda connection: self._create_plan_tx(
                connection,
                workspace_id,
                content_item_id,
                content_revision_id,
                targets,
                dependencies,
                campaign_id,
                actor,
            ),
        )
        return self.get_plan(str(result["id"]))

    def _create_plan_tx(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        content_item_id: str,
        content_revision_id: str,
        targets: list[dict[str, str]],
        dependencies: list[dict[str, str]],
        campaign_id: str,
        actor: str,
    ) -> dict[str, Any]:
        self._assert_acyclic(dependencies)
        plan_id = f"plan-{stable_checksum(content_item_id + content_revision_id + utc_now_iso())[:12]}"
        snapshot_id = f"snapshot-{stable_checksum(plan_id + content_revision_id)[:12]}"
        now = utc_now_iso()
        connection.execute(
            "INSERT INTO owned_publication_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot_id,
                workspace_id,
                plan_id,
                content_item_id,
                content_revision_id,
                _json({target["channel_id"]: target["variant_id"] for target in targets}),
                "{}",
                "{}",
                "{}",
                _payload_checksum(targets),
                now,
                "snapshot-" + plan_id,
            ),
        )
        connection.execute(
            "INSERT INTO publication_plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (plan_id, workspace_id, campaign_id, 1, "draft", content_item_id, snapshot_id, actor, now, now, plan_id),
        )
        for target in targets:
            connection.execute(
                "INSERT INTO publication_targets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    target["id"],
                    workspace_id,
                    plan_id,
                    target["channel_id"],
                    target["account_id"],
                    target["variant_id"],
                    target.get("schedule_id", ""),
                    target.get("verification_policy", ""),
                    target.get("status", "draft"),
                    target.get("execution_state", "not_started"),
                    now,
                    now,
                ),
            )
        for dependency in dependencies:
            if dependency["predecessor_target_id"] == dependency["dependent_target_id"]:
                raise OwnedPublicationError("dependency.self", "Self-dependency is not allowed.")
            connection.execute(
                "INSERT INTO publication_target_dependencies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dependency["id"],
                    workspace_id,
                    plan_id,
                    dependency["predecessor_target_id"],
                    dependency["dependent_target_id"],
                    dependency["required_state"],
                    dependency.get("dependency_type", "publication_state"),
                    dependency.get("timeout_policy", "wait"),
                    dependency.get("failure_policy", "block"),
                    now,
                ),
            )
        self._audit_tx(connection, workspace_id, "plan created", actor, plan_id, {"target_count": len(targets)})
        return {"id": plan_id}

    def get_plan(self, plan_id: str) -> PublicationPlan:
        with self._connect() as connection:
            plan = connection.execute(f"SELECT {PLAN_COLUMNS} FROM publication_plans WHERE id=?", (plan_id,)).fetchone()
            if not plan:
                raise OwnedPublicationError("workspace.not_found", "Publication plan not found.")
            targets = connection.execute(
                f"SELECT {TARGET_COLUMNS} FROM publication_targets WHERE plan_id=? ORDER BY created_at", (plan_id,)
            ).fetchall()
            dependencies = connection.execute(
                f"SELECT {DEPENDENCY_COLUMNS} FROM publication_target_dependencies WHERE plan_id=? ORDER BY created_at",
                (plan_id,),
            ).fetchall()
        return PublicationPlan(
            plan["id"],
            plan["workspace_id"],
            plan["content_item_id"],
            self._snapshot_revision(str(plan["snapshot_id"])),
            plan["campaign_id"],
            tuple(
                PublicationTarget(
                    row["id"],
                    row["channel_id"],
                    row["account_id"],
                    row["variant_id"],
                    row["schedule_id"],
                    row["status"],
                    row["verification_policy"],
                    row["execution_state"],
                )
                for row in targets
            ),
            tuple(dict(row) for row in dependencies),
            int(plan["version"]),
            plan["created_at"],
        )

    def _snapshot_revision(self, snapshot_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_revision_id FROM owned_publication_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
        return str(row["content_revision_id"]) if row else ""

    def materialize_occurrence(
        self,
        workspace_id: str,
        schedule_id: str,
        target_id: str,
        planned_for: str,
        *,
        timezone: str = "UTC",
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {"schedule_id": schedule_id, "target_id": target_id, "planned_for": planned_for}
        return self._idempotent(
            workspace_id,
            "occurrence.materialize",
            idempotency_key,
            payload,
            lambda connection: self._materialize_occurrence_tx(
                connection, workspace_id, schedule_id, target_id, planned_for, timezone, idempotency_key
            ),
        )

    def _materialize_occurrence_tx(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        schedule_id: str,
        target_id: str,
        planned_for: str,
        timezone: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        occurrence_id = f"occ-{stable_checksum(idempotency_key)[:12]}"
        now = utc_now_iso()
        connection.execute(
            "INSERT OR IGNORE INTO publication_schedules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (schedule_id, workspace_id, target_id, "once", timezone, planned_for, "{}", now, now),
        )
        connection.execute(
            "INSERT INTO publication_occurrences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                occurrence_id,
                workspace_id,
                schedule_id,
                target_id,
                planned_for,
                timezone,
                "waiting_dependency",
                "pending",
                now,
                "",
                "",
                0,
                idempotency_key,
                now,
                now,
            ),
        )
        return {"id": occurrence_id}

    def claim_occurrence(self, occurrence_id: str, owner: str, lease_expires_at: str) -> bool:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status, lease_expires_at FROM publication_occurrences WHERE id=?", (occurrence_id,)
            ).fetchone()
            if not row:
                return False
            if row["lease_expires_at"] and row["lease_expires_at"] > utc_now_iso():
                return False
            updated = connection.execute(
                "UPDATE publication_occurrences SET status='claimed', lease_owner=?, lease_expires_at=?, attempt_count=attempt_count+1, updated_at=? WHERE id=?",
                (owner, lease_expires_at, utc_now_iso(), occurrence_id),
            ).rowcount
        return updated == 1

    def list_occurrence_ids(self, *, limit: int = 10) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM publication_occurrences "
                "WHERE status IN ('waiting_dependency', 'open', 'claimed') "
                "ORDER BY planned_for, created_at LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def append_execution_event(
        self,
        workspace_id: str,
        attempt_id: str,
        target_id: str,
        event: ExecutionTimelineEvent,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = asdict(event) | {"attempt_id": attempt_id, "target_id": target_id}
        return self._idempotent(
            workspace_id,
            "execution.event",
            idempotency_key,
            payload,
            lambda connection: self._append_execution_event_tx(
                connection, workspace_id, attempt_id, target_id, event, idempotency_key
            ),
        )

    def _append_execution_event_tx(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        attempt_id: str,
        target_id: str,
        event: ExecutionTimelineEvent,
        idempotency_key: str,
    ) -> dict[str, Any]:
        sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM publication_execution_events WHERE publication_attempt_id=?",
                (attempt_id,),
            ).fetchone()[0]
        )
        event_id = f"event-{stable_checksum(attempt_id + idempotency_key)[:12]}"
        connection.execute(
            "INSERT INTO publication_execution_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                workspace_id,
                attempt_id,
                target_id,
                event.phase,
                event.phase,
                event.mutation_state,
                event.safe_evidence_summary,
                "[]",
                event.timestamp,
                sequence,
                idempotency_key,
            ),
        )
        return {"id": event_id, "sequence_number": sequence}

    def list_timeline(self, attempt_or_target_id: str) -> list[ExecutionTimelineEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {EVENT_COLUMNS} FROM publication_execution_events "
                "WHERE publication_attempt_id=? OR target_id=? ORDER BY sequence_number",
                (attempt_or_target_id, attempt_or_target_id),
            ).fetchall()
        return [
            ExecutionTimelineEvent(
                row["occurred_at"],
                row["phase"],
                "PublicationExecutionService",
                row["mutation_state"],
                "completed",
                row["safe_summary"],
            )
            for row in rows
        ]

    def add_evidence(
        self,
        workspace_id: str,
        evidence_type: str,
        evidence: PublicationEvidenceSummary,
        *,
        idempotency_key: str,
        previous_evidence_id: str = "",
    ) -> PublicationEvidenceSummary:
        payload = asdict(evidence)
        result = self._idempotent(
            workspace_id,
            "evidence.create",
            idempotency_key,
            {"type": evidence_type, "payload": payload},
            lambda connection: self._add_evidence_tx(
                connection, workspace_id, evidence_type, evidence, idempotency_key, previous_evidence_id
            ),
        )
        return self.get_evidence(str(result["id"]))

    def _add_evidence_tx(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        evidence_type: str,
        evidence: PublicationEvidenceSummary,
        idempotency_key: str,
        previous_evidence_id: str,
    ) -> dict[str, Any]:
        payload = _redact(asdict(evidence))
        checksum = _payload_checksum(payload)
        evidence_id = f"evidence-{stable_checksum(idempotency_key)[:12]}"
        connection.execute(
            "INSERT INTO publication_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evidence_id,
                workspace_id,
                evidence_type,
                evidence.publication_id,
                evidence.target_id,
                evidence.channel,
                evidence.content_revision_id,
                _json(payload),
                checksum,
                previous_evidence_id,
                utc_now_iso(),
                idempotency_key,
            ),
        )
        return {"id": evidence_id}

    def get_evidence(self, evidence_id: str) -> PublicationEvidenceSummary:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {EVIDENCE_COLUMNS} FROM publication_evidence WHERE id=?", (evidence_id,)
            ).fetchone()
        if not row:
            raise OwnedPublicationError("workspace.not_found", "Evidence not found.")
        payload = _load_json(row["payload_json"])
        return PublicationEvidenceSummary(**payload)

    def list_evidence(self, publication_or_target_id: str) -> list[PublicationEvidenceSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM publication_evidence WHERE publication_id=? OR target_id=? ORDER BY created_at",
                (publication_or_target_id, publication_or_target_id),
            ).fetchall()
        return [self.get_evidence(str(row["id"])) for row in rows]

    def detect_reconciliation(
        self,
        item: ReconciliationItem,
        *,
        plan_id: str = "",
        attempt_id: str = "",
        idempotency_key: str,
    ) -> ReconciliationItem:
        payload = asdict(item) | {"plan_id": plan_id, "attempt_id": attempt_id}
        result = self._idempotent(
            item.workspace_id,
            "reconciliation.detect",
            idempotency_key,
            payload,
            lambda connection: self._detect_reconciliation_tx(connection, item, plan_id, attempt_id, idempotency_key),
        )
        return self.get_reconciliation_item(str(result["id"]))

    def _detect_reconciliation_tx(
        self,
        connection: sqlite3.Connection,
        item: ReconciliationItem,
        plan_id: str,
        attempt_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        connection.execute(
            "INSERT INTO reconciliation_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.id,
                item.workspace_id,
                item.category,
                plan_id,
                item.target_id,
                attempt_id,
                item.mutation_state,
                item.severity,
                "open",
                _json(_redact(item.safe_evidence)),
                "[]",
                item.detected_at,
                item.detected_at,
                0,
                5,
                "",
                "",
                "",
                "",
                1,
                idempotency_key,
            ),
        )
        return {"id": item.id}

    def list_reconciliation(self, workspace_id: str = "") -> list[ReconciliationItem]:
        sql = f"SELECT {RECONCILIATION_COLUMNS} FROM reconciliation_items"
        params: tuple[Any, ...] = ()
        if workspace_id:
            sql += " WHERE workspace_id=?"
            params = (workspace_id,)
        sql += " ORDER BY detected_at"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._reconciliation_from_row(row) for row in rows]

    def list_reconciliation_ids(self, *, limit: int = 10) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM reconciliation_items WHERE status IN ('open', 'waiting', 'claimed') "
                "ORDER BY next_check_at, detected_at LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def get_reconciliation_item(self, item_id: str) -> ReconciliationItem:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {RECONCILIATION_COLUMNS} FROM reconciliation_items WHERE id=?", (item_id,)
            ).fetchone()
        if not row:
            raise OwnedPublicationError("workspace.not_found", "Reconciliation item not found.")
        return self._reconciliation_from_row(row)

    def claim_reconciliation(self, item_id: str, owner: str, lease_expires_at: str) -> ReconciliationLease:
        now = utc_now_iso()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT workspace_id, status, lease_expires_at FROM reconciliation_items WHERE id=?", (item_id,)
            ).fetchone()
            if not row:
                raise OwnedPublicationError("workspace.not_found", "Reconciliation item not found.")
            if row["lease_expires_at"] and row["lease_expires_at"] > now:
                return ReconciliationLease(item_id, owner, row["lease_expires_at"], "busy")
            connection.execute(
                "UPDATE reconciliation_items SET status='claimed', lease_owner=?, lease_expires_at=?, version=version+1 WHERE id=?",
                (owner, lease_expires_at, item_id),
            )
            connection.execute(
                "INSERT OR REPLACE INTO reconciliation_leases VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"lease-{item_id}", row["workspace_id"], item_id, owner, lease_expires_at, now, now),
            )
        return ReconciliationLease(item_id, owner, lease_expires_at, "claimed")

    def heartbeat_reconciliation(self, item_id: str, owner: str, lease_expires_at: str) -> bool:
        with self.transaction() as connection:
            updated = connection.execute(
                "UPDATE reconciliation_items SET lease_expires_at=? WHERE id=? AND lease_owner=?",
                (lease_expires_at, item_id, owner),
            ).rowcount
            if updated:
                connection.execute(
                    "UPDATE reconciliation_leases SET expires_at=?, heartbeat_at=? WHERE reconciliation_item_id=? AND owner=?",
                    (lease_expires_at, utc_now_iso(), item_id, owner),
                )
        return updated == 1

    def release_reconciliation(self, item_id: str, owner: str) -> bool:
        with self.transaction() as connection:
            updated = connection.execute(
                "UPDATE reconciliation_items SET status='open', lease_owner='', lease_expires_at='' WHERE id=? AND lease_owner=?",
                (item_id, owner),
            ).rowcount
            connection.execute(
                "DELETE FROM reconciliation_leases WHERE reconciliation_item_id=? AND owner=?", (item_id, owner)
            )
        return updated == 1

    def resolve_reconciliation(
        self, item_id: str, owner: str, *, expected_version: int, resolution: str, read_only: bool = True
    ) -> dict[str, Any]:
        if not read_only:
            raise OwnedPublicationError(
                "reconciliation.mutating_repair_blocked", "Mutating repair requires explicit execution flow."
            )
        with self.transaction() as connection:
            row = connection.execute(
                f"SELECT {RECONCILIATION_COLUMNS} FROM reconciliation_items WHERE id=?", (item_id,)
            ).fetchone()
            if not row or row["lease_owner"] != owner or int(row["version"]) != expected_version:
                raise OwnedPublicationError("workspace.conflict", "Reconciliation version or owner conflict.")
            connection.execute(
                "UPDATE reconciliation_items SET status='resolved', resolution=?, resolved_at=?, version=version+1 WHERE id=?",
                (resolution, utc_now_iso(), item_id),
            )
            connection.execute(
                "INSERT INTO reconciliation_attempts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"rec-attempt-{stable_checksum(item_id + resolution)[:12]}",
                    row["workspace_id"],
                    item_id,
                    "read_only_check",
                    "resolved",
                    _json({"resolution": resolution, "new_mutation": False}),
                    utc_now_iso(),
                ),
            )
        return {"id": item_id, "status": "resolved", "new_mutation": False}

    def resolve_claimed_reconciliation(self, item_id: str, owner: str, resolution: str) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute(
                f"SELECT {RECONCILIATION_COLUMNS} FROM reconciliation_items WHERE id=?", (item_id,)
            ).fetchone()
            if not row or row["lease_owner"] != owner:
                raise OwnedPublicationError("workspace.conflict", "Reconciliation owner conflict.")
            connection.execute(
                "UPDATE reconciliation_items SET status='resolved', resolution=?, resolved_at=?, version=version+1 "
                "WHERE id=?",
                (resolution, utc_now_iso(), item_id),
            )
            connection.execute(
                "INSERT OR IGNORE INTO reconciliation_attempts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"rec-attempt-{stable_checksum(item_id + owner + resolution)[:12]}",
                    row["workspace_id"],
                    item_id,
                    "read_only_check",
                    "resolved",
                    _json({"resolution": resolution, "new_mutation": False}),
                    utc_now_iso(),
                ),
            )
        return {"id": item_id, "status": "resolved", "new_mutation": False}

    def create_campaign(
        self,
        workspace_id: str,
        name: str,
        *,
        campaign_id: str = "",
        timezone: str = "UTC",
        start_at: str = "",
        end_at: str = "",
    ) -> CampaignRecord:
        now = utc_now_iso()
        campaign_id = campaign_id or f"campaign-{stable_checksum(workspace_id + name)[:12]}"
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    campaign_id,
                    workspace_id,
                    name,
                    "",
                    "draft",
                    timezone,
                    start_at,
                    end_at,
                    name.lower().replace(" ", "-"),
                    "{}",
                    now,
                    now,
                    1,
                ),
            )
            self._audit_tx(connection, workspace_id, "campaign created", "system", campaign_id, {"name": name})
        return self.get_campaign(campaign_id)

    def get_campaign(self, campaign_id: str) -> CampaignRecord:
        with self._connect() as connection:
            row = connection.execute(f"SELECT {CAMPAIGN_COLUMNS} FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not row:
            raise OwnedPublicationError("workspace.not_found", "Campaign not found.")
        return CampaignRecord(
            row["id"],
            row["workspace_id"],
            row["name"],
            row["description"],
            row["status"],
            row["timezone"],
            row["start_at"],
            row["end_at"],
            row["default_utm_campaign"],
            _load_json(row["goals_json"]),
            int(row["version"]),
        )

    def list_campaigns(self, workspace_id: str = "") -> list[CampaignRecord]:
        sql = f"SELECT {CAMPAIGN_COLUMNS} FROM campaigns"
        params: tuple[Any, ...] = ()
        if workspace_id:
            sql += " WHERE workspace_id=?"
            params = (workspace_id,)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self.get_campaign(str(row["id"])) for row in rows]

    def update_campaign_status(self, campaign_id: str, status: str, *, expected_version: int) -> CampaignRecord:
        with self.transaction() as connection:
            row = connection.execute("SELECT version FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            if not row or int(row["version"]) != expected_version:
                raise OwnedPublicationError("workspace.conflict", "Campaign version conflict.")
            connection.execute(
                "UPDATE campaigns SET status=?, version=version+1, updated_at=? WHERE id=?",
                (status, utc_now_iso(), campaign_id),
            )
        return self.get_campaign(campaign_id)

    def ingest_observation(
        self,
        workspace_id: str,
        metric_name: str,
        value: float,
        content_item_id: str,
        content_revision_id: str,
        target_id: str,
        *,
        campaign_id: str = "",
        source: str = "",
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "metric_name": metric_name,
            "value": value,
            "content_item_id": content_item_id,
            "content_revision_id": content_revision_id,
            "target_id": target_id,
            "campaign_id": campaign_id,
            "source": source,
        }
        return self._idempotent(
            workspace_id,
            "funnel.observation",
            idempotency_key,
            payload,
            lambda connection: self._ingest_observation_tx(
                connection,
                workspace_id,
                metric_name,
                value,
                content_item_id,
                content_revision_id,
                target_id,
                campaign_id,
                source,
                idempotency_key,
            ),
        )

    def _ingest_observation_tx(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        metric_name: str,
        value: float,
        content_item_id: str,
        content_revision_id: str,
        target_id: str,
        campaign_id: str,
        source: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        observation_id = f"obs-{stable_checksum(idempotency_key)[:12]}"
        connection.execute(
            "INSERT INTO funnel_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                observation_id,
                workspace_id,
                metric_name,
                value,
                content_item_id,
                content_revision_id,
                target_id,
                "",
                campaign_id,
                source,
                utc_now_iso(),
                "{}",
                "",
                idempotency_key,
            ),
        )
        return {"id": observation_id}

    def rebuild_readmodel(self, workspace_id: str, readmodel_type: str, subject_id: str) -> dict[str, Any]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT metric_name, value FROM funnel_observations WHERE workspace_id=? AND (content_item_id=? OR campaign_id=?)",
                (workspace_id, subject_id, subject_id),
            ).fetchall()
            totals: dict[str, float] = {}
            for row in rows:
                totals[row["metric_name"]] = totals.get(row["metric_name"], 0.0) + float(row["value"])
            connection.execute(
                "UPDATE funnel_readmodels SET current=0 WHERE workspace_id=? AND readmodel_type=? AND subject_id=?",
                (workspace_id, readmodel_type, subject_id),
            )
            readmodel_id = (
                f"readmodel-{stable_checksum(workspace_id + readmodel_type + subject_id + utc_now_iso())[:12]}"
            )
            payload = {"totals": totals, "causality_claimed": False}
            connection.execute(
                "INSERT INTO funnel_readmodels VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    readmodel_id,
                    workspace_id,
                    readmodel_type,
                    subject_id,
                    _json(payload),
                    utc_now_iso(),
                    FUNNEL_READMODEL_CONTRACT_VERSION,
                    utc_now_iso(),
                    "complete" if rows else "partial",
                    0,
                    "[]",
                    1,
                ),
            )
        return {"id": readmodel_id, "payload": payload, "current": True}

    def readmodels_status(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT readmodel_type, subject_id, stale, current FROM funnel_readmodels"
            ).fetchall()
        return {"readmodels": [dict(row) for row in rows], "rebuildable": True}

    def recovery(self) -> dict[str, Any]:
        now = utc_now_iso()
        with self.transaction() as connection:
            expired_occurrences = connection.execute(
                "UPDATE publication_occurrences SET status='waiting_dependency', lease_owner='', lease_expires_at='' "
                "WHERE lease_expires_at != '' AND lease_expires_at < ?",
                (now,),
            ).rowcount
            expired_reconciliation = connection.execute(
                "UPDATE reconciliation_items SET status='open', lease_owner='', lease_expires_at='' "
                "WHERE lease_expires_at != '' AND lease_expires_at < ?",
                (now,),
            ).rowcount
            connection.execute("DELETE FROM reconciliation_leases WHERE expires_at < ?", (now,))
            post_mutation = connection.execute(
                "SELECT id, workspace_id, target_id FROM publication_execution_events "
                "WHERE mutation_state IN ('mutation_started', 'mutation_acknowledged')"
            ).fetchall()
        return {
            "expired_occurrence_leases_released": expired_occurrences,
            "expired_reconciliation_leases_released": expired_reconciliation,
            "post_mutation_attempts_require_reconciliation": len(post_mutation),
            "blind_retry": False,
        }

    def integrity_scan(self, workspace_id: str = "") -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        with self._connect() as connection:
            variants = connection.execute(
                "SELECT v.id FROM owned_publication_variants v LEFT JOIN owned_publication_revisions r ON v.content_revision_id=r.id WHERE r.id IS NULL"
            ).fetchall()
            deps = connection.execute(
                "SELECT d.id FROM publication_target_dependencies d LEFT JOIN publication_targets t ON d.dependent_target_id=t.id WHERE t.id IS NULL"
            ).fetchall()
            readmodels = connection.execute("SELECT id FROM funnel_readmodels WHERE stale=1").fetchall()
        findings.extend({"category": "orphan_variant", "id": row["id"]} for row in variants)
        findings.extend({"category": "orphan_dependency", "id": row["id"]} for row in deps)
        findings.extend({"category": "stale_readmodel", "id": row["id"]} for row in readmodels)
        return {"findings": findings, "read_only": True, "safe_repairs": ["release_expired_lease", "rebuild_readmodel"]}

    def _idempotent(
        self,
        workspace_id: str,
        operation: str,
        idempotency_key: str,
        payload: Any,
        action: Callable[[sqlite3.Connection], dict[str, Any]],
    ) -> dict[str, Any]:
        checksum = _payload_checksum(payload)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT payload_checksum, result_json FROM owned_publication_idempotency "
                "WHERE workspace_id=? AND operation=? AND idempotency_key=?",
                (workspace_id, operation, idempotency_key),
            ).fetchone()
            if row:
                if row["payload_checksum"] != checksum:
                    raise OwnedPublicationError(
                        "idempotency.conflict", "Idempotency key reused with different payload."
                    )
                return dict(_load_json(row["result_json"]))
            result = action(connection)
            connection.execute(
                "INSERT INTO owned_publication_idempotency VALUES (?, ?, ?, ?, ?, ?)",
                (workspace_id, operation, idempotency_key, checksum, _json(result), utc_now_iso()),
            )
            return result

    def _audit_tx(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        event_type: str,
        actor: str,
        subject_id: str,
        summary: dict[str, Any],
    ) -> None:
        audit_id = f"audit-{stable_checksum(workspace_id + event_type + subject_id + utc_now_iso())[:12]}"
        connection.execute(
            "INSERT OR IGNORE INTO workspace_audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (audit_id, workspace_id, event_type, actor, subject_id, _json(_redact(summary)), utc_now_iso(), audit_id),
        )

    def _draft_from_row(self, row: sqlite3.Row) -> ContentDraft:
        draft = ContentDraft(
            row["id"],
            row["workspace_id"],
            row["title"],
            row["summary"],
            row["markdown_body"],
            tuple(_load_json(row["tags_json"])),
            row["language"],
            row["author"],
            "draft",
            int(row["version"]),
            row["updated_at"],
        )
        if draft.checksum != row["checksum"]:
            raise OwnedPublicationError("storage.checksum_mismatch", "Draft checksum mismatch.")
        return draft

    def _reconciliation_from_row(self, row: sqlite3.Row) -> ReconciliationItem:
        return ReconciliationItem(
            row["id"],
            row["workspace_id"],
            row["publication_plan_id"],
            row["target_id"],
            "",
            row["category"],
            row["mutation_state"],
            row["severity"],
            row["detected_at"],
            _load_json(row["safe_summary_json"]),
            "read_only_check",
            "safe_rebuild",
            row["resolution"],
        )

    def _assert_acyclic(self, dependencies: list[dict[str, str]]) -> None:
        edges: dict[str, set[str]] = {}
        for dependency in dependencies:
            predecessor = dependency["predecessor_target_id"]
            dependent = dependency["dependent_target_id"]
            if predecessor == dependent:
                raise OwnedPublicationError("dependency.self", "Self-dependency is not allowed.")
            edges.setdefault(predecessor, set()).add(dependent)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise OwnedPublicationError("dependency.cycle", "Publication dependency cycle blocked.")
            if node in visited:
                return
            visiting.add(node)
            for child in edges.get(node, ()):
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for node in edges:
            visit(node)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in ("secret", "token", "authorization", "private_key", "cookie")):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and any(
        marker in value.lower() for marker in ("authorization:", "private key", "token=")
    ):
        return "[redacted]"
    return value


class InMemoryOwnedPublicationRepository(DatabaseOwnedPublicationRepository):
    """Test implementation backed by a temporary SQLite database."""

    def __init__(self) -> None:
        fd, path = mkstemp(prefix="smm-owned-publication-", suffix=".sqlite3")
        os.close(fd)
        Path(path).unlink(missing_ok=True)
        super().__init__(path)


__all__ = [
    "CAMPAIGN_WORKSPACE_CONTRACT_VERSION",
    "FUNNEL_READMODEL_CONTRACT_VERSION",
    "OWNED_PUBLICATION_PERSISTENCE_VERSION",
    "OWNED_PUBLICATION_STORAGE_CONTRACT_VERSION",
    "PUBLICATION_EVIDENCE_STORAGE_CONTRACT_VERSION",
    "RECONCILIATION_LEASE_CONTRACT_VERSION",
    "CampaignRecord",
    "DatabaseOwnedPublicationRepository",
    "InMemoryOwnedPublicationRepository",
    "ReconciliationLease",
    "StorageHealth",
    "default_database_path",
    "migration_checksum",
]
