from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.core.content.models import Artifact, ArtifactType, ContentCompleteness, ContentItem
from src.core.runtime.events import utc_now_iso
from src.core.runtime.execution_context import _assert_no_secret_values


MAX_TRANSCRIPT_BYTES = 2_000_000


class ArtifactError(Exception):
    def __init__(self, code: str, message: str, metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.metadata = dict(metadata or {})


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class LocalArtifactStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def store(self, data: bytes, *, media_type: str, content_hash: str = "") -> tuple[str, str]:
        if len(data) > MAX_TRANSCRIPT_BYTES:
            raise ArtifactError("ARTIFACT_TOO_LARGE", "Artifact exceeds the configured transcript size limit.")
        digest = content_hash or sha256_bytes(data)
        suffix = ".json" if media_type == "application/json" else ".vtt" if media_type == "text/vtt" else ".bin"
        rel = Path("artifacts") / digest[:2] / f"{digest}{suffix}"
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        return digest, rel.as_posix()

    def read(self, storage_ref: str) -> bytes:
        rel = Path(storage_ref)
        if rel.is_absolute() or ".." in rel.parts:
            raise ArtifactError("ARTIFACT_STORAGE_REF_INVALID", "Artifact storage reference is not portable.")
        return (self.root / rel).read_bytes()


def artifact_identity(
    *,
    content_entity_id: str,
    revision_id: str,
    artifact_type: str,
    source: str,
    language: str,
    content_hash: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    identity_metadata = {
        key: value
        for key, value in dict(metadata or {}).items()
        if key
        in {
            "caption_track_id",
            "provider_track_identity",
            "parser_id",
            "parser_version",
            "source_artifact_id",
        }
    }
    digest = sha256_json(
        {
            "artifact_type": artifact_type,
            "content_entity_id": content_entity_id,
            "content_hash": content_hash,
            "language": language,
            "metadata": identity_metadata,
            "revision_id": revision_id,
            "source": source,
        }
    )
    return f"artifact_{digest[:32]}"


class ArtifactRepository(Protocol):
    def save(self, artifact: Artifact) -> tuple[Artifact, bool]: ...

    def get(self, artifact_id: str) -> Artifact | None: ...

    def find(self, *, content_entity_id: str = "", artifact_type: str = "") -> tuple[Artifact, ...]: ...

    def find_by_hash(
        self, *, content_entity_id: str, artifact_type: str, content_hash: str, language: str = ""
    ) -> Artifact | None: ...


@dataclass
class InMemoryArtifactRepository:
    artifacts: dict[str, Artifact] = field(default_factory=dict)

    def save(self, artifact: Artifact) -> tuple[Artifact, bool]:
        _assert_no_secret_values(asdict(artifact), code="artifact.secret_value")
        existing = self.artifacts.get(artifact.artifact_id)
        if existing:
            return existing, False
        self.artifacts[artifact.artifact_id] = artifact
        return artifact, True

    def get(self, artifact_id: str) -> Artifact | None:
        return self.artifacts.get(artifact_id)

    def find(self, *, content_entity_id: str = "", artifact_type: str = "") -> tuple[Artifact, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self.artifacts.values()
                    if (not content_entity_id or item.content_entity_id == content_entity_id)
                    and (not artifact_type or item.artifact_type == artifact_type)
                ),
                key=lambda item: (item.created_at, item.artifact_id),
            )
        )

    def find_by_hash(
        self, *, content_entity_id: str, artifact_type: str, content_hash: str, language: str = ""
    ) -> Artifact | None:
        for item in self.find(content_entity_id=content_entity_id, artifact_type=artifact_type):
            if item.content_hash == content_hash and (not language or item.language == language):
                return item
        return None


class SqliteArtifactRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    content_entity_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    language TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    storage_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifact_entity_type ON content_artifacts(content_entity_id, artifact_type)"
            )

    def save(self, artifact: Artifact) -> tuple[Artifact, bool]:
        _assert_no_secret_values(asdict(artifact), code="artifact.secret_value")
        existing = self.get(artifact.artifact_id)
        if existing:
            return existing, False
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO content_artifacts (
                    artifact_id, content_entity_id, revision_id, artifact_type, media_type,
                    source, language, content_hash, storage_ref, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.content_entity_id,
                    artifact.revision_id,
                    artifact.artifact_type,
                    artifact.media_type,
                    artifact.source,
                    artifact.language,
                    artifact.content_hash,
                    artifact.storage_ref,
                    artifact.created_at,
                    json.dumps({"metadata": artifact.metadata, "provenance": artifact.provenance}, sort_keys=True),
                ),
            )
        return artifact, True

    def get(self, artifact_id: str) -> Artifact | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM content_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        return _artifact_from_row(row) if row else None

    def find(self, *, content_entity_id: str = "", artifact_type: str = "") -> tuple[Artifact, ...]:
        clauses: list[str] = []
        params: list[str] = []
        if content_entity_id:
            clauses.append("content_entity_id = ?")
            params.append(content_entity_id)
        if artifact_type:
            clauses.append("artifact_type = ?")
            params.append(artifact_type)
        query = "SELECT * FROM content_artifacts"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at ASC, artifact_id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def find_by_hash(
        self, *, content_entity_id: str, artifact_type: str, content_hash: str, language: str = ""
    ) -> Artifact | None:
        query = (
            "SELECT * FROM content_artifacts WHERE content_entity_id = ? AND artifact_type = ? "
            "AND content_hash = ?"
        )
        params: list[str] = [content_entity_id, artifact_type, content_hash]
        if language:
            query += " AND language = ?"
            params.append(language)
        query += " ORDER BY created_at ASC, artifact_id ASC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return _artifact_from_row(row) if row else None


def _artifact_from_row(row: sqlite3.Row) -> Artifact:
    payload = json.loads(row["payload_json"])
    return Artifact(
        artifact_id=row["artifact_id"],
        content_entity_id=row["content_entity_id"],
        revision_id=row["revision_id"],
        artifact_type=row["artifact_type"],
        media_type=row["media_type"],
        source=row["source"],
        language=row["language"],
        content_hash=row["content_hash"],
        storage_ref=row["storage_ref"],
        created_at=row["created_at"],
        provenance=dict(payload.get("provenance") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def transcript_completeness_metadata(item: ContentItem, *, normalized_artifact: Artifact) -> dict[str, Any]:
    metadata = dict(item.metadata)
    metadata["completeness"] = ContentCompleteness.TRANSCRIPT_AVAILABLE.value
    metadata["current_transcript_artifact_id"] = normalized_artifact.artifact_id
    metadata["current_transcript_language"] = normalized_artifact.language
    metadata["current_transcript_source"] = normalized_artifact.source
    metadata["current_transcript_generation_method"] = normalized_artifact.metadata.get("generation_method", "")
    return metadata


def new_artifact(
    *,
    content_entity_id: str,
    revision_id: str,
    artifact_type: ArtifactType | str,
    media_type: str,
    source: str,
    language: str,
    content_hash: str,
    storage_ref: str,
    provenance: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    created_at: str = "",
) -> Artifact:
    metadata = dict(metadata or {})
    artifact_type_value = artifact_type.value if isinstance(artifact_type, ArtifactType) else str(artifact_type)
    return Artifact(
        artifact_id=artifact_identity(
            content_entity_id=content_entity_id,
            revision_id=revision_id,
            artifact_type=artifact_type_value,
            source=source,
            language=language,
            content_hash=content_hash,
            metadata=metadata,
        ),
        content_entity_id=content_entity_id,
        revision_id=revision_id,
        artifact_type=artifact_type_value,
        media_type=media_type,
        source=source,
        language=language,
        content_hash=content_hash,
        storage_ref=storage_ref,
        created_at=created_at or utc_now_iso(),
        provenance=dict(provenance),
        metadata=metadata,
    )
