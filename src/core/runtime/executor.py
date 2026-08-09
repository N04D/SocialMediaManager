from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .conditions import evaluate_condition
from .errors import PlaybookExecutionError
from .events import EventEnvelope
from .execution_context import ExecutionContext
from .handlers import CapabilityHandlerRegistry
from .input_resolution import resolve_node_input
from .ledger import TERMINAL_STATES, ExecutionLedger, ExecutionRecord, ExecutionState, InMemoryExecutionLedger
from .plans import ExecutionPlan, ExecutionPlanNode
from .playbooks import PlaybookNode, PlaybookNodeKind
from .policy import ApprovalStatus, InMemoryApprovalStore, RuntimePolicyEngine
from .results import NodeResult, NodeResultStatus
from .transforms import execute_transform


@dataclass(frozen=True)
class ExecutionOutcome:
    execution: ExecutionRecord
    context: ExecutionContext


@dataclass
class PlaybookExecutor:
    handler_registry: CapabilityHandlerRegistry
    ledger: ExecutionLedger = field(default_factory=InMemoryExecutionLedger)
    policy_engine: RuntimePolicyEngine | None = None
    approval_store: InMemoryApprovalStore = field(default_factory=InMemoryApprovalStore)
    _contexts: dict[str, ExecutionContext] = field(default_factory=dict)
    _plans: dict[str, ExecutionPlan] = field(default_factory=dict)
    _waiting_node_ids: dict[str, str] = field(default_factory=dict)

    def start_execution_once(self, *, plan: ExecutionPlan, trigger_event: EventEnvelope) -> ExecutionOutcome:
        existing_id = getattr(self.ledger, "idempotency_index", {}).get(_execution_idempotency_key(plan, trigger_event))
        if existing_id:
            existing = self.ledger.get_execution(existing_id)
            if existing is not None:
                context = self._contexts.get(existing.execution_id)
                if context is None:
                    context = _new_context(existing, trigger_event)
                    self._contexts[existing.execution_id] = context
                return ExecutionOutcome(existing, context)
        return self.execute(plan=plan, trigger_event=trigger_event, idempotent=True)

    def execute(
        self, *, plan: ExecutionPlan, trigger_event: EventEnvelope, idempotent: bool = True
    ) -> ExecutionOutcome:
        record = ExecutionRecord(
            deployment_id=plan.deployment_id,
            playbook_id=plan.playbook_id,
            playbook_version=plan.playbook_version,
            trigger_event_id=trigger_event.event_id,
            correlation_id=trigger_event.correlation_id,
            trace_id=trigger_event.trace_id,
            idempotency_key=_execution_idempotency_key(plan, trigger_event) if idempotent else "",
        )
        created = self.ledger.create_execution(record)
        context = _new_context(created, trigger_event)
        self._contexts[created.execution_id] = context
        self._plans[created.execution_id] = plan
        if created.execution_id != record.execution_id:
            return ExecutionOutcome(created, self._contexts[created.execution_id])
        self.ledger.record_transition(created.execution_id, ExecutionState.RUNNING.value, actor="playbook_executor")
        return self._run_ready_nodes(plan=plan, execution_id=created.execution_id, resume_node_id="")

    def resume_execution(self, execution_id: str) -> ExecutionOutcome:
        record = self.ledger.get_execution(execution_id)
        if record is None:
            raise PlaybookExecutionError(
                "EXECUTION_NOT_FOUND", "Execution does not exist.", {"execution_id": execution_id}
            )
        if record.state in TERMINAL_STATES:
            raise PlaybookExecutionError(
                "EXECUTION_ALREADY_TERMINAL",
                "Terminal execution cannot be resumed.",
                {"execution_id": execution_id, "state": record.state},
            )
        if record.state != ExecutionState.WAITING.value:
            raise PlaybookExecutionError(
                "EXECUTION_NOT_WAITING",
                "Only waiting executions can be resumed.",
                {"execution_id": execution_id, "state": record.state},
            )
        plan = self._plans[execution_id]
        self.ledger.record_transition(execution_id, ExecutionState.RUNNING.value, actor="playbook_executor.resume")
        return self._run_ready_nodes(
            plan=plan,
            execution_id=execution_id,
            resume_node_id=self._waiting_node_ids.pop(execution_id, ""),
        )

    def approve_execution_node(self, execution_id: str, node_id: str, *, actor: str = "") -> ExecutionOutcome:
        record = self.ledger.get_execution(execution_id)
        if record is None:
            raise PlaybookExecutionError(
                "EXECUTION_NOT_FOUND", "Execution does not exist.", {"execution_id": execution_id}
            )
        approval = self.approval_store.get(execution_id, node_id)
        if approval is None:
            raise PlaybookExecutionError(
                "APPROVAL_NOT_FOUND",
                "No approval is pending for this execution node.",
                {"execution_id": execution_id, "node_id": node_id},
            )
        if approval.status == ApprovalStatus.REJECTED.value:
            raise PlaybookExecutionError(
                "APPROVAL_REJECTED",
                "Rejected approval cannot be approved later.",
                {"execution_id": execution_id, "node_id": node_id},
            )
        self.approval_store.approve(execution_id, node_id, actor=actor)
        current = self.ledger.get_execution(execution_id)
        assert current is not None
        if current.state in TERMINAL_STATES:
            return ExecutionOutcome(current, self._contexts[execution_id])
        return self.resume_execution(execution_id)

    def reject_execution_node(self, execution_id: str, node_id: str, *, actor: str = "") -> ExecutionOutcome:
        record = self.ledger.get_execution(execution_id)
        if record is None:
            raise PlaybookExecutionError(
                "EXECUTION_NOT_FOUND", "Execution does not exist.", {"execution_id": execution_id}
            )
        approval = self.approval_store.get(execution_id, node_id)
        if approval is None:
            raise PlaybookExecutionError(
                "APPROVAL_NOT_FOUND",
                "No approval is pending for this execution node.",
                {"execution_id": execution_id, "node_id": node_id},
            )
        self.approval_store.reject(execution_id, node_id, actor=actor)
        for node_execution in reversed(self.ledger.list_node_executions(execution_id)):
            if node_execution.node_id == node_id and node_execution.state == ExecutionState.WAITING.value:
                self.ledger.record_node_transition(
                    node_execution.node_execution_id,
                    ExecutionState.FAILED.value,
                    actor="playbook_executor.reject",
                    error_code="APPROVAL_REJECTED",
                    error_message="Approval was rejected.",
                    metadata={"approval_status": ApprovalStatus.REJECTED.value},
                )
                break
        current = self.ledger.get_execution(execution_id)
        assert current is not None
        if current.state not in TERMINAL_STATES:
            self.ledger.record_transition(execution_id, ExecutionState.FAILED.value, actor="playbook_executor.reject")
        return ExecutionOutcome(self.ledger.get_execution(execution_id), self._contexts[execution_id])  # type: ignore[arg-type]

    def _run_ready_nodes(self, *, plan: ExecutionPlan, execution_id: str, resume_node_id: str) -> ExecutionOutcome:
        context = self._contexts[execution_id]
        nodes = {node.node_id: node for node in plan.nodes}
        incoming = _incoming_edges(plan)
        outgoing = _outgoing_edges(plan)
        completed: set[str] = set(context.node_outputs)
        failed: set[str] = set()
        skipped: set[str] = set()
        waiting = ""
        while True:
            ready = [
                node
                for node in plan.nodes
                if node.node_id not in completed
                and node.node_id not in skipped
                and node.node_id not in failed
                and _dependencies_satisfied(node.node_id, incoming, completed, skipped)
            ]
            if resume_node_id:
                ready = [node for node in ready if node.node_id == resume_node_id] + [
                    node for node in ready if node.node_id != resume_node_id
                ]
                resume_node_id = ""
            if not ready:
                break
            node = ready[0]
            if any(edge["source"] in failed for edge in incoming.get(node.node_id, [])):
                skipped.add(node.node_id)
                self._record_skip(execution_id, node)
                context = context.with_node_output(node.node_id, {"skipped": True})
                self._contexts[execution_id] = context
                continue
            result = self._execute_node(plan_node=node, plan_nodes=nodes, context=context)
            context = self._contexts[execution_id]
            if result.status == NodeResultStatus.SUCCESS.value:
                completed.add(node.node_id)
                if node.kind == PlaybookNodeKind.CONDITION.value:
                    _apply_condition_routing(
                        node.node_id, result.output.get("value"), outgoing, skipped, execution_id, self
                    )
                continue
            if result.status == NodeResultStatus.SKIP.value:
                skipped.add(node.node_id)
                continue
            if result.status == NodeResultStatus.WAIT.value:
                waiting = node.node_id
                break
            failed.add(node.node_id)
        current = self.ledger.get_execution(execution_id)
        assert current is not None
        if waiting:
            self._waiting_node_ids[execution_id] = waiting
            if current.state != ExecutionState.WAITING.value:
                self.ledger.record_transition(execution_id, ExecutionState.WAITING.value, actor="playbook_executor")
        elif failed:
            self.ledger.record_transition(execution_id, ExecutionState.FAILED.value, actor="playbook_executor")
        elif all(node.node_id in completed or node.node_id in skipped for node in plan.nodes):
            self.ledger.record_transition(execution_id, ExecutionState.SUCCEEDED.value, actor="playbook_executor")
        return ExecutionOutcome(self.ledger.get_execution(execution_id), self._contexts[execution_id])  # type: ignore[arg-type]

    def _execute_node(
        self, *, plan_node: ExecutionPlanNode, plan_nodes: dict[str, ExecutionPlanNode], context: ExecutionContext
    ) -> NodeResult:
        del plan_nodes
        node = PlaybookNode(plan_node.node_id, plan_node.kind, plan_node.config)
        max_attempts = int((node.config.get("retry") or {}).get("max_attempts") or 1)
        last_result = NodeResult.failure("INVALID_NODE_RESULT", "Node did not produce a result.")
        for _ in range(max(max_attempts, 1)):
            node_execution = self.ledger.create_node_execution(
                context.execution_id,
                node.node_id,
                metadata=_node_provenance(plan_node),
            )
            self.ledger.record_node_transition(
                node_execution.node_execution_id, ExecutionState.RUNNING.value, actor="playbook_executor"
            )
            try:
                result = self._execute_node_once(node=node, plan_node=plan_node, context=context)
            except PlaybookExecutionError as exc:
                result = NodeResult.failure(exc.code, exc.user_message, exc.details)
            except Exception as exc:
                result = NodeResult.failure(
                    "CAPABILITY_EXECUTION_FAILED",
                    "Node execution failed.",
                    {"error": type(exc).__name__},
                )
            if not isinstance(result, NodeResult):
                result = NodeResult.failure("INVALID_NODE_RESULT", "Handler returned an invalid node result.")
            last_result = result
            if result.status == NodeResultStatus.SUCCESS.value:
                self.ledger.record_node_transition(
                    node_execution.node_execution_id,
                    ExecutionState.SUCCEEDED.value,
                    actor="playbook_executor",
                    metadata=result.metadata,
                )
                self._contexts[context.execution_id] = self._contexts[context.execution_id].with_node_output(
                    node.node_id, result.output
                )
                return result
            if result.status == NodeResultStatus.WAIT.value:
                self.ledger.record_node_transition(
                    node_execution.node_execution_id,
                    ExecutionState.WAITING.value,
                    actor="playbook_executor",
                    metadata=result.metadata,
                )
                return result
            if result.status == NodeResultStatus.SKIP.value:
                self.ledger.record_node_transition(
                    node_execution.node_execution_id,
                    ExecutionState.SKIPPED.value,
                    actor="playbook_executor",
                    metadata=result.metadata,
                )
                self._contexts[context.execution_id] = self._contexts[context.execution_id].with_node_output(
                    node.node_id, result.output
                )
                return result
            self.ledger.record_node_transition(
                node_execution.node_execution_id,
                ExecutionState.FAILED.value,
                actor="playbook_executor",
                error_code=result.error_code or "CAPABILITY_EXECUTION_FAILED",
                error_message=result.error_message,
                metadata=result.metadata,
            )
        return NodeResult.failure("RETRY_EXHAUSTED", "Retry attempts were exhausted.", last_result.metadata)

    def _execute_node_once(
        self, *, node: PlaybookNode, plan_node: ExecutionPlanNode, context: ExecutionContext
    ) -> NodeResult:
        if node.kind == PlaybookNodeKind.TRIGGER.value:
            return NodeResult.success(
                {"payload": context.trigger_event.payload, "event_id": context.trigger_event.event_id}
            )
        if node.kind == PlaybookNodeKind.TRANSFORM.value:
            return execute_transform(node, context)
        if node.kind == PlaybookNodeKind.CONDITION.value:
            return NodeResult.success({"value": evaluate_condition(node.config, context)})
        if node.kind == PlaybookNodeKind.CAPABILITY.value:
            input_data = resolve_node_input(node.config, context)
            policy_metadata: dict[str, Any] = {}
            if self.policy_engine is not None:
                approval = self.approval_store.get(context.execution_id, node.node_id)
                decision = self.policy_engine.evaluate(
                    execution_context=context,
                    plan_node=plan_node,
                    approval=approval,
                )
                if decision.required_approval:
                    requested = self.approval_store.request(
                        execution_id=context.execution_id,
                        node_id=node.node_id,
                        capability_id=plan_node.capability,
                        metadata=decision.metadata,
                    )
                    return NodeResult.wait(
                        {"waiting": True, "approval_id": requested.approval_id},
                        {
                            **decision.metadata,
                            "approval_id": requested.approval_id,
                            "approval_status": requested.status,
                            "waiting_reason": "approval_required",
                        },
                    )
                if not decision.allowed:
                    return NodeResult.failure(
                        decision.reason_code, "Runtime policy denied capability execution.", decision.metadata
                    )
                policy_metadata = decision.metadata
            handler = self.handler_registry.resolve(plan_node.component_id, plan_node.capability)
            result = handler.execute(context=context, node=node, resolved_node=plan_node, input_data=input_data)
            if policy_metadata and isinstance(result, NodeResult):
                return NodeResult(
                    status=result.status,
                    output=result.output,
                    metadata={**policy_metadata, **result.metadata},
                    error_code=result.error_code,
                    error_message=result.error_message,
                )
            return result
        if node.kind in {PlaybookNodeKind.APPROVAL.value, PlaybookNodeKind.DELAY.value}:
            return NodeResult.wait({"waiting": True, "kind": node.kind})
        if node.kind == PlaybookNodeKind.JOIN.value:
            return NodeResult.success({"joined": True})
        raise PlaybookExecutionError("INVALID_NODE_RESULT", "Unsupported node kind.", {"kind": node.kind})

    def _record_skip(self, execution_id: str, node: ExecutionPlanNode) -> None:
        record = self.ledger.create_node_execution(execution_id, node.node_id)
        self.ledger.record_node_transition(
            record.node_execution_id, ExecutionState.SKIPPED.value, actor="playbook_executor"
        )


