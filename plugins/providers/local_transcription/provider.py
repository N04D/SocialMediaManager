from __future__ import annotations

import importlib.util
import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import channel_store
from media_store import get_media_asset, save_media_asset
from plugins.transformations.video_repurpose.ffmpeg_boundary import (
    FFmpegBoundaryError,
    ensure_managed_path,
    run_ffmpeg,
)
from src.core.content import AssetContract, ProvenanceRecord, TimelineSegment, TransformationContract
from src.core.media import MediaAsset, MediaInput, MediaSourceType, MediaStatus, MediaStoreOptions, media_type_for_mime

PROVIDER_ID = "provider.transcription.local"
PROVIDER_VERSION = "0.1.0"
TRANSCRIPTION_CONTRACT_VERSION = "0.1"


class TranscriptionError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class LocalTranscriptionConfig:
    engine: str = "whisper_compatible_local"
    model: str = ""
    device: str = "cpu"
    compute_type: str = "default"
    language: str = "auto"
    default_priority: int = 5
    deterministic_fixture_enabled: bool = False

    @classmethod
    def from_app_config(cls, config: Any) -> LocalTranscriptionConfig:
        return cls(
            engine=str(
                getattr(config, "transcription_engine", "whisper_compatible_local") or "whisper_compatible_local"
            ),
            model=str(getattr(config, "transcription_model", "") or ""),
            device=str(getattr(config, "transcription_device", "cpu") or "cpu"),
            compute_type=str(getattr(config, "transcription_compute_type", "default") or "default"),
            language=str(getattr(config, "transcription_language", "auto") or "auto"),
            deterministic_fixture_enabled=bool(getattr(config, "transcription_deterministic_fixture_enabled", False)),
        )


@dataclass(frozen=True)
class TranscriptSegment:
    segment_id: str
    start_time: float
    end_time: float
    text: str
    confidence: float | None = None
    words: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    language: str
    segments: tuple[TranscriptSegment, ...]
    duration: float
    provider_id: str
    engine: str
    model: str
    created_at: str
    source_asset_id: str
    status: str = "succeeded"
    provider_version: str = PROVIDER_VERSION
    audio_asset_id: str = ""
    run_id: str = ""
    transcript_asset: AssetContract | None = None
    canonical_text: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def timeline(self) -> list[TimelineSegment]:
        return [
            TimelineSegment(
                start_time=segment.start_time,
                end_time=segment.end_time,
                text=segment.text,
                signals={"segment_id": segment.segment_id, "confidence": segment.confidence},
            )
            for segment in self.segments
        ]


class TranscriptionEngine(Protocol):
    engine_id: str

    def available(self, config: LocalTranscriptionConfig) -> tuple[bool, str]: ...

    def transcribe(
        self, audio_path: Path, *, config: LocalTranscriptionConfig, source_duration: float
    ) -> TranscriptResult: ...


class WhisperLocalEngine:
    engine_id = "whisper_compatible_local"

    def available(self, config: LocalTranscriptionConfig) -> tuple[bool, str]:
        if not config.model:
            return False, "model_unavailable"
        if importlib.util.find_spec("faster_whisper") is None:
            return False, "engine_unavailable"
        return True, "ready"

    def transcribe(
        self, audio_path: Path, *, config: LocalTranscriptionConfig, source_duration: float
    ) -> TranscriptResult:
        available, code = self.available(config)
        if not available:
            raise TranscriptionError(code, "Local Whisper-compatible engine is not configured.")
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        model = WhisperModel(config.model, device=config.device, compute_type=config.compute_type)
        language = None if config.language == "auto" else config.language
        segments_raw, info = model.transcribe(str(audio_path), language=language)
        segments: list[TranscriptSegment] = []
        for index, segment in enumerate(segments_raw, start=1):
            text = str(getattr(segment, "text", "")).strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    segment_id=f"segment_{index:04d}",
                    start_time=float(getattr(segment, "start", 0.0)),
                    end_time=float(getattr(segment, "end", 0.0)),
                    text=text,
                )
            )
        detected_language = str(getattr(info, "language", "") or config.language or "und")
        return TranscriptResult(
            text=" ".join(segment.text for segment in segments).strip(),
            language=detected_language,
            segments=tuple(segments),
            duration=source_duration,
            provider_id=PROVIDER_ID,
            engine=self.engine_id,
            model=config.model,
            created_at=channel_store.now_iso(),
            source_asset_id="",
        )


