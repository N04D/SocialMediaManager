from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.core.content.models import ContentCompleteness, ContentItem, ContentRevision, ContentType
from src.core.content.resources import ExternalResourceSnapshot, ResourceRef
from src.core.runtime.events import utc_now_iso
from src.core.runtime.execution_context import _assert_no_secret_values


def compute_snapshot_checksum(snapshot: ExternalResourceSnapshot) -> str:
    payload = {
        "canonical_ref": snapshot.resource_ref.canonical_ref,
        "description": snapshot.fields.get("description", ""),
        "duration": snapshot.fields.get("duration", ""),
        "privacy_status": snapshot.fields.get("privacy_status", ""),
        "published_at": snapshot.fields.get("published_at", ""),
        "title": snapshot.fields.get("title", ""),
    }
    dumped = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


class ContentRepository(Protocol):
    def upsert_external_resource(
        self,
        *,
        snapshot: ExternalResourceSnapshot,
        provenance: dict[str, Any],
    ) -> tuple[ContentItem, ContentRevision, bool]: ...

    def get_content_item(self, item_id: str) -> ContentItem | None: ...

    def get_by_external_ref(self, canonical_ref: str) -> ContentItem | None: ...

    def list_revisions(self, item_id: str) -> tuple[ContentRevision, ...]: ...


@dataclass
class InMemoryContentRepository:
    items: dict[str, ContentItem] = field(default_factory=dict)
    revisions: dict[str, list[ContentRevision]] = field(default_factory=dict)
    external_ref_index: dict[str, str] = field(default_factory=dict)

    def upsert_external_resource(
        self,
        *,
        snapshot: ExternalResourceSnapshot,
        provenance: dict[str, Any],
    ) -> tuple[ContentItem, ContentRevision, bool]:
        _assert_no_secret_values(snapshot.fields, code="content_repository.secret_value")
        _assert_no_secret_values(provenance, code="content_repository.secret_value")

        canonical_ref = snapshot.resource_ref.canonical_ref
        checksum = compute_snapshot_checksum(snapshot)
        item_id = self.external_ref_index.get(canonical_ref)

        if item_id and item_id in self.items:
            item = self.items[item_id]
            revs = self.revisions.get(item_id, [])
            latest_rev = revs[-1] if revs else None

            if latest_rev and latest_rev.checksum == checksum:
                # Unchanged observation / replay -> reuse existing item & revision
                return item, latest_rev, False

            # Metadata changed -> create new revision
            rev_number = (latest_rev.revision_number + 1) if latest_rev else 1
            new_title = str(snapshot.fields.get("title") or item.title)
            new_body = str(snapshot.fields.get("description") or item.body)
            rev_id = f"rev_{rev_number}_{snapshot.resource_ref.external_id}"

            new_rev = ContentRevision(
                id=rev_id,
                content_item_id=item.id,
                workspace_id=item.workspace_id,
                revision_number=rev_number,
                title=new_title,
                body=new_body,
                summary=str(snapshot.fields.get("summary") or ""),
                metadata=dict(snapshot.fields),
                primary_source_type=snapshot.resource_ref.provider,
                primary_source_entity_id=snapshot.resource_ref.external_id,
                primary_source_ref=canonical_ref,
                source_provenance=provenance,
                checksum=checksum,
                created_at=snapshot.observed_at or utc_now_iso(),
                change_reason="metadata_update",
            )
            revs.append(new_rev)
            self.revisions[item_id] = revs

            updated_item = ContentItem(
                id=item.id,
                workspace_id=item.workspace_id,
                content_type=item.content_type,
                title=new_title,
                body=new_body,
                summary=item.summary,
                language=item.language,
                status=item.status,
                current_revision_id=new_rev.id,
                created_at=item.created_at,
                updated_at=snapshot.observed_at or utc_now_iso(),
                primary_source_type=item.primary_source_type,
                primary_source_entity_id=item.primary_source_entity_id,
                primary_source_ref=item.primary_source_ref,
                primary_source_metadata=dict(snapshot.fields),
                source_provenance=provenance,
                metadata={
                    "completeness": snapshot.fields.get("completeness", ContentCompleteness.METADATA_ONLY.value),
                    "external_ref": snapshot.resource_ref.to_dict(),
                },
            )
            self.items[item_id] = updated_item
            return updated_item, new_rev, True

        # First observation -> create new ContentItem & initial ContentRevision
        new_item_id = f"entity_{snapshot.resource_ref.provider}_{snapshot.resource_ref.external_id}"
        workspace_id = str(provenance.get("workspace_id") or "ws-default")
        title = str(snapshot.fields.get("title") or "Untitled External Resource")
        body = str(snapshot.fields.get("description") or "")
        created_at = snapshot.observed_at or utc_now_iso()

        initial_rev = ContentRevision(
            id=f"rev_1_{snapshot.resource_ref.external_id}",
            content_item_id=new_item_id,
            workspace_id=workspace_id,
            revision_number=1,
            title=title,
            body=body,
            metadata=dict(snapshot.fields),
            primary_source_type=snapshot.resource_ref.provider,
            primary_source_entity_id=snapshot.resource_ref.external_id,
            primary_source_ref=canonical_ref,
            source_provenance=provenance,
            checksum=checksum,
            created_at=created_at,
            change_reason="initial_ingestion",
        )

        item = ContentItem(
            id=new_item_id,
            workspace_id=workspace_id,
            content_type=ContentType.ARTICLE_SOURCE.value,
            title=title,
            body=body,
            current_revision_id=initial_rev.id,
            created_at=created_at,
            updated_at=created_at,
            primary_source_type=snapshot.resource_ref.provider,
            primary_source_entity_id=snapshot.resource_ref.external_id,
            primary_source_ref=canonical_ref,
            primary_source_metadata=dict(snapshot.fields),
            source_provenance=provenance,
            metadata={
                "completeness": snapshot.fields.get("completeness", ContentCompleteness.METADATA_ONLY.value),
                "external_ref": snapshot.resource_ref.to_dict(),
            },
        )

        self.items[new_item_id] = item
        self.revisions[new_item_id] = [initial_rev]
        self.external_ref_index[canonical_ref] = new_item_id
        return item, initial_rev, True

    def get_content_item(self, item_id: str) -> ContentItem | None:
        return self.items.get(item_id)

    def get_by_external_ref(self, canonical_ref: str) -> ContentItem | None:
        item_id = self.external_ref_index.get(canonical_ref)
        return self.items.get(item_id) if item_id else None

    def list_revisions(self, item_id: str) -> tuple[ContentRevision, ...]:
        return tuple(self.revisions.get(item_id, []))


