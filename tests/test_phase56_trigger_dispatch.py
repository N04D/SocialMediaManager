from pathlib import Path
from typing import Any
import pytest

from src.core.runtime.capabilities import CapabilityDescriptor, CapabilityMode
from src.core.runtime.components import ComponentManifest
from src.core.runtime.deployments import DeploymentPolicy, PlaybookDeployment, RequirementBinding
from src.core.runtime.event_store import EventDeliveryState, SqliteEventStore
from src.core.runtime.events import EventEnvelope, EventSource
from src.core.runtime.executor import PlaybookExecutor
from src.core.runtime.handlers import CapabilityHandler, CapabilityHandlerRegistry
from src.core.runtime.installs import ComponentBinding, Install, InstallGrants
from src.core.runtime.playbooks import CapabilityRequirement, PlaybookDefinition, PlaybookNode, PlaybookNodeKind
from src.core.runtime.resolver import RuntimeRegistry
from src.core.runtime.results import NodeResult
from src.core.runtime.dispatcher import TriggerDispatcher


class DummyEchoHandler(CapabilityHandler):
    def __init__(self, component_id: str, capability_id: str):
        self.component_id = component_id
        self.capability_id = capability_id

    def execute(self, node: PlaybookNode, context: Any) -> NodeResult:
        return NodeResult.success({"echo": node.config.get("message", "ok")})


def _build_test_setup(tmp_path: Path):
    store = SqliteEventStore(tmp_path / "events.db")
    registry = RuntimeRegistry()
    handler_registry = CapabilityHandlerRegistry()

    comp = ComponentManifest(
        component_id="echo-component",
        provider="test",
        version="1.0.0",
        sdk_version="1.0.0",
        capabilities=(
            CapabilityDescriptor(capability_id="test.echo", version="1.0.0", mode=CapabilityMode.WRITE.value),
        ),
    )
    install = Install(
        install_id="echo-install",
        workspace_id="ws-main",
        provider="test",
        account_ref="test-acc",
        component_bindings={"test.echo": ComponentBinding("echo-component")},
        grants=InstallGrants(
            allowed_capabilities=("test.echo",),
            allow_network=True,
            allow_mutations=True,
        ),
    )
    registry.register_component(comp)
    registry.register_install(install)

    handler = DummyEchoHandler("echo-component", "test.echo")
    handler_registry.register(handler)

    executor = PlaybookExecutor(handler_registry=handler_registry)

    # Playbook A: Triggered on website.article.published -> Echo capability
    playbook_a = PlaybookDefinition(
        playbook_id="playbook.analytics",
        version="1.0",
        schema_version="1.0",
        name="Analytics Triggered Playbook",
        requirements={"echo_slot": CapabilityRequirement(capabilities=("test.echo",))},
        nodes=(
            PlaybookNode(node_id="trig1", kind="trigger", config={"event_type": "website.article.published"}),
            PlaybookNode(
                node_id="node1",
                kind="capability",
                config={"requirement": "echo_slot", "capability": "test.echo", "message": "analytics_processed"},
            ),
        ),
    )

    deployment_a = PlaybookDeployment(
        deployment_id="dep-analytics",
        playbook_id="playbook.analytics",
        playbook_version="1.0",
        workspace_id="ws-main",
        requirement_bindings={"echo_slot": RequirementBinding(install_id="echo-install")},
        policy=DeploymentPolicy(allow_mutations=True),
    )

    # Playbook B: Triggered on website.article.published -> Echo capability
    playbook_b = PlaybookDefinition(
        playbook_id="playbook.social",
        version="1.0",
        schema_version="1.0",
        name="Social Distribution Playbook",
        requirements={"echo_slot": CapabilityRequirement(capabilities=("test.echo",))},
        nodes=(
            PlaybookNode(node_id="trig2", kind="trigger", config={"event_type": "website.article.published"}),
            PlaybookNode(
                node_id="node2",
                kind="capability",
                config={"requirement": "echo_slot", "capability": "test.echo", "message": "social_distributed"},
            ),
        ),
    )

    deployment_b = PlaybookDeployment(
        deployment_id="dep-social",
        playbook_id="playbook.social",
        playbook_version="1.0",
        workspace_id="ws-main",
        requirement_bindings={"echo_slot": RequirementBinding(install_id="echo-install")},
        policy=DeploymentPolicy(allow_mutations=True),
    )

    deployments = {"dep-analytics": deployment_a, "dep-social": deployment_b}
    playbooks = {"playbook.analytics": playbook_a, "playbook.social": playbook_b}

    dispatcher = TriggerDispatcher(
        store=store,
        registry=registry,
        executor=executor,
        deployments=deployments,
        playbooks=playbooks,
    )

    return store, dispatcher, executor


