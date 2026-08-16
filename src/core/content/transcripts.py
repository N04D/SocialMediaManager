from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from typing import Any

from src.core.content.artifacts import (
    MAX_TRANSCRIPT_BYTES,
    ArtifactError,
    ArtifactRepository,
    LocalArtifactStorage,
    canonical_json,
    artifact_identity,
    new_artifact,
    sha256_bytes,
    sha256_json,
    transcript_completeness_metadata,
)
from src.core.content.models import Artifact, ArtifactType, ContentCompleteness, ContentItem, ContentRevision
from src.core.content.repository import ContentRepository
from src.core.runtime.events import utc_now_iso
from src.core.runtime.execution_context import _assert_no_secret_values

PARSER_ID = "smm.vtt.transcript"
PARSER_VERSION = "0.1.0"


@dataclass(frozen=True)
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class NormalizedTranscript:
    language: str
    segments: tuple[TranscriptSegment, ...]
    plain_text: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "plain_text": self.plain_text,
            "segments": [asdict(segment) for segment in self.segments],
        }


_TIMING_RE = re.compile(
    r"(?P<start>\d{2,}:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})\s*-->\s*"
    r"(?P<end>\d{2,}:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_timestamp(value: str) -> int:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds_raw = parts[1]
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_raw = parts[2]
    else:
        raise ArtifactError("TRANSCRIPT_PARSE_FAILED", "Malformed transcript timestamp.")
    seconds, millis = seconds_raw.split(".", 1)
    if len(millis) != 3:
        raise ArtifactError("TRANSCRIPT_PARSE_FAILED", "Malformed transcript timestamp precision.")
    total = ((hours * 60 + minutes) * 60 + int(seconds)) * 1000 + int(millis)
    if total < 0:
        raise ArtifactError("TRANSCRIPT_PARSE_FAILED", "Negative transcript timestamp.")
    return total


def normalize_caption_text(lines: list[str]) -> str:
    text = "\n".join(line.strip() for line in lines).strip()
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_vtt(data: bytes | str, *, language: str = "", max_bytes: int = MAX_TRANSCRIPT_BYTES) -> NormalizedTranscript:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > max_bytes:
        raise ArtifactError("ARTIFACT_TOO_LARGE", "Transcript exceeds the configured input size limit.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ArtifactError("TRANSCRIPT_PARSE_FAILED", "Transcript is not valid Unicode.") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[0].strip().startswith("WEBVTT"):
        lines = lines[1:]

    segments: list[TranscriptSegment] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            index += 1
            while index < len(lines) and lines[index].strip():
                index += 1
            continue
        match = _TIMING_RE.search(line)
        if not match and index + 1 < len(lines):
            match = _TIMING_RE.search(lines[index + 1].strip())
            if match:
                index += 1
        if not match:
            raise ArtifactError("TRANSCRIPT_PARSE_FAILED", "Transcript cue timestamp is malformed.")
        start_ms = parse_timestamp(match.group("start"))
        end_ms = parse_timestamp(match.group("end"))
        if end_ms < start_ms:
            raise ArtifactError("TRANSCRIPT_PARSE_FAILED", "Transcript cue ends before it starts.")
        index += 1
        cue_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            cue_lines.append(lines[index])
            index += 1
        cue_text = normalize_caption_text(cue_lines)
        if cue_text:
            segments.append(TranscriptSegment(start_ms=start_ms, end_ms=end_ms, text=cue_text))

    if not segments:
        raise ArtifactError("TRANSCRIPT_EMPTY", "Transcript does not contain any usable cue text.")
    plain_text = "\n".join(segment.text for segment in segments)
    return NormalizedTranscript(language=language, segments=tuple(segments), plain_text=plain_text)


class TranscriptArtifactIngestor:
    def __init__(
        self,
        *,
        content_repository: ContentRepository,
        artifact_repository: ArtifactRepository,
        storage: LocalArtifactStorage,
    ):
        self.content_repository = content_repository
        self.artifact_repository = artifact_repository
        self.storage = storage

    def ingest_raw_transcript(
        self,
        *,
        content_item: ContentItem,
        revision: ContentRevision,
        raw_data: bytes | str,
        media_type: str,
        source: str,
        language: str,
        provenance: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Artifact, bool]:
        raw = raw_data.encode("utf-8") if isinstance(raw_data, str) else raw_data
        if len(raw) > MAX_TRANSCRIPT_BYTES:
            raise ArtifactError("ARTIFACT_TOO_LARGE", "Transcript exceeds the configured input size limit.")
        content_hash = sha256_bytes(raw)
        candidate_metadata = dict(metadata or {})
        candidate_id = artifact_identity(
            content_entity_id=content_item.id,
            revision_id=revision.id,
            artifact_type=ArtifactType.TRANSCRIPT_RAW.value,
            source=source,
            language=language,
            content_hash=content_hash,
            metadata=candidate_metadata,
        )
        existing = self.artifact_repository.get(candidate_id)
        if existing:
            return existing, False
        _, storage_ref = self.storage.store(raw, media_type=media_type, content_hash=content_hash)
        safe_provenance = dict(provenance)
        safe_provenance.setdefault("retrieved_at", utc_now_iso())
        artifact = new_artifact(
            content_entity_id=content_item.id,
            revision_id=revision.id,
            artifact_type=ArtifactType.TRANSCRIPT_RAW,
            media_type=media_type,
            source=source,
            language=language,
            content_hash=content_hash,
            storage_ref=storage_ref,
            provenance=safe_provenance,
            metadata=candidate_metadata,
        )
        return self.artifact_repository.save(artifact)

    def normalize_raw_artifact(self, raw_artifact: Artifact) -> tuple[Artifact, bool, NormalizedTranscript]:
        if raw_artifact.artifact_type != ArtifactType.TRANSCRIPT_RAW.value:
            raise ArtifactError("TRANSCRIPT_PARSE_FAILED", "Only raw transcript artifacts can be normalized.")
        raw = self.storage.read(raw_artifact.storage_ref)
        transcript = parse_vtt(raw, language=raw_artifact.language)
        normalized_payload = {
            "normalized_transcript": transcript.to_payload(),
            "parser_id": PARSER_ID,
            "parser_version": PARSER_VERSION,
            "source_artifact_id": raw_artifact.artifact_id,
        }
        normalized_hash = sha256_json(normalized_payload)
        metadata = {
            "generation_method": "provider_asr"
            if str(raw_artifact.metadata.get("track_kind", "")).lower() == "asr"
            else "provider_caption"
            if raw_artifact.source == "youtube_official_captions"
            else "user_supplied",
            "normalized_content_hash": normalized_hash,
            "parser_id": PARSER_ID,
            "parser_version": PARSER_VERSION,
            "source_artifact_id": raw_artifact.artifact_id,
        }
        existing = self.artifact_repository.find_by_hash(
            content_entity_id=raw_artifact.content_entity_id,
            artifact_type=ArtifactType.TRANSCRIPT_NORMALIZED.value,
            content_hash=normalized_hash,
            language=raw_artifact.language,
        )
        if existing:
            return existing, False, transcript
        _, storage_ref = self.storage.store(
            canonical_json(normalized_payload).encode("utf-8"),
            media_type="application/json",
            content_hash=normalized_hash,
        )
        provenance = dict(raw_artifact.provenance)
        provenance.update(
            {
                "parser_id": PARSER_ID,
                "parser_version": PARSER_VERSION,
                "raw_artifact_hash": raw_artifact.content_hash,
                "source_artifact_id": raw_artifact.artifact_id,
            }
        )
        artifact = new_artifact(
            content_entity_id=raw_artifact.content_entity_id,
            revision_id=raw_artifact.revision_id,
            artifact_type=ArtifactType.TRANSCRIPT_NORMALIZED,
            media_type="application/json",
            source=raw_artifact.source,
            language=raw_artifact.language,
            content_hash=normalized_hash,
            storage_ref=storage_ref,
            provenance=provenance,
            metadata=metadata,
        )
        return (*self.artifact_repository.save(artifact), transcript)

    def ingest_transcript(
        self,
        *,
        content_item: ContentItem,
        revision: ContentRevision,
        raw_data: bytes | str,
        media_type: str = "text/vtt",
        source: str,
        language: str,
        provenance: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _assert_no_secret_values(provenance, code="transcript.provenance")
        raw_artifact, raw_created = self.ingest_raw_transcript(
            content_item=content_item,
            revision=revision,
            raw_data=raw_data,
            media_type=media_type,
            source=source,
            language=language,
            provenance=provenance,
            metadata=metadata,
        )
        normalized_artifact, normalized_created, transcript = self.normalize_raw_artifact(raw_artifact)
        self.mark_transcript_available(content_item, normalized_artifact)
        return {
            "status": ContentCompleteness.TRANSCRIPT_AVAILABLE.value,
            "raw_artifact": raw_artifact,
            "raw_created": raw_created,
            "normalized_artifact": normalized_artifact,
            "normalized_created": normalized_created,
            "transcript": transcript,
        }

    def ingest_supplied_transcript(
        self,
        *,
        content_item: ContentItem,
        revision: ContentRevision,
        transcript_vtt: bytes | str,
        language: str,
        supplied_by: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        supplied_provenance = {
            "provider": "user_supplied",
            "source": "user_supplied",
            "supplied_by": supplied_by,
            "retrieved_at": utc_now_iso(),
        }
        supplied_provenance.update(provenance or {})
        return self.ingest_transcript(
            content_item=content_item,
            revision=revision,
            raw_data=transcript_vtt,
            media_type="text/vtt",
            source="user_supplied",
            language=language,
            provenance=supplied_provenance,
            metadata={"source": "user_supplied"},
        )

    def reconcile_transcript_availability(self, content_item: ContentItem) -> ContentItem:
        normalized = self.artifact_repository.find(
            content_entity_id=content_item.id,
            artifact_type=ArtifactType.TRANSCRIPT_NORMALIZED.value,
        )
        if not normalized:
            return content_item
        latest = normalized[-1]
        return self.mark_transcript_available(content_item, latest)

    def mark_transcript_available(self, content_item: ContentItem, normalized_artifact: Artifact) -> ContentItem:
        updated = ContentItem(
            **{
                **content_item.__dict__,
                "metadata": transcript_completeness_metadata(content_item, normalized_artifact=normalized_artifact),
                "updated_at": utc_now_iso(),
            }
        )
        saver = getattr(self.content_repository, "save_content_item", None)
        if callable(saver):
            saver(updated)
        elif hasattr(self.content_repository, "items"):
            self.content_repository.items[updated.id] = updated  # type: ignore[attr-defined]
        return updated
