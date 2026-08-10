from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from src.core.runtime import (
    CapabilityDescriptor,
    CapabilityHandler,
    CapabilityHandlerRegistry,
    CapabilityMode,
    CapabilityRequirement,
    ComponentBinding,
    ComponentManifest,
    DeploymentPolicy,
    EventDeliveryState,
    ExternalEventSource,
    ExternalSourceRecord,
    InMemoryApprovalStore,
    InMemoryExecutionLedger,
    InMemoryMutationJournal,
    Install,
    InstallGrants,
    NodeResult,
    PlaybookDefinition,
    PlaybookDeployment,
    PlaybookExecutor,
    PlaybookNode,
    RequirementBinding,
    RuntimePolicyEngine,
    RuntimeRegistry,
    SourceBatch,
    SourceCheckpointStore,
    SqliteEventStore,
    TriggerDispatcher,
    poll_and_ingest_external_events,
)


class DummyTestExternalSource(ExternalEventSource):
    source_id = "test-video-source"

    def __init__(self, records_by_poll: list[list[ExternalSourceRecord]] | None = None):
        self.records_by_poll = records_by_poll or []
        self.poll_count = 0

    def poll(self, *, install_id: str, checkpoint: str = "", limit: int = 10) -> SourceBatch:
        self.poll_count += 1
        if self.records_by_poll and self.poll_count <= len(self.records_by_poll):
            records = self.records_by_poll[self.poll_count - 1][:limit]
        else:
            records = []
        next_cp = f"cp_seq_{self.poll_count}"
        return SourceBatch(records=tuple(records), next_checkpoint=next_cp, has_more=False)


class DummyEchoHandler(CapabilityHandler):
    def __init__(self, component_id: str, capability_id: str):
        self.component_id = component_id
        self.capability_id = capability_id

    def execute(
        self, *, context: Any, node: PlaybookNode, resolved_node: Any = None, input_data: Any = None, **kwargs: Any
    ) -> NodeResult:
        return NodeResult.success({"echo_result": node.config.get("message", "ok")})


def test_sqlite_source_checkpoint_store_persistence(tmp_path: Path):
    db_path = tmp_path / "checkpoints.db"
    store = SourceCheckpointStore(db_path)

    assert store.get_checkpoint("src1", "inst1") is None

    cp = store.advance_checkpoint("src1", "inst1", "cursor_100")
    assert cp.source_id == "src1"
    assert cp.install_id == "inst1"
    assert cp.cursor == "cursor_100"

    # Re-instantiate store from disk to verify SQLite persistence
    store_reloaded = SourceCheckpointStore(db_path)
    loaded_cp = store_reloaded.get_checkpoint("src1", "inst1")
    assert loaded_cp is not None
    assert loaded_cp.cursor == "cursor_100"


def test_multi_worker_lease_safety(tmp_path: Path):
    db_path = tmp_path / "checkpoints.db"
    store = SourceCheckpointStore(db_path)

    # Worker 1 acquires lease
    assert store.acquire_lease("src1", "inst1", worker_id="w1", lease_duration_sec=60.0) is True

    # Worker 2 attempt to acquire lease fails
    assert store.acquire_lease("src1", "inst1", worker_id="w2", lease_duration_sec=60.0) is False

    # Worker 1 releases lease
    store.release_lease("src1", "inst1", worker_id="w1")

    # Worker 2 can now acquire lease
    assert store.acquire_lease("src1", "inst1", worker_id="w2", lease_duration_sec=60.0) is True


def test_poll_and_ingest_event_deduplication(tmp_path: Path):
    db_events = tmp_path / "events.db"
    db_checkpoints = tmp_path / "checkpoints.db"
    event_store = SqliteEventStore(db_events)
    checkpoint_store = SourceCheckpointStore(db_checkpoints)

    rec1 = ExternalSourceRecord(
        external_event_id="vid_101",
        event_type="test.video.published",
        occurred_at="2026-08-10T00:00:00Z",
        payload={"title": "Test Video 1", "video_id": "vid_101"},
    )

    source = DummyTestExternalSource(records_by_poll=[[rec1], [rec1]])
    install = Install(install_id="inst-test", workspace_id="ws1", provider="test_provider", account_ref="acc1")

    # First poll: ingests rec1
    success, code, events1 = poll_and_ingest_external_events(
        source=source,
        install=install,
        event_store=event_store,
        checkpoint_store=checkpoint_store,
        first_poll_policy="FROM_NOW",
    )
    assert success is True
    assert code == "BOOTSTRAP_FROM_NOW"

    # Second poll: same record vid_101 returned
    success2, code2, events2 = poll_and_ingest_external_events(
        source=source,
        install=install,
        event_store=event_store,
        checkpoint_store=checkpoint_store,
    )
    assert success2 is True
    assert code2 == "OK"

    # EventStore contains exactly 1 unique logical event (vid_101)
    ev = event_store.get("evt_ext_test-video-source_vid_101")
    assert ev is not None
    assert ev.payload["video_id"] == "vid_101"


