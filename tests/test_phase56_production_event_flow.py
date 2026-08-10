import subprocess
from pathlib import Path
from typing import Any
import pytest

from channels.markdown_website.models import WebsiteRepositoryReference
from publication_git_runtime_handlers import (
    GIT_WEBSITE_COMPONENT_ID,
    WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
    build_website_published_event,
    reconcile_mutation_events,
    register_and_activate_website_publish,
)
from runtime_foundation_mappings import phase41_component_manifests
from src.core.runtime.candidates import admit_and_register_mutation
from src.core.runtime.capabilities import CapabilityDescriptor, CapabilityMode
from src.core.runtime.components import ComponentManifest
from src.core.runtime.deployments import DeploymentPolicy, PlaybookDeployment, RequirementBinding
from src.core.runtime.dispatcher import TriggerDispatcher
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.event_store import EventDeliveryState, SqliteEventStore
from src.core.runtime.events import EventEnvelope, EventSource
from src.core.runtime.executor import PlaybookExecutor
from src.core.runtime.handlers import CapabilityHandler, CapabilityHandlerRegistry
from src.core.runtime.installs import ComponentBinding, Install, InstallGrants
from src.core.runtime.permissions import InstallPermissionGrants
from src.core.runtime.ledger import ExecutionState, InMemoryExecutionLedger
from src.core.runtime.mutations import InMemoryMutationJournal, MutationState
from src.core.runtime.plans import ExecutionPlanNode, compile_execution_plan
from src.core.runtime.playbooks import CapabilityRequirement, PlaybookDefinition, PlaybookNode
from src.core.runtime.policy import InMemoryApprovalStore, RuntimePolicyEngine
from src.core.runtime.resolver import RuntimeRegistry
from src.core.runtime.results import NodeResult


class DummyEchoHandler(CapabilityHandler):
    def __init__(self, component_id: str, capability_id: str):
        self.component_id = component_id
        self.capability_id = capability_id

    def execute(self, *, context: Any, node: PlaybookNode, resolved_node: Any = None, input_data: Any = None, **kwargs: Any) -> NodeResult:
        return NodeResult.success({"echo_result": node.config.get("message", "ok")})


def _init_git_repo(repo_path: Path) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True)
    (repo_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True, capture_output=True)


