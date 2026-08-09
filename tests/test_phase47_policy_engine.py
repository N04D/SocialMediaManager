from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from runtime_foundation_mappings import phase41_runtime_registry
from src.core.runtime import (
    CapabilityDescriptor,
    CapabilityMode,
    ComponentBinding,
    ComponentManifest,
    DeploymentPolicy,
    EventEnvelope,
    EventSource,
    ExecutionContext,
    Install,
    InstallGrants,
    PlaybookDeployment,
    PolicyReasonCode,
    RequirementBinding,
    RuntimePolicyEngine,
    RuntimeRegistry,
    capability_report,
    validate_deployment,
)
from src.core.runtime.deployments import DeploymentValidationError
from src.core.runtime.plans import ExecutionPlanNode


def policy_context(deployment_id: str = "deploy") -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-policy",
        deployment_id=deployment_id,
        trigger_event=EventEnvelope(
            event_type="policy.test",
            source=EventSource(component="policy-test", provider="runtime"),
        ),
    )


def policy_node(capability: str = "test.data.read", component: str = "test-component") -> ExecutionPlanNode:
    return ExecutionPlanNode(
        node_id="read",
        kind="capability",
        requirement="resource",
        capability=capability,
        install_id="install",
        component_id=component,
        provider="test",
    )


def registry_for(
    *,
    capability: CapabilityDescriptor | None = None,
    component_permissions: dict | None = None,
    grants: InstallGrants | None = None,
    install_enabled: bool = True,
) -> RuntimeRegistry:
    capability = capability or CapabilityDescriptor("test.data.read", "0.1.0", CapabilityMode.READ.value)
    registry = RuntimeRegistry()
    registry.register_component(
        ComponentManifest(
            component_id="test-component",
            provider="test",
            version="0.1.0",
            sdk_version="runtime-contracts-0.1",
            capabilities=(capability,),
            permissions=component_permissions or {},
        )
    )
    registry.register_install(
        Install(
            install_id="install",
            workspace_id="workspace",
            provider="test",
            account_ref="account",
            component_bindings={capability.capability_id: ComponentBinding("test-component")},
            secret_refs=("secretref:test",),
            enabled=install_enabled,
            grants=grants or InstallGrants(allowed_capabilities=(capability.capability_id,)),
        )
    )
    return registry


def deployment(policy: DeploymentPolicy | None = None, *, enabled: bool = True) -> PlaybookDeployment:
    return PlaybookDeployment(
        deployment_id="deploy",
        playbook_id="policy.playbook",
        playbook_version="1.0.0",
        workspace_id="workspace",
        requirement_bindings={"resource": RequirementBinding("install")},
        enabled=enabled,
        policy=policy or DeploymentPolicy(),
    )


def engine(registry: RuntimeRegistry, deploy: PlaybookDeployment | None = None) -> RuntimePolicyEngine:
    deploy = deploy or deployment()
    return RuntimePolicyEngine(registry=registry, deployments={deploy.deployment_id: deploy})


def evaluate(
    registry: RuntimeRegistry, deploy: PlaybookDeployment | None = None, node: ExecutionPlanNode | None = None
):
    return engine(registry, deploy).evaluate(execution_context=policy_context(), plan_node=node or policy_node())


def test_explicit_allow_and_default_deny() -> None:
    allowed = evaluate(registry_for())
    assert allowed.allowed is True
    assert allowed.reason_code == PolicyReasonCode.ALLOW.value

    denied = evaluate(registry_for(grants=InstallGrants()))
    assert denied.allowed is False
    assert denied.reason_code == PolicyReasonCode.CAPABILITY_NOT_GRANTED.value


def test_explicit_deny_wins_over_allow() -> None:
    decision = evaluate(
        registry_for(
            grants=InstallGrants(
                allowed_capabilities=("test.data.read",),
                denied_capabilities=("test.data.read",),
            )
        )
    )

    assert decision.allowed is False
    assert decision.reason_code == PolicyReasonCode.CAPABILITY_EXPLICITLY_DENIED.value