class SqliteContentRepository:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_items (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    current_revision_id TEXT NOT NULL,
                    primary_source_type TEXT NOT NULL,
                    primary_source_entity_id TEXT NOT NULL,
                    primary_source_ref TEXT UNIQUE NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_revisions (
                    id TEXT PRIMARY KEY,
                    content_item_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    revision_number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(content_item_id) REFERENCES content_items(id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rev_item ON content_revisions(content_item_id, revision_number)")

    def upsert_external_resource(
        self,
        *,
        snapshot: ExternalResourceSnapshot,
        provenance: dict[str, Any],
    ) -> tuple[ContentItem, ContentRevision, bool]:
        _assert_no_secret_values(snapshot.fields, code="content_repository.secret_value")
        _assert_no_secret_values(provenance, code="content_repository.secret_value")

        canonical_ref = snapshot.resource_ref.canonical_ref
        checksum = compute_snapshot_checksum(snapshot)

        existing_item = self.get_by_external_ref(canonical_ref)
        if existing_item:
            revs = self.list_revisions(existing_item.id)
            latest_rev = revs[-1] if revs else None

            if latest_rev and latest_rev.checksum == checksum:
                return existing_item, latest_rev, False

            rev_number = (latest_rev.revision_number + 1) if latest_rev else 1
            new_title = str(snapshot.fields.get("title") or existing_item.title)
            new_body = str(snapshot.fields.get("description") or existing_item.body)
            rev_id = f"rev_{rev_number}_{snapshot.resource_ref.external_id}"

            new_rev = ContentRevision(
                id=rev_id,
                content_item_id=existing_item.id,
                workspace_id=existing_item.workspace_id,
                revision_number=rev_number,
                title=new_title,
                body=new_body,
                metadata=dict(snapshot.fields),
                primary_source_type=snapshot.resource_ref.provider,
                primary_source_entity_id=snapshot.resource_ref.external_id,
                primary_source_ref=canonical_ref,
                source_provenance=provenance,
                checksum=checksum,
                created_at=snapshot.observed_at or utc_now_iso(),
                change_reason="metadata_update",
            )
            updated_item = ContentItem(
                id=existing_item.id,
                workspace_id=existing_item.workspace_id,
                content_type=existing_item.content_type,
                title=new_title,
                body=new_body,
                current_revision_id=new_rev.id,
                created_at=existing_item.created_at,
                updated_at=snapshot.observed_at or utc_now_iso(),
                primary_source_type=existing_item.primary_source_type,
                primary_source_entity_id=existing_item.primary_source_entity_id,
                primary_source_ref=existing_item.primary_source_ref,
                primary_source_metadata=dict(snapshot.fields),
                source_provenance=provenance,
                metadata={
                    "completeness": snapshot.fields.get("completeness", ContentCompleteness.METADATA_ONLY.value),
                    "external_ref": snapshot.resource_ref.to_dict(),
                },
            )
            self._save_revision(new_rev)
            self._save_item(updated_item)
            return updated_item, new_rev, True

        new_item_id = f"entity_{snapshot.resource_ref.provider}_{snapshot.resource_ref.external_id}"
        workspace_id = str(provenance.get("workspace_id") or "ws-default")
        title = str(snapshot.fields.get("title") or "Untitled External Resource")
        body = str(snapshot.fields.get("description") or "")
        created_at = snapshot.observed_at or utc_now_iso()

        initial_rev = ContentRevision(
            id=f"rev_1_{snapshot.resource_ref.external_id}",
            content_item_id=new_item_id,
            workspace_id=workspace_id,
            revision_number=1,
            title=title,
            body=body,
            metadata=dict(snapshot.fields),
            primary_source_type=snapshot.resource_ref.provider,
            primary_source_entity_id=snapshot.resource_ref.external_id,
            primary_source_ref=canonical_ref,
            source_provenance=provenance,
            checksum=checksum,
            created_at=created_at,
            change_reason="initial_ingestion",
        )

        item = ContentItem(
            id=new_item_id,
            workspace_id=workspace_id,
            content_type=ContentType.ARTICLE_SOURCE.value,
            title=title,
            body=body,
            current_revision_id=initial_rev.id,
            created_at=created_at,
            updated_at=created_at,
            primary_source_type=snapshot.resource_ref.provider,
            primary_source_entity_id=snapshot.resource_ref.external_id,
            primary_source_ref=canonical_ref,
            primary_source_metadata=dict(snapshot.fields),
            source_provenance=provenance,
            metadata={
                "completeness": snapshot.fields.get("completeness", ContentCompleteness.METADATA_ONLY.value),
                "external_ref": snapshot.resource_ref.to_dict(),
            },
        )
        self._save_revision(initial_rev)
        self._save_item(item)
        return item, initial_rev, True

    def _save_item(self, item: ContentItem) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO content_items (
                    id, workspace_id, content_type, title, body, current_revision_id,
                    primary_source_type, primary_source_entity_id, primary_source_ref,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    body=excluded.body,
                    current_revision_id=excluded.current_revision_id,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    item.id,
                    item.workspace_id,
                    item.content_type,
                    item.title,
                    item.body,
                    item.current_revision_id,
                    item.primary_source_type,
                    item.primary_source_entity_id,
                    item.primary_source_ref,
                    json.dumps({
                        "metadata": item.metadata,
                        "primary_source_metadata": item.primary_source_metadata,
                        "source_provenance": item.source_provenance,
                    }),
                    item.created_at,
                    item.updated_at,
                ),
            )

    def _save_revision(self, rev: ContentRevision) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO content_revisions (
                    id, content_item_id, workspace_id, revision_number, title, body, checksum, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    body=excluded.body,
                    checksum=excluded.checksum,
                    payload_json=excluded.payload_json
                """,
                (
                    rev.id,
                    rev.content_item_id,
                    rev.workspace_id,
                    rev.revision_number,
                    rev.title,
                    rev.body,
                    rev.checksum,
                    json.dumps({
                        "change_reason": rev.change_reason,
                        "metadata": rev.metadata,
                        "primary_source_entity_id": rev.primary_source_entity_id,
                        "primary_source_ref": rev.primary_source_ref,
                        "primary_source_type": rev.primary_source_type,
                        "source_provenance": rev.source_provenance,
                    }),
                    rev.created_at,
                ),
            )

    def get_content_item(self, item_id: str) -> ContentItem | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM content_items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                return None
            payload = json.loads(row["payload_json"])
            return ContentItem(
                id=row["id"],
                workspace_id=row["workspace_id"],
                content_type=row["content_type"],
                title=row["title"],
                body=row["body"],
                current_revision_id=row["current_revision_id"],
                primary_source_type=row["primary_source_type"],
                primary_source_entity_id=row["primary_source_entity_id"],
                primary_source_ref=row["primary_source_ref"],
                primary_source_metadata=dict(payload.get("primary_source_metadata") or {}),
                source_provenance=dict(payload.get("source_provenance") or {}),
                metadata=dict(payload.get("metadata") or {}),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def get_by_external_ref(self, canonical_ref: str) -> ContentItem | None:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM content_items WHERE primary_source_ref = ?", (canonical_ref,)).fetchone()
            if not row:
                return None
            return self.get_content_item(row["id"])

    def list_revisions(self, item_id: str) -> tuple[ContentRevision, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM content_revisions WHERE content_item_id = ? ORDER BY revision_number ASC", (item_id,)
            ).fetchall()
            results: list[ContentRevision] = []
            for row in rows:
                payload = json.loads(row["payload_json"])
                results.append(
                    ContentRevision(
                        id=row["id"],
                        content_item_id=row["content_item_id"],
                        workspace_id=row["workspace_id"],
                        revision_number=row["revision_number"],
                        title=row["title"],
                        body=row["body"],
                        checksum=row["checksum"],
                        created_at=row["created_at"],
                        change_reason=str(payload.get("change_reason") or ""),
                        metadata=dict(payload.get("metadata") or {}),
                        primary_source_entity_id=str(payload.get("primary_source_entity_id") or ""),
                        primary_source_ref=str(payload.get("primary_source_ref") or ""),
                        primary_source_type=str(payload.get("primary_source_type") or ""),
                        source_provenance=dict(payload.get("source_provenance") or {}),
                    )
                )
            return tuple(results)