class DeterministicTranscriptionEngine:
    engine_id = "deterministic_fixture"

    def __init__(self, *, language: str = "en", segments: tuple[TranscriptSegment, ...] | None = None) -> None:
        self.language = language
        self.segments = segments or (
            TranscriptSegment(
                segment_id="segment_0001",
                start_time=0.0,
                end_time=10.0,
                text="What makes a short worth watching? It starts with one clear promise and ends with one complete idea.",
                confidence=0.99,
            ),
            TranscriptSegment(
                segment_id="segment_0002",
                start_time=10.0,
                end_time=20.0,
                text="Why does Sabr matter in daily creative work? It helps you keep moving without rushing the result.",
                confidence=0.99,
            ),
            TranscriptSegment(
                segment_id="segment_0003",
                start_time=20.0,
                end_time=30.0,
                text="When a long story becomes heavy, choose the moment where the viewer can understand the whole lesson.",
                confidence=0.98,
            ),
            TranscriptSegment(
                segment_id="segment_0004",
                start_time=30.0,
                end_time=40.0,
                text="A simple creator workflow is upload, choose, render, preview, and then write the supporting caption.",
                confidence=0.98,
            ),
        )

    def available(self, config: LocalTranscriptionConfig) -> tuple[bool, str]:
        return True, "ready"

    def transcribe(
        self, audio_path: Path, *, config: LocalTranscriptionConfig, source_duration: float
    ) -> TranscriptResult:
        del audio_path
        segments = tuple(segment for segment in self.segments if segment.end_time <= source_duration + 1.0)
        return TranscriptResult(
            text=" ".join(segment.text for segment in segments),
            language=config.language if config.language != "auto" else self.language,
            segments=segments,
            duration=source_duration,
            provider_id=PROVIDER_ID,
            engine=self.engine_id,
            model=config.model or "deterministic-fixture",
            created_at=channel_store.now_iso(),
            source_asset_id="",
        )