def test_production_flow_mutation_to_event_to_second_playbook(tmp_path: Path):
    repo_dir = tmp_path / "website_repo"
    _init_git_repo(repo_dir)

    db_path = tmp_path / "runtime_events.db"
    store = SqliteEventStore(db_path)
    registry = RuntimeRegistry()
    handler_registry = CapabilityHandlerRegistry()

    # 1. Register Website Component & Install
    website_comp = next(m for m in phase41_component_manifests() if m.component_id == GIT_WEBSITE_COMPONENT_ID)
    website_install = Install(
        install_id="website-prod-install",
        workspace_id="ws-prod",
        provider="github",
        account_ref="main_repo",
        component_bindings={
            WEBSITE_ARTICLE_PUBLISH_CAPABILITY: ComponentBinding(GIT_WEBSITE_COMPONENT_ID),
        },
        grants=InstallGrants(
            allowed_capabilities=(WEBSITE_ARTICLE_PUBLISH_CAPABILITY,),
            allow_filesystem=True,
            allow_subprocess=True,
            allow_network=True,
            allow_mutations=True,
            permission_grants=InstallPermissionGrants.from_dict({
                "filesystem": {"read": ["repository"], "write": ["repository"]},
                "operations": [
                    "git.status",
                    "git.rev_parse",
                    "git.cat_file",
                    "git.add.path",
                    "git.commit",
                    "git.push",
                    "git.fetch",
                ],
                "network": {"egress": [{"host": "github.com", "port": 443, "scheme": "https"}]},
            }),
        ),
    )
    registry.register_component(website_comp)
    registry.register_install(website_install)

    repo_ref = WebsiteRepositoryReference(
        id="test-repo-ref",
        workspace_id="ws-prod",
        display_name="website-repo",
        managed_checkout_root=repo_dir,
    )

    act_result = register_and_activate_website_publish(
        handler_registry,
        component=website_comp,
        install=website_install,
        repository_resolver=lambda i: repo_ref,
    )
    assert act_result.activated

    # 2. Register Downstream Echo Component & Install
    echo_comp = ComponentManifest(
        component_id="echo-component",
        provider="test",
        version="1.0.0",
        sdk_version="1.0.0",
        capabilities=(
            CapabilityDescriptor(capability_id="test.echo", version="1.0.0", mode=CapabilityMode.READ.value),
        ),
    )
    echo_install = Install(
        install_id="echo-install",
        workspace_id="ws-prod",
        provider="test",
        account_ref="test-acc",
        component_bindings={"test.echo": ComponentBinding("echo-component")},
        grants=InstallGrants(
            allowed_capabilities=("test.echo",),
            allow_network=True,
            allow_mutations=True,
        ),
    )
    registry.register_component(echo_comp)
    registry.register_install(echo_install)
    handler_registry.register(DummyEchoHandler("echo-component", "test.echo"))

    # Assert production mutation handler registered across system
    prod_mutations = [
        (h.component_id, h.capability_id)
        for h in handler_registry._handlers.values()
        if getattr(h, "component_id", "") not in {"test-component", "echo-component"}
    ]
    # The admitted production mutation is website.article.publish
    assert len([h for h in handler_registry._handlers.values() if getattr(h, "capability_id", "") == WEBSITE_ARTICLE_PUBLISH_CAPABILITY]) == 1

    # 3. Build Playbook A (Publish Article)
    playbook_a = PlaybookDefinition(
        playbook_id="playbook.publish.article",
        version="1.0",
        schema_version="1.0",
        name="Publish Article Playbook",
        requirements={"pub_slot": CapabilityRequirement(capabilities=(WEBSITE_ARTICLE_PUBLISH_CAPABILITY,))},
        nodes=(
            PlaybookNode(node_id="trig_a", kind="trigger", config={"event_type": "manual.trigger"}),
            PlaybookNode(
                node_id="pub1",
                kind="capability",
                config={
                    "requirement": "pub_slot",
                    "capability": WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
                    "input": {
                        "relative_path": "posts/hello.md",
                        "markdown_content": "# Hello World\nPublished content.",
                        "commit_message": "feat: publish hello article",
                        "push": False,
                    },
                },
            ),
        ),
    )

    deployment_a = PlaybookDeployment(
        deployment_id="dep-publish",
        playbook_id="playbook.publish.article",
        playbook_version="1.0",
        workspace_id="ws-prod",
        requirement_bindings={"pub_slot": RequirementBinding(install_id="website-prod-install")},
        policy=DeploymentPolicy(
            allow_filesystem=True,
            allow_subprocess=True,
            allow_mutations=True,
            require_approval_for_writes=True,
        ),
    )

    ledger = InMemoryExecutionLedger()
    approval_store = InMemoryApprovalStore()
    mutation_journal = InMemoryMutationJournal()
    policy_engine = RuntimePolicyEngine(registry=registry, deployments={"dep-publish": deployment_a})
    executor = PlaybookExecutor(
        handler_registry=handler_registry,
        ledger=ledger,
        policy_engine=policy_engine,
        approval_store=approval_store,
        mutation_journal=mutation_journal,
    )

    plan_a = compile_execution_plan(playbook_a, deployment_a, registry)
    start_event = EventEnvelope(
        event_id="evt_start_pub",
        event_type="manual.trigger",
        source=EventSource(component="system", provider="system"),
    )

    # 4. Execute Playbook A -> Reaches Approval WAITING
    outcome1 = executor.execute(plan=plan_a, trigger_event=start_event)
    nodes = ledger.list_node_executions(outcome1.execution.execution_id)
    assert outcome1.execution.state == ExecutionState.WAITING.value, f"State: {outcome1.execution.state}, Nodes: {[(n.node_id, n.state, n.error_code, n.error_message, n.metadata) for n in nodes]}"

    # Verify 0 published events materialized before approval/applied
    pre_events = reconcile_mutation_events(mutation_journal, store)
    assert len(pre_events) == 0

    # 5. Approve Execution Node -> Mutation executes & APPLIED
    outcome2 = executor.approve_execution_node(outcome1.execution.execution_id, "pub1")
    nodes2 = ledger.list_node_executions(outcome2.execution.execution_id)
    assert outcome2.execution.state == ExecutionState.SUCCEEDED.value, f"Nodes: {[(n.node_id, n.state, n.error_code, n.error_message, n.metadata) for n in nodes2]}"

    # 6. Reconcile Mutation Events -> 1 Event `website.article.published` Emitted
    post_events = reconcile_mutation_events(mutation_journal, store)
    assert len(post_events) == 1
    published_event = post_events[0]
    assert published_event.event_type == "website.article.published"
    assert published_event.causation_id.startswith("mutation_")
    assert published_event.payload["path"] == "posts/hello.md"

    # Reconciling again does NOT emit duplicate (idempotency identity check)
    dup_reconcile = reconcile_mutation_events(mutation_journal, store)
    assert len(dup_reconcile) == 1
    assert store.get(published_event.event_id) is not None

    # Re-reset store for dispatcher
    store_fresh = SqliteEventStore(db_path)

    # 7. Build Playbook B (Downstream Social Fanout Playbook)
    playbook_b = PlaybookDefinition(
        playbook_id="playbook.social.fanout",
        version="1.0",
        schema_version="1.0",
        name="Social Fanout Playbook",
        requirements={"echo_slot": CapabilityRequirement(capabilities=("test.echo",))},
        nodes=(
            PlaybookNode(node_id="trig_b", kind="trigger", config={"event_type": "website.article.published"}),
            PlaybookNode(
                node_id="node_b",
                kind="capability",
                config={"requirement": "echo_slot", "capability": "test.echo", "message": "social_notified"},
            ),
        ),
    )

    deployment_b = PlaybookDeployment(
        deployment_id="dep-social-fanout",
        playbook_id="playbook.social.fanout",
        playbook_version="1.0",
        workspace_id="ws-prod",
        requirement_bindings={"echo_slot": RequirementBinding(install_id="echo-install")},
        policy=DeploymentPolicy(allow_mutations=True),
    )

    deployments = {"dep-social-fanout": deployment_b}
    policy_engine.deployments["dep-social-fanout"] = deployment_b
    playbooks = {"playbook.social.fanout": playbook_b}

    dispatcher = TriggerDispatcher(
        store=store_fresh,
        registry=registry,
        executor=executor,
        deployments=deployments,
        playbooks=playbooks,
    )

    # 8. Dispatch Events -> Triggers Execution B
    dispatch_results = dispatcher.dispatch_pending_events()
    assert len(dispatch_results) == 1
    res_b = dispatch_results[0]
    assert res_b.record.state == EventDeliveryState.DISPATCHED.value
    assert res_b.outcome is not None
    nodes_b = ledger.list_node_executions(res_b.outcome.execution.execution_id)
    assert res_b.outcome.execution.state == ExecutionState.SUCCEEDED.value

    # 9. Lineage & Correlation Proof
    exec_b_record = ledger.get_execution(res_b.outcome.execution.execution_id)
    assert exec_b_record is not None
    assert exec_b_record.trigger_event_id == published_event.event_id
    assert published_event.causation_id.startswith("mutation_")
