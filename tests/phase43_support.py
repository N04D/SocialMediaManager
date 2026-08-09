from __future__ import annotations

from typing import Any

from src.core.runtime.capabilities import CapabilityDescriptor, CapabilityMode
from src.core.runtime.components import ComponentManifest
from src.core.runtime.deployments import PlaybookDeployment, RequirementBinding
from src.core.runtime.events import EventEnvelope, EventSource
from src.core.runtime.installs import ComponentBinding, Install
from src.core.runtime.plans import ExecutionPlan, compile_execution_plan
from src.core.runtime.playbooks import (
    CapabilityRequirement,
    PlaybookDefinition,
    PlaybookEdge,
    PlaybookNode,
)
from src.core.runtime.resolver import RuntimeRegistry


def capability(capability_id: str, mode: str = CapabilityMode.WRITE.value) -> CapabilityDescriptor:
    return CapabilityDescriptor(capability_id=capability_id, version="1.0.0", mode=mode)


def component(component_id: str, *capability_ids: str) -> ComponentManifest:
    return ComponentManifest(
        component_id=component_id,
        provider="test",
        version="1.0.0",
        sdk_version="phase43",
        capabilities=tuple(capability(item) for item in capability_ids),
    )


def phase43_registry() -> RuntimeRegistry:
    registry = RuntimeRegistry()
    for manifest in (
        component("test-echo-component", "test.echo"),
        component("test-echo-alt-component", "test.echo"),
        component("test-text-component", "test.text.uppercase"),
        component("test-counter-component", "test.counter.increment"),
        component("test-wait-component", "test.wait"),
        component("test-flaky-component", "test.flaky"),
    ):
        registry.register_component(manifest)
    registry.register_install(
        Install(
            install_id="test-install",
            workspace_id="workspace-test",
            provider="test",
            account_ref="test-account",
            component_bindings={
                "test.echo": ComponentBinding("test-echo-component"),
                "test.text.uppercase": ComponentBinding("test-text-component"),
                "test.counter.increment": ComponentBinding("test-counter-component"),
                "test.wait": ComponentBinding("test-wait-component"),
                "test.flaky": ComponentBinding("test-flaky-component"),
            },
            secret_refs=("test-secret-ref",),
        )
    )
    registry.register_install(
        Install(
            install_id="test-install-alt",
            workspace_id="workspace-test",
            provider="test",
            account_ref="test-account-alt",
            component_bindings={"test.echo": ComponentBinding("test-echo-alt-component")},
            secret_refs=("test-secret-ref-alt",),
        )
    )
    return registry


def phase43_deployment(install_id: str = "test-install") -> PlaybookDeployment:
    return PlaybookDeployment(
        deployment_id=f"deployment-{install_id.replace('_', '-')}",
        playbook_id="test.phase43.reference",
        playbook_version="1.0.0",
        workspace_id="workspace-test",
        requirement_bindings={
            "echoer": RequirementBinding(install_id),
            "text": RequirementBinding("test-install"),
            "waiter": RequirementBinding("test-install"),
            "flaky": RequirementBinding("test-install"),
        },
    )


def reference_playbook(*, echo_capability: str = "test.echo") -> PlaybookDefinition:
    return PlaybookDefinition(
        playbook_id="test.phase43.reference",
        version="1.0.0",
        schema_version="1.0",
        name="Phase 43 Reference",
        requirements={
            "echoer": CapabilityRequirement((echo_capability,)),
        },
        nodes=(
            PlaybookNode("trigger", "trigger", {"event_type": "test.input.received"}),
            PlaybookNode(
                "uppercase",
                "transform",
                {
                    "transformer": "uppercase",
                    "field": "text",
                    "input": {"text": {"from_event": "payload", "path": "text"}},
                },
            ),
            PlaybookNode(
                "is-hello",
                "condition",
                {
                    "left": {"from_node": "uppercase", "path": "text"},
                    "operator": "equals",
                    "right": {"literal": "HELLO"},
                },
            ),
            PlaybookNode(
                "echo",
                "capability",
                {
                    "requirement": "echoer",
                    "capability": echo_capability,
                    "input": {"value": {"from_node": "uppercase", "path": "text"}},
                },
            ),
        ),
        edges=(
            PlaybookEdge("trigger", "uppercase"),
            PlaybookEdge("uppercase", "is-hello"),
            PlaybookEdge("is-hello", "echo", condition="true"),
        ),
    )


def compile_reference_plan(install_id: str = "test-install") -> ExecutionPlan:
    return compile_execution_plan(reference_playbook(), phase43_deployment(install_id), phase43_registry())


def event(payload: dict[str, Any] | None = None, *, idempotency_key: str = "event-1") -> EventEnvelope:
    return EventEnvelope(
        event_type="test.input.received",
        source=EventSource(component="test-source", provider="test"),
        workspace_id="workspace-test",
        correlation_id="corr-1",
        trace_id="trace-1",
        idempotency_key=idempotency_key,
        payload=payload or {"text": "hello"},
    )