def _new_context(record: ExecutionRecord, trigger_event: EventEnvelope) -> ExecutionContext:
    return ExecutionContext(
        execution_id=record.execution_id,
        deployment_id=record.deployment_id,
        trigger_event=trigger_event,
        correlation_id=record.correlation_id,
        trace_id=record.trace_id,
    )


def _execution_idempotency_key(plan: ExecutionPlan, trigger_event: EventEnvelope) -> str:
    event_key = trigger_event.idempotency_key or trigger_event.external_event_id or trigger_event.event_id
    return f"{plan.deployment_id}:{event_key}"


def _incoming_edges(plan: ExecutionPlan) -> dict[str, list[dict[str, Any]]]:
    incoming: dict[str, list[dict[str, Any]]] = {node.node_id: [] for node in plan.nodes}
    for edge in plan.edges:
        incoming.setdefault(str(edge["target"]), []).append(edge)
    return incoming


def _outgoing_edges(plan: ExecutionPlan) -> dict[str, list[dict[str, Any]]]:
    outgoing: dict[str, list[dict[str, Any]]] = {node.node_id: [] for node in plan.nodes}
    for edge in plan.edges:
        outgoing.setdefault(str(edge["source"]), []).append(edge)
    return outgoing


def _dependencies_satisfied(
    node_id: str, incoming: dict[str, list[dict[str, Any]]], completed: set[str], skipped: set[str]
) -> bool:
    return all(str(edge["source"]) in completed or str(edge["source"]) in skipped for edge in incoming.get(node_id, []))


def _apply_condition_routing(
    node_id: str,
    value: Any,
    outgoing: dict[str, list[dict[str, Any]]],
    skipped: set[str],
    execution_id: str,
    executor: PlaybookExecutor,
) -> None:
    for edge in outgoing.get(node_id, []):
        condition = str(edge.get("condition") or edge.get("source_port") or "")
        if condition in {"true", "false"} and str(value).lower() != condition:
            target = str(edge["target"])
            skipped.add(target)
            executor._record_skip(execution_id, ExecutionPlanNode(target, "skipped"))


def _node_provenance(plan_node: ExecutionPlanNode) -> dict[str, Any]:
    metadata = {"kind": plan_node.kind}
    if plan_node.requirement:
        metadata["requirement"] = plan_node.requirement
    if plan_node.install_id:
        metadata["install_id"] = plan_node.install_id
    if plan_node.capability:
        metadata["capability"] = plan_node.capability
    if plan_node.component_id:
        metadata["component_id"] = plan_node.component_id
    if plan_node.provider:
        metadata["provider"] = plan_node.provider
    return metadata
