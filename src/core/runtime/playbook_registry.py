from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .errors import PlaybookValidationError
from .identifiers import validate_namespaced_id
from .playbooks import _contains_forbidden_key

_ALLOWED_CONTRACT_KEYS = {
    "content_entity_id",
    "external_ref",
    "install_id",
    "provider",
    "target_channel",
    "time_window",
}
_BLOCKED_SECRET_KEYS = {
    "api_key",
    "authorization",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "refresh_token",
    "secret",
    "secret_ref",
    "secret_refs",
    "token",
}

PLAYBOOK_REGISTRY_SCHEMA_VERSION = "playbook-registry.v1"
SUPPORTED_CONTEXT_SCHEMAS = {"content-performance-context.v1"}


class PlaybookRegistryStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"
    INVALID = "invalid"


@dataclass(frozen=True)
class PlaybookInputContract:
    content_entity_id: str = "optional"
    external_ref: str = "optional"
    provider: str = "optional"
    install_id: str = "optional"
    time_window: str = "optional"
    target_channel: str = "optional"
    intent_label: str = "optional"
    allowed_inputs: tuple[str, ...] = field(default_factory=tuple)
    forbidden_inputs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for field_name in (
            "content_entity_id",
            "external_ref",
            "provider",
            "install_id",
            "time_window",
            "target_channel",
            "intent_label",
        ):
            value = getattr(self, field_name)
            if value not in {"optional", "required", "forbidden"}:
                raise PlaybookValidationError(
                    "playbook_registry.input_contract_invalid",
                    "Input contract fields must be optional, required, or forbidden.",
                    {"field": field_name, "value": value},
                )
        normalized_allowed = tuple(sorted(str(item) for item in self.allowed_inputs))
        normalized_forbidden = tuple(sorted(str(item) for item in self.forbidden_inputs))
        if _contains_forbidden_key({"allowed_inputs": normalized_allowed, "forbidden_inputs": normalized_forbidden}):
            raise PlaybookValidationError(
                "playbook_registry.input_contract_secret",
                "Playbook inputs must not expose secrets, tokens, or environment-specific values.",
            )
        object.__setattr__(self, "allowed_inputs", normalized_allowed)
        object.__setattr__(self, "forbidden_inputs", normalized_forbidden)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlaybookInputContract:
        return cls(
            content_entity_id=str(payload.get("content_entity_id") or "optional"),
            external_ref=str(payload.get("external_ref") or "optional"),
            provider=str(payload.get("provider") or "optional"),
            install_id=str(payload.get("install_id") or "optional"),
            time_window=str(payload.get("time_window") or "optional"),
            target_channel=str(payload.get("target_channel") or "optional"),
            intent_label=str(payload.get("intent_label") or "optional"),
            allowed_inputs=tuple(str(item) for item in payload.get("allowed_inputs", [])),
            forbidden_inputs=tuple(str(item) for item in payload.get("forbidden_inputs", [])),
        )


@dataclass(frozen=True)
class PlaybookContextContract:
    schema_version: str = "content-performance-context.v1"
    requires_transcript: bool = False
    requires_publications: bool = False
    requires_metrics_history: bool = False
    raw_metrics_required: bool = False
    raw_transcript_required: bool = False

    def __post_init__(self) -> None:
        if self.schema_version not in SUPPORTED_CONTEXT_SCHEMAS:
            raise PlaybookValidationError(
                "playbook_registry.context_schema_unsupported",
                "Playbook context schema is not supported.",
                {"schema_version": self.schema_version},
            )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlaybookContextContract:
        return cls(
            schema_version=str(payload.get("schema_version") or "content-performance-context.v1"),
            requires_transcript=bool(payload.get("requires_transcript", False)),
            requires_publications=bool(payload.get("requires_publications", False)),
            requires_metrics_history=bool(payload.get("requires_metrics_history", False)),
            raw_metrics_required=bool(payload.get("raw_metrics_required", False)),
            raw_transcript_required=bool(payload.get("raw_transcript_required", False)),
        )