class LocalTranscriptionProvider:
    provider_id = PROVIDER_ID
    display_name = "Local Transcription"
    capabilities = (
        "transcription.media",
        "transcription.local",
        "transcription.accepts.asset.video",
        "transcription.accepts.asset.audio",
        "transcription.produces.transcript.text",
        "transcription.produces.timeline.transcript",
        "transcript.text",
        "timeline.transcript",
        "canonical.text",
    )
    supported_input_types = ("asset.video", "asset.audio")
    contract = TransformationContract(
        id="transcription.media.local.v0",
        plugin_id=PROVIDER_ID,
        accepts=("asset.video", "asset.audio"),
        produces=("transcript.text", "timeline.transcript", "canonical.text"),
    )

    def __init__(
        self,
        config: Any = None,
        *,
        provider_config: LocalTranscriptionConfig | None = None,
        engine: TranscriptionEngine | None = None,
    ) -> None:
        self.config = provider_config or LocalTranscriptionConfig.from_app_config(config)
        self.engine = engine or WhisperLocalEngine()
        self._runs: dict[str, TranscriptResult] = {}

    def health_check(self) -> dict[str, Any]:
        available, code = self.engine.available(self.config)
        status = "ready" if available else code
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "status": status,
            "ready": available,
            "configured": available,
            "engine": self.config.engine if self.engine.engine_id != "deterministic_fixture" else self.engine.engine_id,
            "engine_id": self.engine.engine_id,
            "model": self.config.model or "not_configured",
            "device": self.config.device,
            "compute_type": self.config.compute_type,
            "language": self.config.language,
            "language_mode": "auto_detect" if self.config.language == "auto" else "hint",
            "supported_inputs": list(self.supported_input_types),
            "capabilities": list(self.capabilities),
            "processing": "Local" if available else "Local transcription unavailable",
            "reason": "" if available else code,
            "network_required": False,
            "model_autodownload": False,
            "automatic_start_on_upload": False,
            "contract_version": TRANSCRIPTION_CONTRACT_VERSION,
        }

    def transcribe(
        self,
        *,
        app_runtime,
        content_service,
        workspace_id: str,
        source_asset_id: str,
        language: str = "auto",
        model: str = "",
        force_new: bool = False,
        actor: str = "",
    ) -> TranscriptResult:
        source_asset = get_media_asset(source_asset_id)
        if source_asset is None:
            raise TranscriptionError("source_asset_not_found", "Source media asset was not found.")
        if source_asset.metadata.get("audio_present") is False:
            raise TranscriptionError("missing_audio", "No audio track detected.")
        source_kind = str(source_asset.metadata.get("asset_type") or source_asset.media_type or "")
        if (
            "video" not in source_kind
            and "audio" not in source_kind
            and source_asset.mime_type
            not in {
                "video/mp4",
                "audio/wav",
                "audio/mpeg",
                "audio/mp4",
            }
        ):
            raise TranscriptionError("unsupported_media", "Transcription supports managed video or audio assets.")

        run_config = self._run_config(language=language, model=model)
        duplicate_key = self._duplicate_key(source_asset, run_config)
        if not force_new:
            existing = self._existing_transcript(source_asset, duplicate_key)
            if existing is not None:
                return existing

        health = self.health_check()
        if not health.get("ready"):
            raise TranscriptionError(
                str(health.get("status") or "provider_not_configured"), "Local transcription unavailable."
            )

        graph = content_service.graph_service
        started_at = channel_store.now_iso()
        extracted_audio = self.extract_transcription_audio(
            app_runtime=app_runtime,
            source_asset=source_asset,
            workspace_id=workspace_id,
        )
        duration = self._asset_duration(source_asset)
        materialized = self._materialize_asset_to_path(app_runtime, extracted_audio)
        try:
            raw_result = self.engine.transcribe(materialized, config=run_config, source_duration=duration)
            completed_at = channel_store.now_iso()
            result = TranscriptResult(
                text=raw_result.text.strip(),
                language=raw_result.language,
                segments=raw_result.segments,
                duration=duration,
                provider_id=self.provider_id,
                engine=raw_result.engine,
                model=raw_result.model,
                created_at=completed_at,
                source_asset_id=source_asset.id,
                status="succeeded",
                audio_asset_id=extracted_audio.id,
                provenance={
                    "source_asset_id": source_asset.id,
                    "audio_asset_id": extracted_audio.id,
                    "provider_id": self.provider_id,
                    "provider_version": PROVIDER_VERSION,
                    "engine": raw_result.engine,
                    "model": raw_result.model,
                    "language": raw_result.language,
                    "transcription_started_at": started_at,
                    "transcription_completed_at": completed_at,
                    "duplicate_key": duplicate_key,
                    "actor": actor,
                },
            )
            self.validate_result(result, source_asset=source_asset)
            run = graph.record_transformation_run(
                workspace_id=workspace_id,
                transformation=self.contract,
                input_refs=(f"asset.{source_asset.id}", f"asset.{extracted_audio.id}"),
                output_refs=(f"transcript.{duplicate_key}",),
                configuration={
                    "language": run_config.language,
                    "model": run_config.model or "not_configured",
                    "engine": result.engine,
                    "force_new": force_new,
                },
                evidence=result.provenance | {"status": "succeeded"},
            )
            transcript_asset = AssetContract(
                asset_id=f"transcript_{uuid4().hex}",
                asset_type="asset.transcript.timeline",
                text=result.text,
                metadata={
                    "source_asset_id": source_asset.id,
                    "audio_asset_id": extracted_audio.id,
                    "language": result.language,
                    "duration": duration,
                    "segments": [asdict(segment) for segment in result.segments],
                    "timeline_segments_json": json.dumps([asdict(segment) for segment in result.timeline()]),
                    "original_transcript": result.text,
                    "canonical_edited_transcript": result.text,
                    "transcription_run_id": run.id,
                    "duplicate_key": duplicate_key,
                    "status": "succeeded",
                },
                provenance=ProvenanceRecord(
                    provider=self.provider_id,
                    plugin_id=self.provider_id,
                    actor_type="plugin",
                    actor_id=actor,
                    created_at=completed_at,
                    evidence=result.provenance,
                ),
            )
            final = TranscriptResult(
                **{
                    **asdict(result),
                    "segments": result.segments,
                    "transcript_asset": transcript_asset,
                    "canonical_text": result.text,
                    "run_id": run.id,
                }
            )
            self._record_success(source_asset, final, duplicate_key)
            graph.add_relationship(
                workspace_id=workspace_id,
                from_entity_id=f"asset.{source_asset.id}",
                relationship_type="extracted_audio_for",
                to_entity_id=f"asset.{extracted_audio.id}",
                metadata={"purpose": "transcription", "run_id": run.id},
                provenance={"actor_type": "plugin", "plugin_id": self.provider_id, "created_at": completed_at},
            )
            graph.add_relationship(
                workspace_id=workspace_id,
                from_entity_id=f"asset.{extracted_audio.id}",
                relationship_type="transcribed_to",
                to_entity_id=transcript_asset.asset_id,
                metadata={"run_id": run.id, "provider_id": self.provider_id},
                provenance={"actor_type": "plugin", "plugin_id": self.provider_id, "created_at": completed_at},
            )
            graph.add_relationship(
                workspace_id=workspace_id,
                from_entity_id=transcript_asset.asset_id,
                relationship_type="canonicalized_as",
                to_entity_id=f"canonical.{source_asset.id}",
                metadata={"canonical_text": result.text, "run_id": run.id},
                provenance={"actor_type": "plugin", "plugin_id": self.provider_id, "created_at": completed_at},
            )
            return final
        finally:
            materialized.unlink(missing_ok=True)

    def retranscribe(self, **kwargs: Any) -> TranscriptResult:
        kwargs["force_new"] = True
        return self.transcribe(**kwargs)

    def edit_canonical_transcript(
        self,
        *,
        source_asset_id: str,
        transcript_asset_id: str,
        edited_text: str,
        edited_by: str = "",
    ) -> dict[str, Any]:
        source_asset = get_media_asset(source_asset_id)
        if source_asset is None:
            raise TranscriptionError("source_asset_not_found", "Source media asset was not found.")
        text = edited_text.replace("\r\n", "\n").strip()
        if not text:
            raise TranscriptionError("canonical_transcript_empty", "Edited transcript cannot be empty.")
        transcripts = list(source_asset.metadata.get("transcripts") or [])
        matched = None
        for transcript in transcripts:
            if transcript.get("transcript_asset_id") == transcript_asset_id:
                matched = transcript
                break
        if matched is None:
            raise TranscriptionError("transcript_not_found", "Transcript artifact was not found.")
        matched["canonical_edited_transcript"] = text
        matched["canonical_changed"] = text != matched.get("original_transcript")
        matched["canonical_edited_at"] = channel_store.now_iso()
        matched["canonical_edited_by"] = edited_by
        source_asset.metadata["canonical_transcript"] = text
        source_asset.metadata["canonical_transcript_source"] = transcript_asset_id
        source_asset.metadata["transcript_status"] = "edited" if matched["canonical_changed"] else "succeeded"
        save_media_asset(source_asset)
        return matched

    def extract_transcription_audio(
        self,
        *,
        app_runtime,
        source_asset: MediaAsset,
        workspace_id: str,
    ) -> MediaAsset:
        if str(source_asset.mime_type).startswith("audio/"):
            return source_asset
        source_path = self._materialize_asset_to_path(app_runtime, source_asset)
        try:
            output_root = source_path.parent.parent / "transcription-audio"
            output_root.mkdir(parents=True, exist_ok=True)
            output_path = output_root / f"{uuid4().hex}.wav"
            ensure_managed_path(source_path, root=source_path.parent.parent)
            ensure_managed_path(output_path, root=source_path.parent.parent)
            run_ffmpeg(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(source_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-f",
                    "wav",
                    str(output_path),
                ],
                timeout=60,
            )
            return self._store_audio_asset(app_runtime, workspace_id, output_path, source_asset)
        except FFmpegBoundaryError as exc:
            raise TranscriptionError(
                "audio_extraction_failed", "Audio extraction failed safely.", {"stderr": exc.stderr}
            ) from exc
        finally:
            source_path.unlink(missing_ok=True)

    def validate_result(self, result: TranscriptResult, *, source_asset: MediaAsset) -> None:
        if not result.text.strip():
            raise TranscriptionError("provider_output_invalid", "Transcript text was empty.")
        if result.source_asset_id != source_asset.id:
            raise TranscriptionError("provider_output_invalid", "Transcript source linkage was invalid.")
        duration = self._asset_duration(source_asset) or result.duration
        previous_end = 0.0
        for segment in result.segments:
            if segment.start_time < 0 or segment.end_time <= segment.start_time or not segment.text.strip():
                raise TranscriptionError("provider_output_invalid", "Transcript segment timing/text was invalid.")
            if segment.start_time < previous_end:
                raise TranscriptionError("provider_output_invalid", "Transcript segments were not monotonic.")
            if duration and segment.end_time > duration + 2.0:
                raise TranscriptionError("provider_output_invalid", "Transcript segment exceeded source duration.")
            previous_end = segment.end_time

    def timeline_from_result(self, result: TranscriptResult) -> list[TimelineSegment]:
        self.validate_result(result, source_asset=get_media_asset(result.source_asset_id) or _stub_asset(result))
        return result.timeline()

    def _run_config(self, *, language: str, model: str) -> LocalTranscriptionConfig:
        return LocalTranscriptionConfig(
            engine=self.config.engine,
            model=model or self.config.model,
            device=self.config.device,
            compute_type=self.config.compute_type,
            language=language or self.config.language,
            deterministic_fixture_enabled=self.config.deterministic_fixture_enabled,
        )

    def _asset_duration(self, source_asset: MediaAsset) -> float:
        metadata = source_asset.metadata or {}
        video_metadata = metadata.get("video_metadata") if isinstance(metadata.get("video_metadata"), dict) else {}
        return float(
            metadata.get("duration") or video_metadata.get("duration") or source_asset.duration_ms / 1000 or 0.0
        )

    def _duplicate_key(self, source_asset: MediaAsset, config: LocalTranscriptionConfig) -> str:
        payload = {
            "source_asset_id": source_asset.id,
            "source_checksum": source_asset.checksum,
            "provider_id": self.provider_id,
            "engine": self.engine.engine_id,
            "model": config.model or "not_configured",
            "language": config.language,
        }
        return "transcription_" + json.dumps(payload, sort_keys=True).encode("utf-8").hex()[:40]

    def _existing_transcript(self, source_asset: MediaAsset, duplicate_key: str) -> TranscriptResult | None:
        for item in source_asset.metadata.get("transcripts") or []:
            if item.get("duplicate_key") != duplicate_key:
                continue
            segments = tuple(TranscriptSegment(**segment) for segment in item.get("segments", []))
            return TranscriptResult(
                text=str(item.get("original_transcript") or ""),
                language=str(item.get("language") or "und"),
                segments=segments,
                duration=float(item.get("duration") or 0.0),
                provider_id=str(item.get("provider_id") or self.provider_id),
                engine=str(item.get("engine") or self.engine.engine_id),
                model=str(item.get("model") or "not_configured"),
                created_at=str(item.get("created_at") or ""),
                source_asset_id=source_asset.id,
                status="succeeded",
                audio_asset_id=str(item.get("audio_asset_id") or ""),
                run_id=str(item.get("transcription_run_id") or ""),
                transcript_asset=AssetContract(
                    asset_id=str(item.get("transcript_asset_id")),
                    asset_type="asset.transcript.timeline",
                    text=str(item.get("original_transcript") or ""),
                    metadata=dict(item),
                    provenance=ProvenanceRecord(provider=self.provider_id, plugin_id=self.provider_id),
                ),
                canonical_text=str(item.get("canonical_edited_transcript") or item.get("original_transcript") or ""),
                provenance=dict(item.get("provenance") or {}),
            )
        return None

    def _record_success(self, source_asset: MediaAsset, result: TranscriptResult, duplicate_key: str) -> None:
        transcripts = list(source_asset.metadata.get("transcripts") or [])
        transcript_asset_id = (
            result.transcript_asset.asset_id if result.transcript_asset else f"transcript_{uuid4().hex}"
        )
        transcripts.append(
            {
                "transcript_asset_id": transcript_asset_id,
                "transcription_run_id": result.run_id,
                "duplicate_key": duplicate_key,
                "provider_id": result.provider_id,
                "provider_version": result.provider_version,
                "engine": result.engine,
                "model": result.model,
                "language": result.language,
                "created_at": result.created_at,
                "duration": result.duration,
                "audio_asset_id": result.audio_asset_id,
                "segments": [asdict(segment) for segment in result.segments],
                "original_transcript": result.text,
                "canonical_edited_transcript": result.canonical_text or result.text,
                "canonical_changed": False,
                "provenance": dict(result.provenance),
                "status": "succeeded",
            }
        )
        source_asset.metadata["transcripts"] = transcripts
        source_asset.metadata["transcript_status"] = "succeeded"
        source_asset.metadata["original_transcript"] = result.text
        source_asset.metadata["canonical_transcript"] = result.canonical_text or result.text
        source_asset.metadata["timeline_transcript"] = [asdict(segment) for segment in result.timeline()]
        source_asset.metadata["transcription_provider_id"] = self.provider_id
        source_asset.metadata["transcription_run_id"] = result.run_id
        save_media_asset(source_asset)

    def _materialize_asset_to_path(self, app_runtime, asset: MediaAsset) -> Path:
        provider = app_runtime.media_provider(preferred_provider_id=asset.storage_provider_id)
        tmp_root = Path(tempfile.mkdtemp(prefix="transcription-media-", dir=str(channel_store.STUDIO_DATA_DIR)))
        suffix = Path(asset.original_filename or "").suffix or ".bin"
        target = tmp_root / f"{asset.id}{suffix}"
        with target.open("wb") as handle:
            for chunk in provider.open_stream(asset.storage_reference):
                handle.write(chunk)
        ensure_managed_path(target, root=tmp_root)
        return target

    def _store_audio_asset(
        self,
        app_runtime,
        workspace_id: str,
        output_path: Path,
        source_asset: MediaAsset,
    ) -> MediaAsset:
        stored = app_runtime.media_provider().store(
            MediaInput(
                local_path=output_path,
                original_filename=output_path.name,
                declared_mime_type="audio/wav",
                source_type=MediaSourceType.GENERATED.value,
                source_reference=source_asset.id,
            ),
            MediaStoreOptions(
                workspace_id=workspace_id,
                purpose="transcription.audio_extract",
                allowed_mime_types=("audio/wav",),
                maximum_size=100_000_000,
            ),
        )
        now = channel_store.now_iso()
        resolved_media_type = media_type_for_mime(stored.mime_type)
        asset = MediaAsset(
            id=f"media_{uuid4().hex}",
            workspace_id=workspace_id,
            original_filename=output_path.name,
            display_name=output_path.name,
            storage_provider_id=stored.provider_id,
            storage_reference=stored.storage_reference,
            mime_type=stored.mime_type,
            media_type=getattr(resolved_media_type, "value", resolved_media_type),
            file_size=stored.file_size,
            checksum_algorithm="sha256",
            checksum=stored.checksum,
            source_type=MediaSourceType.GENERATED.value,
            source_reference=source_asset.id,
            status=MediaStatus.AVAILABLE.value,
            created_at=now,
            updated_at=now,
            metadata={
                "asset_type": "audio",
                "purpose": "transcription",
                "source_asset_id": source_asset.id,
                "sample_rate": 16000,
                "channels": 1,
            },
        )
        output_path.unlink(missing_ok=True)
        return save_media_asset(asset)


def _stub_asset(result: TranscriptResult) -> MediaAsset:
    return MediaAsset(
        id=result.source_asset_id,
        workspace_id="",
        original_filename="",
        storage_provider_id="",
        storage_reference="",
        mime_type="video/mp4",
        media_type="video",
        file_size=1,
        checksum="",
        metadata={"duration": result.duration},
    )