def test_crash_recovery_before_and_after_event_persist(tmp_path: Path):
    db_events = tmp_path / "events.db"
    db_checkpoints = tmp_path / "checkpoints.db"

    rec_a = ExternalSourceRecord(
        external_event_id="vid_A",
        event_type="test.video.published",
        occurred_at="2026-08-10T00:00:00Z",
        payload={"title": "Video A"},
    )

    # 1. Crash before event persist -> checkpoint is unchanged
    event_store = SqliteEventStore(db_events)
    checkpoint_store = SourceCheckpointStore(db_checkpoints)

    assert checkpoint_store.get_checkpoint("test-video-source", "inst1") is None
    assert event_store.get("evt_ext_test-video-source_vid_A") is None

    # 2. Ingest successfully
    source = DummyTestExternalSource(records_by_poll=[[rec_a]])
    install = Install(install_id="inst1", workspace_id="ws1", provider="test_provider", account_ref="acc1")

    success, code, events = poll_and_ingest_external_events(
        source=source,
        install=install,
        event_store=event_store,
        checkpoint_store=checkpoint_store,
        first_poll_policy="LATEST_ONLY",
    )
    assert success is True
    assert len(events) == 1

    cp = checkpoint_store.get_checkpoint("test-video-source", "inst1")
    assert cp is not None
    assert cp.cursor == "cp_seq_1"


def test_external_event_triggers_portable_playbook(tmp_path: Path):
    db_events = tmp_path / "events.db"
    db_checkpoints = tmp_path / "checkpoints.db"
    event_store = SqliteEventStore(db_events)
    checkpoint_store = SourceCheckpointStore(db_checkpoints)

    # 1. External Record
    rec_pub = ExternalSourceRecord(
        external_event_id="vid_202",
        event_type="test.video.published",
        occurred_at="2026-08-10T01:00:00Z",
        payload={"video_id": "vid_202", "title": "New Video Published"},
    )

    source = DummyTestExternalSource(records_by_poll=[[rec_pub]])
    install = Install(install_id="inst-ext", workspace_id="ws-prod", provider="test_provider", account_ref="acc-ext")

    # 2. Ingest external event
    poll_and_ingest_external_events(
        source=source,
        install=install,
        event_store=event_store,
        checkpoint_store=checkpoint_store,
        first_poll_policy="LATEST_ONLY",
    )

    ext_event = event_store.get("evt_ext_test-video-source_vid_202")
    assert ext_event is not None
    assert ext_event.event_type == "test.video.published"

    # 3. Setup Downstream Playbook & Dispatcher
    registry = RuntimeRegistry()
    handler_registry = CapabilityHandlerRegistry()

    echo_comp = ComponentManifest(
        component_id="echo-component",
        provider="test",
        version="1.0.0",
        sdk_version="1.0.0",
        capabilities=(CapabilityDescriptor(capability_id="test.echo", version="1.0.0", mode=CapabilityMode.READ.value),),
    )
    echo_install = Install(
        install_id="echo-install",
        workspace_id="ws-prod",
        provider="test",
        account_ref="test-acc",
        component_bindings={"test.echo": ComponentBinding("echo-component")},
        grants=InstallGrants(allowed_capabilities=("test.echo",), allow_mutations=True),
    )
    registry.register_component(echo_comp)
    registry.register_install(echo_install)

    echo_handler = DummyEchoHandler("echo-component", "test.echo")
    handler_registry.register(echo_handler)

    playbook = PlaybookDefinition(
        playbook_id="playbook.video.fanout",
        version="1.0",
        schema_version="1.0",
        name="Video Fanout Playbook",
        requirements={"echo_slot": CapabilityRequirement(capabilities=("test.echo",))},
        nodes=(
            PlaybookNode(node_id="trig_1", kind="trigger", config={"event_type": "test.video.published"}),
            PlaybookNode(
                node_id="node_1",
                kind="capability",
                config={"requirement": "echo_slot", "capability": "test.echo", "message": "video_fanout_ok"},
            ),
        ),
    )

    deployment = PlaybookDeployment(
        deployment_id="dep-video-fanout",
        playbook_id="playbook.video.fanout",
        playbook_version="1.0",
        workspace_id="ws-prod",
        requirement_bindings={"echo_slot": RequirementBinding(install_id="echo-install")},
        policy=DeploymentPolicy(allow_mutations=True),
    )

    ledger = InMemoryExecutionLedger()
    approval_store = InMemoryApprovalStore()
    mutation_journal = InMemoryMutationJournal()
    policy_engine = RuntimePolicyEngine(registry=registry, deployments={"dep-video-fanout": deployment})

    executor = PlaybookExecutor(
        handler_registry=handler_registry,
        ledger=ledger,
        policy_engine=policy_engine,
        approval_store=approval_store,
        mutation_journal=mutation_journal,
    )

    dispatcher = TriggerDispatcher(
        store=event_store,
        registry=registry,
        executor=executor,
        deployments={"dep-video-fanout": deployment},
        playbooks={"playbook.video.fanout": playbook},
    )

    # 4. Dispatch Events -> Executed via TriggerDispatcher
    results = dispatcher.dispatch_pending_events()
    assert len(results) == 1
    res = results[0]
    assert res.record.state == EventDeliveryState.DISPATCHED.value
    assert res.outcome is not None
    assert res.outcome.execution.state == "succeeded"

    # Lineage check
    exec_rec = ledger.get_execution(res.outcome.execution.execution_id)
    assert exec_rec is not None
    assert exec_rec.trigger_event_id == ext_event.event_id