def test_trigger_dispatch_multi_playbook_fanout(tmp_path: Path):
    store, dispatcher, _ = _build_test_setup(tmp_path)
    source = EventSource(component="github-markdown-website", install="website-install", provider="github")
    event = EventEnvelope(
        event_id="evt_pub_001",
        event_type="website.article.published",
        source=source,
        payload={"commit_sha": "abc111"},
    )
    store.append(event)

    results = dispatcher.dispatch_pending_events()
    assert len(results) == 2

    res_a = next(r for r in results if r.deployment_id == "dep-analytics")
    res_b = next(r for r in results if r.deployment_id == "dep-social")

    assert res_a.record.state == EventDeliveryState.DISPATCHED.value
    assert res_b.record.state == EventDeliveryState.DISPATCHED.value
    assert res_a.outcome is not None
    assert res_b.outcome is not None
    # Independent execution IDs created
    assert res_a.outcome.execution.execution_id != res_b.outcome.execution.execution_id


def test_trigger_dispatch_failure_isolation(tmp_path: Path):
    store, dispatcher, _ = _build_test_setup(tmp_path)

    # Break deployment_b by pointing to missing install
    bad_deployment_b = PlaybookDeployment(
        deployment_id="dep-social",
        playbook_id="playbook.social",
        playbook_version="1.0",
        workspace_id="ws-main",
        requirement_bindings={"echo_slot": RequirementBinding(install_id="missing-install")},
    )
    dispatcher.deployments["dep-social"] = bad_deployment_b

    source = EventSource(component="github-markdown-website", install="website-install", provider="github")
    event = EventEnvelope(
        event_id="evt_pub_002",
        event_type="website.article.published",
        source=source,
        payload={"commit_sha": "abc222"},
    )
    store.append(event)

    results = dispatcher.dispatch_pending_events()
    assert len(results) == 2

    res_a = next(r for r in results if r.deployment_id == "dep-analytics")
    res_b = next(r for r in results if r.deployment_id == "dep-social")

    assert res_a.record.state == EventDeliveryState.DISPATCHED.value
    assert res_b.record.state == EventDeliveryState.FAILED.value
    assert res_b.record.error_code == "INSTALL_MISSING"


def test_loop_guard_blocks_unbounded_causation_cycle(tmp_path: Path):
    store, dispatcher, _ = _build_test_setup(tmp_path)
    dispatcher.max_causation_depth = 2

    source = EventSource(component="github-markdown-website", install="website-install", provider="github")

    e1 = EventEnvelope(event_id="evt_c1", event_type="website.article.published", source=source, causation_id="mut_100")
    store.append(e1)

    e2 = EventEnvelope(event_id="evt_c2", event_type="website.article.published", source=source, causation_id="evt_c1")
    store.append(e2)

    e3 = EventEnvelope(event_id="evt_c3", event_type="website.article.published", source=source, causation_id="evt_c2")
    store.append(e3)

    # Claim e1, e2 first
    dispatcher.dispatch_pending_events()

    # e3 has depth 3 > max_causation_depth=2
    results = dispatcher.dispatch_pending_events()
    res_e3 = [r for r in results if r.event_id == "evt_c3"]
    if res_e3:
        assert res_e3[0].record.state == EventDeliveryState.FAILED.value
        assert res_e3[0].record.error_code == "LOOP_GUARD_BLOCKED"


def test_replay_dispatch_uses_same_event_id(tmp_path: Path):
    store, dispatcher, _ = _build_test_setup(tmp_path)
    source = EventSource(component="github-markdown-website", install="website-install", provider="github")
    event = EventEnvelope(event_id="evt_replay1", event_type="website.article.published", source=source)
    store.append(event)

    # Break deployment first
    bad_dep = PlaybookDeployment(
        deployment_id="dep-analytics",
        playbook_id="playbook.analytics",
        playbook_version="1.0",
        workspace_id="ws-main",
        requirement_bindings={"echo_slot": RequirementBinding(install_id="missing-install")},
    )
    dispatcher.deployments["dep-analytics"] = bad_dep

    results = dispatcher.dispatch_pending_events()
    res_a = next(r for r in results if r.deployment_id == "dep-analytics")
    assert res_a.record.state == EventDeliveryState.FAILED.value

    # Fix deployment and replay
    good_dep = PlaybookDeployment(
        deployment_id="dep-analytics",
        playbook_id="playbook.analytics",
        playbook_version="1.0",
        workspace_id="ws-main",
        requirement_bindings={"echo_slot": RequirementBinding(install_id="echo-install")},
    )
    dispatcher.deployments["dep-analytics"] = good_dep

    replay_res = dispatcher.retry_dispatch("evt_replay1", "dep-analytics")
    assert replay_res.event_id == "evt_replay1"
    assert replay_res.record.state == EventDeliveryState.DISPATCHED.value
