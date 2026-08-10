from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .deployments import PlaybookDeployment, capability_report
from .errors import PlaybookExecutionError
from .event_store import EventDeliveryState, EventDispatchRecord, EventStore
from .events import EventEnvelope
from .executor import ExecutionOutcome, PlaybookExecutor
from .plans import ExecutionPlan, compile_execution_plan
from .playbooks import PlaybookDefinition, PlaybookNodeKind
from .resolver import RuntimeRegistry


@dataclass(frozen=True)
class DispatchResult:
    event_id: str
    deployment_id: str
    record: EventDispatchRecord
    outcome: ExecutionOutcome | None = None


class TriggerDispatcher:
    def __init__(
        self,
        *,
        store: EventStore,
        registry: RuntimeRegistry,
        executor: PlaybookExecutor,
        deployments: dict[str, PlaybookDeployment],
        playbooks: dict[str, PlaybookDefinition],
        max_causation_depth: int = 5,
    ):
        self.store = store
        self.registry = registry
        self.executor = executor
        self.deployments = deployments
        self.playbooks = playbooks
        self.max_causation_depth = max_causation_depth

    def dispatch_pending_events(self, owner: str = "") -> list[DispatchResult]:
        owner = owner or "trigger_dispatcher"
        events = self.store.claim_pending(owner=owner, limit=50)
        results: list[DispatchResult] = []

        for event in events:
            matching = self._find_matching_deployments(event)
            if not matching:
                continue

            for deployment, playbook in matching:
                result = self._dispatch_single(event=event, deployment=deployment, playbook=playbook, owner=owner)
                results.append(result)

        return results

    def retry_dispatch(self, event_id: str, deployment_id: str, owner: str = "") -> DispatchResult:
        event = self.store.get(event_id)
        if event is None:
            raise PlaybookExecutionError("EVENT_NOT_FOUND", f"Event {event_id} does not exist.", {"event_id": event_id})

        deployment = self.deployments.get(deployment_id)
        if deployment is None:
            raise PlaybookExecutionError(
                "DEPLOYMENT_NOT_FOUND", f"Deployment {deployment_id} does not exist.", {"deployment_id": deployment_id}
            )

        playbook = self.playbooks.get(deployment.playbook_id)
        if playbook is None:
            raise PlaybookExecutionError(
                "PLAYBOOK_NOT_FOUND", f"Playbook {deployment.playbook_id} does not exist.", {"playbook_id": deployment.playbook_id}
            )

        return self._dispatch_single(event=event, deployment=deployment, playbook=playbook, owner=owner or "retry_dispatcher")

    def _find_matching_deployments(
        self, event: EventEnvelope
    ) -> list[tuple[PlaybookDeployment, PlaybookDefinition]]:
        matches: list[tuple[PlaybookDeployment, PlaybookDefinition]] = []
        for deployment in self.deployments.values():
            if not deployment.enabled:
                continue
            playbook = self.playbooks.get(deployment.playbook_id)
            if playbook is None:
                continue

            if self._playbook_matches_event(playbook, event.event_type):
                matches.append((deployment, playbook))

        return matches

    def _playbook_matches_event(self, playbook: PlaybookDefinition, event_type: str) -> bool:
        for node in playbook.nodes:
            if node.kind == PlaybookNodeKind.TRIGGER.value:
                trigger_type = str(node.config.get("event_type") or "")
                if trigger_type == event_type:
                    return True
        return False

    def _dispatch_single(
        self,
        *,
        event: EventEnvelope,
        deployment: PlaybookDeployment,
        playbook: PlaybookDefinition,
        owner: str,
    ) -> DispatchResult:
        # Check loop / causation depth guard
        depth_ok, loop_reason = self._check_loop_guard(event=event, deployment_id=deployment.deployment_id)
        if not depth_ok:
            record = self.store.mark_failed(
                event.event_id,
                deployment.deployment_id,
                error_code="LOOP_GUARD_BLOCKED",
                error_message=loop_reason,
            )
            return DispatchResult(event_id=event.event_id, deployment_id=deployment.deployment_id, record=record)

        # Capability / Deployment readiness check
        report = capability_report(playbook, deployment, self.registry)
        if not report.ok:
            first_fail = report.failures()[0]
            record = self.store.mark_failed(
                event.event_id,
                deployment.deployment_id,
                error_code=first_fail.error_code,
                error_message=first_fail.message,
            )
            return DispatchResult(event_id=event.event_id, deployment_id=deployment.deployment_id, record=record)

        self.store.record_dispatch_started(event.event_id, deployment.deployment_id, owner=owner)

        try:
            plan = compile_execution_plan(playbook, deployment, self.registry)
            outcome = self.executor.start_execution_once(plan=plan, trigger_event=event)
            record = self.store.mark_dispatched(
                event.event_id, deployment.deployment_id, outcome.execution.execution_id
            )
            return DispatchResult(
                event_id=event.event_id, deployment_id=deployment.deployment_id, record=record, outcome=outcome
            )
        except Exception as exc:
            error_code = getattr(exc, "code", "DISPATCH_EXECUTION_FAILED")
            record = self.store.mark_failed(
                event.event_id, deployment.deployment_id, error_code=str(error_code), error_message=str(exc)
            )
            return DispatchResult(event_id=event.event_id, deployment_id=deployment.deployment_id, record=record)

    def _check_loop_guard(self, *, event: EventEnvelope, deployment_id: str) -> tuple[bool, str]:
        depth = 0
        current_causation = event.causation_id
        visited_deployments: set[tuple[str, str]] = {(event.event_type, deployment_id)}

        while current_causation:
            depth += 1
            if depth > self.max_causation_depth:
                return False, f"Causation chain depth {depth} exceeds maximum allowed depth {self.max_causation_depth}."

            parent_event = self.store.get(current_causation)
            if parent_event:
                key = (parent_event.event_type, deployment_id)
                if key in visited_deployments:
                    return False, f"Self-trigger cycle detected for deployment {deployment_id} on event {parent_event.event_type}."
                visited_deployments.add(key)
                current_causation = parent_event.causation_id
            else:
                causation_events = [
                    e for e in self.store.list_events_by_causation(current_causation)
                    if e.event_id != event.event_id
                ]
                if not causation_events:
                    break
                first_parent = causation_events[0]
                key = (first_parent.event_type, deployment_id)
                if key in visited_deployments:
                    return False, f"Self-trigger cycle detected for deployment {deployment_id} on event {first_parent.event_type}."
                visited_deployments.add(key)
                current_causation = first_parent.causation_id

        return True, ""
