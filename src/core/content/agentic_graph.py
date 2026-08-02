from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProvenanceActorType(StrEnum):
    MANUAL = "manual"
    AGENT = "agent"
    RULE = "rule"
    PLUGIN = "plugin"
    IMPORT = "import"


@dataclass(frozen=True)
class ProvenanceRecord:
    provider: str = ""
    plugin_id: str = ""
    actor_type: str = ProvenanceActorType.MANUAL.value
    actor_id: str = ""
    created_at: str = ""
    original_ref: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Entity:
    id: str
    entity_type: str
    source_plugin: str = ""
    external_ref: str = ""
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class SourceDescriptor:
    source_type: str
    entity_id: str = ""
    source_plugin: str = ""
    ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)


@dataclass(frozen=True)
class TimelineSegment:
    start_time: float
    end_time: float
    text: str
    speaker: str = ""
    semantic_topic: str = ""
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalRepresentation:
    text: str = ""
    media_refs: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: tuple[ProvenanceRecord, ...] = field(default_factory=tuple)
    timeline: tuple[TimelineSegment, ...] = field(default_factory=tuple)
    representation_id: str = ""


@dataclass
class Relationship:
    id: str
    workspace_id: str
    from_entity_id: str
    relationship_type: str
    to_entity_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    created_at: str = ""


@dataclass(frozen=True)
class AssetContract:
    asset_id: str
    asset_type: str
    media_asset_id: str = ""
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)


@dataclass(frozen=True)
class TransformationContract:
    id: str
    plugin_id: str
    accepts: tuple[str, ...]
    produces: tuple[str, ...]
    configuration_schema: dict[str, Any] = field(default_factory=dict)
    evidence_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransformationRun:
    id: str
    workspace_id: str
    transformation_id: str
    plugin_id: str
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...] = field(default_factory=tuple)
    configuration: dict[str, Any] = field(default_factory=dict)
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    created_at: str = ""


@dataclass(frozen=True)
class Intent:
    id: str
    name: str
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass
class Campaign:
    id: str
    workspace_id: str
    intent_id: str
    name: str = ""
    source_entity_ids: tuple[str, ...] = field(default_factory=tuple)
    selected_plugin_ids: tuple[str, ...] = field(default_factory=tuple)
    transformation_run_ids: tuple[str, ...] = field(default_factory=tuple)
    variant_ids: tuple[str, ...] = field(default_factory=tuple)
    publication_ids: tuple[str, ...] = field(default_factory=tuple)
    outcome_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Outcome:
    id: str
    workspace_id: str
    outcome_type: str
    subject_entity_id: str = ""
    source_ref: str = ""
    value: float | None = None
    currency: str = ""
    status: str = "observed"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(frozen=True)
class Playbook:
    id: str
    name: str
    intent_id: str
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...] = field(default_factory=tuple)
    workflow_stages: tuple[str, ...] = field(default_factory=tuple)
    policies: tuple[str, ...] = field(default_factory=tuple)
    success_metrics: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PolicyRule:
    id: str
    description: str
    effect: str = "deny"
    conditions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClipCandidate:
    start: float
    end: float
    transcript_excerpt: str
    score: float
    reason: str
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