@dataclass(frozen=True)
class CapabilityRequirements:
    read: tuple[str, ...] = ("content.performance.context.read",)
    optional: tuple[str, ...] = field(default_factory=tuple)
    mutations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "read", _normalized_capabilities(self.read))
        object.__setattr__(self, "optional", _normalized_capabilities(self.optional))
        object.__setattr__(self, "mutations", _normalized_capabilities(self.mutations))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CapabilityRequirements:
        return cls(
            read=tuple(str(item) for item in payload.get("read", ("content.performance.context.read",))),
            optional=tuple(str(item) for item in payload.get("optional", ())),
            mutations=tuple(str(item) for item in payload.get("mutations", ())),
        )


@dataclass(frozen=True)
class MutationPolicy:
    allowed: bool = False
    allowed_capabilities: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_capabilities", _normalized_capabilities(self.allowed_capabilities))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MutationPolicy:
        return cls(
            allowed=bool(payload.get("allowed", False)),
            allowed_capabilities=tuple(str(item) for item in payload.get("allowed_capabilities", ())),
        )


@dataclass(frozen=True)
class RawAccessPolicy:
    raw_metrics: bool = False
    raw_transcript: bool = False
    provider_payloads: bool = False
    secrets: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RawAccessPolicy:
        return cls(
            raw_metrics=bool(payload.get("raw_metrics", False)),
            raw_transcript=bool(payload.get("raw_transcript", False)),
            provider_payloads=bool(payload.get("provider_payloads", False)),
            secrets=bool(payload.get("secrets", False)),
        )


