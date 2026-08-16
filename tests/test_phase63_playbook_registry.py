from __future__ import annotations

import pytest

from src.core.runtime import (
    PlaybookDefinitionRecord,
    PlaybookRegistry,
    PlaybookRegistryStatus,
    PlaybookValidationError,
)


def playbook(
    playbook_id: str = "content.performance.observe",
    version: str = "1.0.0",
    *,
    status: str = PlaybookRegistryStatus.ACTIVE.value,
    scope: str = "content.performance",
    capability_requirements: dict | None = None,
    context_contract: dict | None = None,
    mutation_policy: dict | None = None,
    raw_access_policy: dict | None = None,
    provenance: dict | None = None,
) -> PlaybookDefinitionRecord:
    return PlaybookDefinitionRecord.from_dict(
        {
            "playbook_id": playbook_id,
            "version": version,
            "name": f"{playbook_id} {version}",
            "description": "Read-only context registry fixture",
            "status": status,
            "scope": scope,
            "input_contract": {
                "content_entity_id": "required",
                "external_ref": "optional",
                "provider": "optional",
                "install_id": "optional",
                "intent_label": "optional",
            },
            "context_contract": context_contract
            or {
                "schema_version": "content-performance-context.v1",
                "requires_transcript": False,
                "requires_publications": True,
                "requires_metrics_history": True,
            },
            "capability_requirements": capability_requirements
            or {"read": ["content.performance.context.read"], "optional": [], "mutations": []},
            "mutation_policy": mutation_policy or {"allowed": False, "allowed_capabilities": []},
            "raw_access_policy": raw_access_policy
            or {"raw_metrics": False, "raw_transcript": False, "provider_payloads": False, "secrets": False},
            "steps": [{"step_id": "read-context", "kind": "read"}],
            "provenance": provenance or {"definition_source": "test-fixture", "intent": "content.performance"},
            "created_at": "2026-08-16T00:00:00Z",
            "updated_at": "2026-08-16T00:00:00Z",
        }
    )


def test_register_one_and_multiple_playbooks_without_overwriting_versions():
    registry = PlaybookRegistry()

    first = registry.register(playbook(version="1.0.0"))
    second = registry.register(playbook(version="1.1.0"))
    other = registry.register(playbook(playbook_id="content.performance.audit", version="1.0.0"))

    assert first.ok is True
    assert second.ok is True
    assert other.ok is True
    assert registry.get("content.performance.observe", "1.0.0") is not None
    assert registry.get("content.performance.observe", "1.1.0") is not None
    assert len(registry.list(scope="content.performance")) == 3


def test_active_deprecated_disabled_and_invalid_states_are_stored_side_by_side():
    registry = PlaybookRegistry()
    registry.register(playbook(version="1.0.0", status=PlaybookRegistryStatus.DEPRECATED.value))
    registry.register(playbook(version="1.1.0", status=PlaybookRegistryStatus.ACTIVE.value))
    registry.register(playbook(version="1.2.0", status=PlaybookRegistryStatus.DISABLED.value))
    registry.register(playbook(version="1.3.0", status=PlaybookRegistryStatus.INVALID.value))

    assert [item.version for item in registry.list()] == ["1.0.0", "1.1.0", "1.2.0", "1.3.0"]
    assert [item.version for item in registry.list(status=PlaybookRegistryStatus.ACTIVE.value)] == ["1.1.0"]


def test_validation_missing_required_fields_and_unsupported_context_schema_invalid():
    with pytest.raises(PlaybookValidationError):
        PlaybookDefinitionRecord.from_dict({"playbook_id": "content.performance.bad", "version": "1.0.0"})

    with pytest.raises(PlaybookValidationError) as error:
        playbook(context_contract={"schema_version": "future-context.v9"})

    assert error.value.code == "playbook_registry.context_schema_unsupported"


def test_unavailable_capability_and_default_mutation_rejection():
    registry = PlaybookRegistry()

    missing_capability = registry.register(
        playbook(capability_requirements={"read": ["content.performance.context.read", "missing.capability.read"]})
    )
    mutation = registry.register(
        playbook(
            playbook_id="content.performance.publish",
            capability_requirements={"read": ["content.performance.context.read"], "mutations": ["website.article.publish"]},
            mutation_policy={"allowed": False, "allowed_capabilities": []},
        )
    )

    assert missing_capability.ok is False
    assert missing_capability.error_code == "CAPABILITY_NOT_AVAILABLE"
    assert mutation.ok is False
    assert mutation.error_code == "MUTATION_NOT_ALLOWED"
    assert registry.get("content.performance.publish", "1.0.0").status == PlaybookRegistryStatus.INVALID.value


def test_definition_output_rejects_secret_canaries():
    with pytest.raises(PlaybookValidationError) as error:
        playbook(provenance={"definition_source": "fixture", "token": "SECRET_CANARY"})

    assert error.value.code == "playbook_registry.definition_secret"