def test_disabled_install_and_deployment_are_denied() -> None:
    assert evaluate(registry_for(install_enabled=False)).reason_code == PolicyReasonCode.INSTALL_DISABLED.value
    assert evaluate(registry_for(), deployment(enabled=False)).reason_code == PolicyReasonCode.DEPLOYMENT_DISABLED.value


def test_mutation_network_secret_filesystem_and_subprocess_denials() -> None:
    write = CapabilityDescriptor("test.resource.write", "0.1.0", CapabilityMode.WRITE.value)
    assert (
        evaluate(
            registry_for(capability=write, grants=InstallGrants(allowed_capabilities=("test.resource.write",))),
            node=policy_node("test.resource.write"),
        ).reason_code
        == PolicyReasonCode.MUTATION_NOT_ALLOWED.value
    )

    network_registry = registry_for(
        component_permissions={"network": {"required": True, "allowed_domains": ["api.example.test"]}},
        grants=InstallGrants(allowed_capabilities=("test.data.read",)),
    )
    assert evaluate(network_registry).reason_code == PolicyReasonCode.NETWORK_NOT_ALLOWED.value

    secret_capability = CapabilityDescriptor(
        "test.data.read",
        "0.1.0",
        CapabilityMode.READ.value,
        policy={"required_secret_refs": ["secretref:test"]},
    )
    assert (
        evaluate(
            registry_for(capability=secret_capability, grants=InstallGrants(allowed_capabilities=("test.data.read",)))
        ).reason_code
        == PolicyReasonCode.SECRET_NOT_GRANTED.value
    )

    fs_registry = registry_for(
        component_permissions={"filesystem": {"mode": "read"}},
        grants=InstallGrants(allowed_capabilities=("test.data.read",)),
    )
    assert evaluate(fs_registry).reason_code == PolicyReasonCode.FILESYSTEM_ACCESS_NOT_ALLOWED.value

    subprocess_registry = registry_for(
        component_permissions={"subprocess": {"allowed": True, "policy": "read-only"}},
        grants=InstallGrants(allowed_capabilities=("test.data.read",)),
    )
    assert evaluate(subprocess_registry).reason_code == PolicyReasonCode.SUBPROCESS_NOT_ALLOWED.value


def test_domain_allowlist_must_be_allowed_by_install_and_deployment() -> None:
    registry = registry_for(
        component_permissions={"network": {"required": True, "allowed_domains": ["api.example.test"]}},
        grants=InstallGrants(
            allowed_capabilities=("test.data.read",),
            allow_network=True,
            allowed_network_domains=("api.example.test",),
        ),
    )
    denied = evaluate(
        registry, deployment(DeploymentPolicy(allow_network=True, allowed_network_domains=("other.test",)))
    )
    assert denied.reason_code == PolicyReasonCode.DOMAIN_NOT_ALLOWED.value

    allowed = evaluate(
        registry,
        deployment(DeploymentPolicy(allow_network=True, allowed_network_domains=("api.example.test",))),
    )
    assert allowed.allowed is True


def test_policy_aware_capability_report_and_validation() -> None:
    from tests.test_phase46_remote_read_bridge import load_youtube_playbook, youtube_deployment

    registry = phase41_runtime_registry()
    base_deploy = youtube_deployment("youtube-don-main-channel")
    deploy = replace(
        base_deploy,
        policy=DeploymentPolicy(allow_network=False),
    )
    policy_engine = RuntimePolicyEngine(registry=registry, deployments={deploy.deployment_id: deploy})
    report = capability_report(load_youtube_playbook(), deploy, registry, policy_engine=policy_engine)

    assert report.entries[0].policy_decision == "DENY"
    assert report.entries[0].policy_reason == PolicyReasonCode.NETWORK_NOT_ALLOWED.value
    with pytest.raises(DeploymentValidationError) as raised:
        validate_deployment(load_youtube_playbook(), deploy, registry, policy_engine=policy_engine)
    assert raised.value.code == PolicyReasonCode.NETWORK_NOT_ALLOWED.value


def test_no_provider_specific_policy_branches_in_core() -> None:
    source = Path("src/core/runtime/policy.py").read_text(encoding="utf-8").lower()

    for forbidden in ("youtube", "linkedin", "calendar", "github", "googleapis"):
        assert forbidden not in source