@dataclass(frozen=True)
class PlaybookDefinitionRecord:
    playbook_id: str
    version: str
    name: str
    description: str = ""
    status: str = PlaybookRegistryStatus.DRAFT.value
    scope: str = "content.performance"
    input_contract: PlaybookInputContract = field(default_factory=PlaybookInputContract)
    context_contract: PlaybookContextContract = field(default_factory=PlaybookContextContract)
    capability_requirements: CapabilityRequirements = field(default_factory=CapabilityRequirements)
    mutation_policy: MutationPolicy = field(default_factory=MutationPolicy)
    raw_access_policy: RawAccessPolicy = field(default_factory=RawAccessPolicy)
    steps: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "playbook_id", validate_namespaced_id(self.playbook_id, field_name="playbook_id"))
        if not str(self.version or "").strip():
            raise PlaybookValidationError("playbook_registry.version_required", "Playbook version is required.")
        if not str(self.name or "").strip():
            raise PlaybookValidationError("playbook_registry.name_required", "Playbook name is required.")
        status = PlaybookRegistryStatus(str(self.status)).value
        object.__setattr__(self, "status", status)
        if _contains_registry_secret(asdict(self)):
            raise PlaybookValidationError(
                "playbook_registry.definition_secret",
                "Playbook registry definitions must not contain secrets or environment-specific values.",
            )
        object.__setattr__(self, "steps", tuple(_json_safe(item) for item in self.steps))
        object.__setattr__(self, "provenance", _json_safe(self.provenance))

    def key(self) -> tuple[str, str]:
        return self.playbook_id, self.version

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlaybookDefinitionRecord:
        return cls(
            playbook_id=str(payload.get("playbook_id") or ""),
            version=str(payload.get("version") or ""),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            status=str(payload.get("status") or PlaybookRegistryStatus.DRAFT.value),
            scope=str(payload.get("scope") or "content.performance"),
            input_contract=PlaybookInputContract.from_dict(dict(payload.get("input_contract") or {})),
            context_contract=PlaybookContextContract.from_dict(dict(payload.get("context_contract") or {})),
            capability_requirements=CapabilityRequirements.from_dict(dict(payload.get("capability_requirements") or {})),
            mutation_policy=MutationPolicy.from_dict(dict(payload.get("mutation_policy") or {})),
            raw_access_policy=RawAccessPolicy.from_dict(dict(payload.get("raw_access_policy") or {})),
            steps=tuple(dict(item) for item in payload.get("steps", ()) if isinstance(item, dict)),
            provenance=dict(payload.get("provenance") or {}),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class PlaybookValidationResult:
    ok: bool
    status: str
    error_code: str = ""
    message: str = ""
    capability_validation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlaybookSelectionPolicy:
    allow_deprecated: bool = False
    allow_mutations: bool = False
    allow_raw_metrics: bool = False
    allow_raw_transcript: bool = False
    select_highest_version: bool = True
    available_capabilities: frozenset[str] = frozenset({"content.performance.context.read"})


@dataclass(frozen=True)
class PlaybookSelectionResult:
    selected: tuple[PlaybookDefinitionRecord, ...]
    rejected: tuple[dict[str, Any], ...]
    selected_by: dict[str, Any]

    @property
    def first(self) -> PlaybookDefinitionRecord | None:
        return self.selected[0] if self.selected else None


@dataclass
class PlaybookRegistry:
    available_capabilities: set[str] = field(default_factory=lambda: {"content.performance.context.read"})
    definitions: dict[tuple[str, str], PlaybookDefinitionRecord] = field(default_factory=dict)

    def register(self, definition: PlaybookDefinitionRecord | dict[str, Any]) -> PlaybookValidationResult:
        record = definition if isinstance(definition, PlaybookDefinitionRecord) else PlaybookDefinitionRecord.from_dict(definition)
        result = self.validate(record)
        record_to_store = record
        if not result.ok and record.status != PlaybookRegistryStatus.INVALID.value:
            record_to_store = PlaybookDefinitionRecord(
                **{
                    **record.__dict__,
                    "status": PlaybookRegistryStatus.INVALID.value,
                    "provenance": {
                        **record.provenance,
                        "validation_result": result.error_code,
                    },
                }
            )
        self.definitions[record_to_store.key()] = record_to_store
        return result

    def validate(self, definition: PlaybookDefinitionRecord) -> PlaybookValidationResult:
        required = set(definition.capability_requirements.read)
        missing = sorted(required - set(self.available_capabilities))
        if missing:
            return PlaybookValidationResult(
                ok=False,
                status=PlaybookRegistryStatus.INVALID.value,
                error_code="CAPABILITY_NOT_AVAILABLE",
                message="Required read capability is not available.",
                capability_validation={"missing": missing},
            )
        if definition.capability_requirements.mutations and not definition.mutation_policy.allowed:
            return PlaybookValidationResult(
                ok=False,
                status=PlaybookRegistryStatus.INVALID.value,
                error_code="MUTATION_NOT_ALLOWED",
                message="Mutation requirements are rejected by the default registry policy.",
                capability_validation={"mutations": list(definition.capability_requirements.mutations)},
            )
        if definition.raw_access_policy.secrets:
            return PlaybookValidationResult(
                ok=False,
                status=PlaybookRegistryStatus.INVALID.value,
                error_code="SECRET_RAW_ACCESS_FORBIDDEN",
                message="Playbooks may never request secret raw access.",
            )
        return PlaybookValidationResult(
            ok=definition.status != PlaybookRegistryStatus.INVALID.value,
            status=definition.status,
            capability_validation={"missing": [], "read": list(definition.capability_requirements.read)},
        )

    def get(self, playbook_id: str, version: str) -> PlaybookDefinitionRecord | None:
        return self.definitions.get((playbook_id, version))

    def list(self, *, status: str | None = None, scope: str | None = None) -> tuple[PlaybookDefinitionRecord, ...]:
        return tuple(
            sorted(
                (
                    definition
                    for definition in self.definitions.values()
                    if (status is None or definition.status == status) and (scope is None or definition.scope == scope)
                ),
                key=lambda item: (item.scope, item.playbook_id, _version_key(item.version), item.version),
            )
        )

    def select_for_context(
        self,
        context: dict[str, Any],
        *,
        intent: str | None = None,
        policy: PlaybookSelectionPolicy | None = None,
    ) -> PlaybookSelectionResult:
        selection_policy = policy or PlaybookSelectionPolicy(available_capabilities=frozenset(self.available_capabilities))
        selected: list[PlaybookDefinitionRecord] = []
        rejected: list[dict[str, Any]] = []
        for definition in self.list():
            reason = self._selection_rejection_reason(definition, context, intent=intent, policy=selection_policy)
            if reason:
                rejected.append({"playbook_id": definition.playbook_id, "version": definition.version, "reason": reason})
            else:
                selected.append(definition)
        selected = _dedupe_versions(selected, selection_policy)
        return PlaybookSelectionResult(
            selected=tuple(selected),
            rejected=tuple(sorted(rejected, key=lambda item: (item["playbook_id"], item["version"], item["reason"]))),
            selected_by={
                "policy": {
                    "allow_deprecated": selection_policy.allow_deprecated,
                    "allow_mutations": selection_policy.allow_mutations,
                    "allow_raw_metrics": selection_policy.allow_raw_metrics,
                    "allow_raw_transcript": selection_policy.allow_raw_transcript,
                    "select_highest_version": selection_policy.select_highest_version,
                },
                "context_schema_version": str(context.get("schema_version") or ""),
            },
        )

    def resolve_context_requirements(self, playbook_id: str, version: str) -> dict[str, Any]:
        definition = self.get(playbook_id, version)
        if definition is None:
            raise PlaybookValidationError(
                "playbook_registry.not_found",
                "Playbook definition was not found.",
                {"playbook_id": playbook_id, "version": version},
            )
        return asdict(definition.context_contract)

    def _selection_rejection_reason(
        self,
        definition: PlaybookDefinitionRecord,
        context: dict[str, Any],
        *,
        intent: str | None,
        policy: PlaybookSelectionPolicy,
    ) -> str:
        if definition.status in {PlaybookRegistryStatus.DISABLED.value, PlaybookRegistryStatus.INVALID.value}:
            return definition.status
        if definition.status == PlaybookRegistryStatus.DEPRECATED.value and not policy.allow_deprecated:
            return "deprecated"
        if intent and definition.input_contract.intent_label == "required":
            declared = str(definition.provenance.get("intent") or definition.scope)
            if declared != intent:
                return "intent_mismatch"
        if definition.context_contract.schema_version != str(context.get("schema_version") or ""):
            return "context_schema_mismatch"
        if definition.context_contract.requires_transcript and not _context_transcript_available(context):
            return "transcript_required"
        if definition.context_contract.requires_publications and not context.get("publications"):
            return "publication_required"
        if definition.context_contract.requires_metrics_history and not _context_has_metrics(context):
            return "metrics_required"
        missing = sorted(set(definition.capability_requirements.read) - set(policy.available_capabilities))
        if missing:
            return "capability_not_available"
        if definition.capability_requirements.mutations and not policy.allow_mutations:
            return "mutation_not_allowed"
        if definition.raw_access_policy.raw_metrics and not policy.allow_raw_metrics:
            return "raw_metrics_not_allowed"
        if definition.raw_access_policy.raw_transcript and not policy.allow_raw_transcript:
            return "raw_transcript_not_allowed"
        if definition.raw_access_policy.provider_payloads and not policy.allow_raw_metrics:
            return "provider_payloads_not_allowed"
        if definition.raw_access_policy.secrets:
            return "secrets_not_allowed"
        return ""


def _normalized_capabilities(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(validate_namespaced_id(str(item), field_name="capability") for item in values if str(item)))


def _contains_registry_secret(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered not in _ALLOWED_CONTRACT_KEYS and lowered in _BLOCKED_SECRET_KEYS and bool(child):
                return True
            if _contains_registry_secret(child):
                return True
    if isinstance(value, list | tuple):
        return any(_contains_registry_secret(item) for item in value)
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return True
    return False


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))


def _version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in str(version).replace("-", ".").split("."):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(0)
    return tuple(parts)


def _dedupe_versions(
    selected: list[PlaybookDefinitionRecord], policy: PlaybookSelectionPolicy
) -> list[PlaybookDefinitionRecord]:
    ordered = sorted(
        selected,
        key=lambda item: (
            item.scope,
            item.playbook_id,
            _version_key(item.version),
            item.version,
        ),
        reverse=policy.select_highest_version,
    )
    if not policy.select_highest_version:
        return ordered
    winners: dict[tuple[str, str], PlaybookDefinitionRecord] = {}
    for item in ordered:
        winners.setdefault((item.scope, item.playbook_id), item)
    return sorted(winners.values(), key=lambda item: (item.scope, item.playbook_id, _version_key(item.version), item.version))


def _context_transcript_available(context: dict[str, Any]) -> bool:
    transcript = context.get("transcript_state") or context.get("transcript") or {}
    return bool(transcript.get("available"))


def _context_has_metrics(context: dict[str, Any]) -> bool:
    freshness = context.get("freshness") or {}
    if freshness.get("metrics_present"):
        return True
    for publication in context.get("publications", ()):
        if publication.get("metrics_history") or publication.get("metrics"):
            return True
    return False