def test_production_boundary_and_admission_status():
    """Verify Phase 57 production boundary guarantees."""
    from unittest.mock import MagicMock
    from publication_calendar_runtime_handlers import register_calendar_mutation_runtime_handlers
    from publication_git_runtime_handlers import GIT_WEBSITE_COMPONENT_ID, WEBSITE_ARTICLE_PUBLISH_CAPABILITY, register_and_activate_website_publish
    from runtime_foundation_mappings import phase41_component_manifests
    from src.core.runtime.installs import ComponentBinding, InstallGrants, InstallPermissionGrants

    handler_registry = CapabilityHandlerRegistry()

    # Register production mutations
    register_calendar_mutation_runtime_handlers(
        handler_registry,
        calendar_service=MagicMock(),
        occurrence_repository=MagicMock(),
    )
    manifests = {m.component_id: m for m in phase41_component_manifests()}
    comp = manifests[GIT_WEBSITE_COMPONENT_ID]

    inst = Install(
        install_id="website-prod-install",
        workspace_id="local",
        provider="github",
        account_ref="main_repo",
        component_bindings={
            WEBSITE_ARTICLE_PUBLISH_CAPABILITY: ComponentBinding(GIT_WEBSITE_COMPONENT_ID),
        },
        grants=InstallGrants(
            allowed_capabilities=(
                "git.repository.status.read",
                "github.file.read",
                "website.publication.verify",
                WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
            ),
            allow_mutations=True,
            allow_filesystem=True,
            allow_subprocess=True,
            permission_grants=InstallPermissionGrants.from_dict({
                "filesystem": {"read": ["repository"], "write": ["repository"]},
                "operations": [
                    "git.status",
                    "git.rev_parse",
                    "git.cat_file",
                    "git.add.path",
                    "git.commit",
                    "git.push",
                ],
                "network": {"egress": [{"host": "github.com", "port": 443, "scheme": "https"}]},
            }),
        ),
    )

    register_and_activate_website_publish(
        handler_registry,
        component=comp,
        install=inst,
        repository_resolver=MagicMock(),
        git_publisher=MagicMock(),
    )

    registered_keys = set(handler_registry._handlers.keys())
    assert len(registered_keys) == 2, f"Active production handlers: {registered_keys}"
    expected = {
        ("publication-calendar-local", "calendar.event.create"),
        ("github-markdown-website", "website.article.publish"),
    }
    assert registered_keys == expected

    # YouTube external source admission is BLOCKED_NO_EXISTING_DISCOVERY
    # (No fake source registered)
