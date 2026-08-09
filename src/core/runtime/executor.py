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
from .mutation_policies import (
    MutationPolicy,
    ReadbackPolicy,
    RecoveryPolicy,
    requested_mutation_policy_from_config,
    validate_mutation_safety,
)
from .mutations import (
    CompensatableMutationHandler,
    CompensationIntent,
    CompensationState,
    InMemoryMutationJournal,
    MutationIntent,
    MutationJournal,
    MutationReceipt,
    MutationState,
    build_compensation_id,
    build_compensation_idempotency_key,
    build_mutation_id,
    build_mutation_idempotency_key,
    canonical_mutation_input,
    mutation_input_fingerprint,
)
from .plans import ExecutionPlan, ExecutionPlanNode
from .playbooks import PlaybookNode, PlaybookNodeKind
from .policy import ApprovalRecord, ApprovalStatus, InMemoryApprovalStore, RuntimePolicyEngine
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
    mutation_journal: MutationJournal = field(default_factory=InMemoryMutationJournal)
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

    def approve_execution_node(
        self,
        execution_id: str,
        node_id: str,
        *,
        actor: str = "",
        actor_id: str = "",
        actor_type: str = "",
    ) -> ExecutionOutcome:
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
        approved = self.approval_store.approve(
            execution_id, node_id, actor=actor, actor_id=actor_id, actor_type=actor_type
        )
        mutation_id = str(approved.metadata.get("mutation_id") or "")
        if mutation_id:
            self.mutation_journal.mark_approved(mutation_id, approval_id=approved.approval_id)
        current = self.ledger.get_execution(execution_id)
        assert current is not None
        if current.state in TERMINAL_STATES:
            return ExecutionOutcome(current, self._contexts[execution_id])
        return self.resume_execution(execution_id)

    def approve_mutation_intent(
        self,
        mutation_id: str,
        *,
        actor: str = "",
        actor_id: str = "",
        actor_type: str = "",
    ) -> ExecutionOutcome:
        record = self.mutation_journal.get(mutation_id)
        if record is None:
            raise PlaybookExecutionError(
                "MUTATION_INTENT_NOT_FOUND",
                "Mutation intent was not prepared.",
                {"mutation_id": mutation_id},
            )
        return self.approve_execution_node(
            record.intent.execution_id,
            record.intent.node_id,
            actor=actor,
            actor_id=actor_id,
            actor_type=actor_type,
        )

    def reject_execution_node(
        self,
        execution_id: str,
        node_id: str,
        *,
        actor: str = "",
        actor_id: str = "",
        actor_type: str = "",
    ) -> ExecutionOutcome:
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
        rejected = self.approval_store.reject(
            execution_id, node_id, actor=actor, actor_id=actor_id, actor_type=actor_type
        )
        mutation_id = str(rejected.metadata.get("mutation_id") or "")
        if mutation_id:
            self.mutation_journal.record_failed(mutation_id, error_code="APPROVAL_REJECTED")
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
            self._compensate_downstream_failure(plan=plan, execution_id=execution_id, failed_nodes=failed)
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
            mutation_intent: MutationIntent | None = None
            handler = None
            if self.policy_engine is not None:
                approval = self.approval_store.get(context.execution_id, node.node_id)
                decision = self.policy_engine.evaluate(
                    execution_context=context,
                    plan_node=plan_node,
                    approval=approval,
                )
                if not decision.allowed and not decision.required_approval:
                    return NodeResult.failure(
                        decision.reason_code, "Runtime policy denied capability execution.", decision.metadata
                    )
                if decision.effective_permission and decision.effective_permission.mutation:
                    handler = self.handler_registry.resolve(plan_node.component_id, plan_node.capability)
                    mutation_policy = _effective_mutation_policy_for_handler(handler, node)
                    safety = validate_mutation_safety(
                        handler=handler,
                        requested_policy=mutation_policy,
                        idempotency_key="preflight",
                    )
                    if not safety.ready:
                        return NodeResult.failure(
                            safety.reason_code,
                            "Mutation safety policy blocked execution.",
                            _mutation_safety_metadata(safety),
                        )
                    mutation_intent = _prepare_mutation_intent(
                        context=context,
                        plan_node=plan_node,
                        input_data=input_data,
                        effective_policy=mutation_policy,
                        journal=self.mutation_journal,
                    )
                    safety = validate_mutation_safety(
                        handler=handler,
                        requested_policy=mutation_policy,
                        idempotency_key=mutation_intent.idempotency_key,
                    )
                    if not safety.ready:
                        return NodeResult.failure(
                            safety.reason_code,
                            "Mutation safety policy blocked execution.",
                            _mutation_safety_metadata(safety),
                        )
                    policy_metadata.update(_mutation_policy_metadata(mutation_policy))
                approval_required = decision.required_approval or (
                    mutation_policy.requires_approval if mutation_intent is not None else False
                )
                if approval_required and (approval is None or approval.status != ApprovalStatus.APPROVED.value):
                    approval_metadata = dict(decision.metadata)
                    if mutation_intent is not None:
                        approval_metadata.update(_mutation_intent_metadata(mutation_intent))
                        approval_metadata.update(policy_metadata)
                    existing_approval = self.approval_store.get(context.execution_id, node.node_id)
                    requested = self.approval_store.request(
                        execution_id=context.execution_id,
                        node_id=node.node_id,
                        capability_id=plan_node.capability,
                        metadata=approval_metadata,
                        replace_existing=_approval_requires_replacement(existing_approval, approval_metadata),
                    )
                    return NodeResult.wait(
                        {
                            "waiting": True,
                            "approval_id": requested.approval_id,
                            "mutation_id": mutation_intent.mutation_id if mutation_intent else "",
                        },
                        {
                            **approval_metadata,
                            "approval_id": requested.approval_id,
                            "approval_status": requested.status,
                            "waiting_reason": "approval_required",
                        },
                    )
                policy_metadata = decision.metadata
                if mutation_intent is not None:
                    policy_metadata = {**policy_metadata, **_mutation_policy_metadata(mutation_policy)}
                    mismatch = _approved_intent_mismatch(approval, mutation_intent)
                    if mismatch:
                        requested = self.approval_store.request(
                            execution_id=context.execution_id,
                            node_id=node.node_id,
                            capability_id=plan_node.capability,
                            metadata={**decision.metadata, **_mutation_intent_metadata(mutation_intent)},
                            replace_existing=True,
                        )
                        return NodeResult.wait(
                            {
                                "waiting": True,
                                "approval_id": requested.approval_id,
                                "mutation_id": mutation_intent.mutation_id,
                            },
                            {
                                **decision.metadata,
                                **_mutation_intent_metadata(mutation_intent),
                                "approval_id": requested.approval_id,
                                "approval_status": requested.status,
                                "waiting_reason": "approval_required",
                                "reason_code": "MUTATION_APPROVAL_MISMATCH",
                            },
                        )
                    applied = self.mutation_journal.find_by_idempotency_key(mutation_intent.idempotency_key)
                    if applied is not None and applied.state == MutationState.APPLIED.value and applied.receipt:
                        return NodeResult.success(
                            {
                                "mutation_receipt": applied.receipt.to_dict(),
                                "resource_ref": applied.receipt.resource_ref,
                                "idempotent_replay": True,
                            },
                            {
                                **policy_metadata,
                                **_mutation_intent_metadata(mutation_intent),
                                "mutation_replayed": True,
                            },
                        )
                    self.mutation_journal.mark_approved(
                        mutation_intent.mutation_id, approval_id=approval.approval_id if approval else ""
                    )
                    claim, claimed = self.mutation_journal.claim_applying(
                        mutation_intent.mutation_id, owner=context.execution_id
                    )
                    if not claimed:
                        if claim.state == MutationState.APPLIED.value and claim.receipt:
                            return NodeResult.success(
                                {
                                    "mutation_receipt": claim.receipt.to_dict(),
                                    "resource_ref": claim.receipt.resource_ref,
                                    "idempotent_replay": True,
                                },
                                {
                                    **policy_metadata,
                                    **_mutation_intent_metadata(mutation_intent),
                                    "mutation_replayed": True,
                                },
                            )
                        return NodeResult.failure(
                            "MUTATION_ALREADY_APPLYING",
                            "Mutation intent is already being applied.",
                            {**policy_metadata, **_mutation_intent_metadata(mutation_intent)},
                        )
                    input_data = _with_runtime_mutation(input_data, mutation_intent)
                    policy_metadata = {**policy_metadata, **_mutation_intent_metadata(mutation_intent)}
            handler = handler or self.handler_registry.resolve(plan_node.component_id, plan_node.capability)
            result = handler.execute(context=context, node=node, resolved_node=plan_node, input_data=input_data)
            if mutation_intent is not None:
                if result.status == NodeResultStatus.SUCCESS.value:
                    receipt = _mutation_receipt_from_result(result, mutation_intent)
                    self.mutation_journal.record_applied(receipt)
                    if "mutation_receipt" in result.output or "resource_ref" in result.output:
                        result = NodeResult(
                            status=result.status,
                            output={**result.output, "mutation_receipt": receipt.to_dict()},
                            metadata=result.metadata,
                            error_code=result.error_code,
                            error_message=result.error_message,
                        )
                elif result.status == NodeResultStatus.FAILURE.value:
                    self.mutation_journal.record_failed(
                        mutation_intent.mutation_id,
                        error_code=result.error_code or "CAPABILITY_EXECUTION_FAILED",
                    )
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

    def _compensate_downstream_failure(self, *, plan: ExecutionPlan, execution_id: str, failed_nodes: set[str]) -> None:
        context = self._contexts[execution_id]
        failed_index = min((index for index, node in enumerate(plan.nodes) if node.node_id in failed_nodes), default=-1)
        if failed_index <= 0:
            return
        for plan_node in reversed(plan.nodes[:failed_index]):
            if plan_node.kind != PlaybookNodeKind.CAPABILITY.value:
                continue
            if str((plan_node.config.get("compensation") or {}).get("mode") or "none") != "on_downstream_failure":
                continue
            output = context.node_outputs.get(plan_node.node_id) or {}
            receipt_payload = output.get("mutation_receipt")
            if not isinstance(receipt_payload, dict) or not receipt_payload:
                continue
            self._compensate_mutation_node(
                context=context,
                plan_node=plan_node,
                receipt=MutationReceipt.from_dict(receipt_payload),
            )

    def _compensate_mutation_node(
        self, *, context: ExecutionContext, plan_node: ExecutionPlanNode, receipt: MutationReceipt
    ) -> None:
        metadata: dict[str, Any] = {
            **_node_provenance(plan_node),
            "mutation_id": receipt.mutation_id,
            "resource_ref": receipt.resource_ref,
        }
        node_execution = self.ledger.create_node_execution(
            context.execution_id,
            f"{plan_node.node_id}.compensation",
            metadata=metadata,
        )
        self.ledger.record_node_transition(
            node_execution.node_execution_id,
            ExecutionState.RUNNING.value,
            actor="playbook_executor.compensate",
        )
        compensation: CompensationIntent | None = None
        try:
            approval = self.approval_store.get(context.execution_id, plan_node.node_id)
            if self.policy_engine is not None:
                decision = self.policy_engine.evaluate(
                    execution_context=context,
                    plan_node=plan_node,
                    approval=approval,
                )
                if not decision.allowed or decision.required_approval:
                    raise PlaybookExecutionError(
                        "COMPENSATION_BLOCKED_BY_POLICY",
                        "Runtime policy blocked compensation.",
                        decision.metadata,
                    )
                metadata.update(decision.metadata)
            compensation = _build_compensation_intent(context=context, plan_node=plan_node, receipt=receipt)
            self.mutation_journal.prepare_compensation(compensation)
            claim, claimed = self.mutation_journal.claim_compensating(
                compensation.compensation_id, owner=context.execution_id
            )
            if not claimed:
                if claim.state == CompensationState.COMPENSATED.value and claim.receipt:
                    self.ledger.record_node_transition(
                        node_execution.node_execution_id,
                        ExecutionState.SUCCEEDED.value,
                        actor="playbook_executor.compensate",
                        metadata={
                            **metadata,
                            "compensation_id": compensation.compensation_id,
                            "compensation_replayed": True,
                            "compensation_state": claim.state,
                        },
                    )
                    return
                raise PlaybookExecutionError(
                    "COMPENSATION_ALREADY_RUNNING",
                    "Compensation is already being applied.",
                    {"compensation_id": compensation.compensation_id, "compensation_state": claim.state},
                )
            handler = self.handler_registry.resolve(plan_node.component_id, plan_node.capability)
            if not isinstance(handler, CompensatableMutationHandler):
                raise PlaybookExecutionError(
                    "COMPENSATION_NOT_SUPPORTED",
                    "Mutation handler does not support private compensation.",
                )
            compensation_receipt = handler.compensate(receipt=receipt, context=context, compensation=compensation)
            self.mutation_journal.record_compensated(compensation_receipt)
            self.ledger.record_node_transition(
                node_execution.node_execution_id,
                ExecutionState.SUCCEEDED.value,
                actor="playbook_executor.compensate",
                metadata={
                    **metadata,
                    "compensation_id": compensation.compensation_id,
                    "compensation_state": CompensationState.COMPENSATED.value,
                    "resource_ref": compensation_receipt.resource_ref,
                    "verified": compensation_receipt.verified,
                },
            )
        except PlaybookExecutionError as exc:
            compensation_id = str(exc.details.get("compensation_id") or "")
            if not compensation_id and compensation is not None:
                compensation_id = compensation.compensation_id
            if compensation_id:
                self.mutation_journal.record_compensation_failed(compensation_id, error_code=exc.code)
            self.ledger.record_node_transition(
                node_execution.node_execution_id,
                ExecutionState.FAILED.value,
                actor="playbook_executor.compensate",
                error_code=exc.code,
                error_message=exc.user_message,
                metadata={**metadata, **exc.details, "compensation_state": CompensationState.FAILED.value},
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


def _prepare_mutation_intent(
    *,
    context: ExecutionContext,
    plan_node: ExecutionPlanNode,
    input_data: dict[str, Any],
    effective_policy: MutationPolicy,
    journal: MutationJournal,
) -> MutationIntent:
    normalized = canonical_mutation_input(_intent_input(input_data, plan_node, effective_policy))
    fingerprint = mutation_input_fingerprint(normalized)
    mutation_id = build_mutation_id(
        execution_id=context.execution_id,
        node_id=plan_node.node_id,
        capability_id=plan_node.capability,
        component_id=plan_node.component_id,
        install_id=plan_node.install_id,
        input_fingerprint=fingerprint,
    )
    idempotency_key = build_mutation_idempotency_key(
        deployment_id=context.deployment_id,
        execution_id=context.execution_id,
        node_id=plan_node.node_id,
        trigger_idempotency_key=context.trigger_event.idempotency_key
        or context.trigger_event.external_event_id
        or context.trigger_event.event_id,
        input_fingerprint=fingerprint,
    )
    intent = MutationIntent(
        mutation_id=mutation_id,
        execution_id=context.execution_id,
        node_id=plan_node.node_id,
        capability_id=plan_node.capability,
        component_id=plan_node.component_id,
        install_id=plan_node.install_id,
        normalized_input=normalized,
        input_fingerprint=fingerprint,
        idempotency_key=idempotency_key,
    )
    return journal.prepare_intent(intent).intent


def _mutation_intent_metadata(intent: MutationIntent) -> dict[str, Any]:
    return {
        "input_fingerprint": intent.input_fingerprint,
        "mutation_id": intent.mutation_id,
        "mutation_idempotency_key": intent.idempotency_key,
    }


def _intent_input(
    input_data: dict[str, Any], plan_node: ExecutionPlanNode, effective_policy: MutationPolicy
) -> dict[str, Any]:
    compensation = dict(plan_node.config.get("compensation") or {})
    return {
        **input_data,
        "_compensation": {"mode": str(compensation.get("mode") or "none")},
        "_mutation_policy": effective_policy.to_dict(),
        "_mutation_policy_fingerprint": effective_policy.fingerprint(),
    }


def _effective_mutation_policy_for_handler(handler: object, node: PlaybookNode) -> MutationPolicy:
    minimum = getattr(handler, "mutation_policy", None)
    if not isinstance(minimum, MutationPolicy):
        component_id = str(getattr(handler, "component_id", ""))
        if component_id.startswith("test-"):
            minimum = MutationPolicy(
                requires_approval=False,
                idempotency_required=False,
                readback=ReadbackPolicy.UNAVAILABLE.value,
                compensation="unavailable",
                recovery=RecoveryPolicy.UNRECOVERABLE.value,
            )
        else:
            raise PlaybookExecutionError(
                "BLOCKED_POLICY_MISSING",
                "Production mutation handler does not declare a mutation policy.",
            )
    requested = requested_mutation_policy_from_config(node.config, minimum)
    safety = validate_mutation_safety(handler=handler, requested_policy=requested, idempotency_key="preflight")
    if not safety.ready:
        raise PlaybookExecutionError(
            safety.reason_code,
            "Mutation safety policy blocked execution.",
            _mutation_safety_metadata(safety),
        )
    assert safety.effective_policy is not None
    return safety.effective_policy


def _mutation_policy_metadata(policy: MutationPolicy) -> dict[str, Any]:
    return {
        "mutation_policy": policy.to_dict(),
        "mutation_policy_fingerprint": policy.fingerprint(),
    }


def _mutation_safety_metadata(safety: Any) -> dict[str, Any]:
    payload = safety.to_dict() if hasattr(safety, "to_dict") else {}
    payload["reason_code"] = getattr(safety, "reason_code", "")
    return payload


def _approval_requires_replacement(approval: ApprovalRecord | None, metadata: dict[str, Any]) -> bool:
    if approval is None:
        return False
    mutation_id = str(metadata.get("mutation_id") or "")
    if not mutation_id:
        return False
    return str(approval.metadata.get("input_fingerprint") or "") != str(metadata.get("input_fingerprint") or "")


def _approved_intent_mismatch(approval: ApprovalRecord | None, intent: MutationIntent) -> bool:
    if approval is None or approval.status != ApprovalStatus.APPROVED.value:
        return False
    return str(approval.metadata.get("input_fingerprint") or "") != intent.input_fingerprint


def _with_runtime_mutation(input_data: dict[str, Any], intent: MutationIntent) -> dict[str, Any]:
    return {
        **input_data,
        "_runtime": {
            "idempotency_key": intent.idempotency_key,
            "input_fingerprint": intent.input_fingerprint,
            "mutation_id": intent.mutation_id,
        },
    }


def _build_compensation_intent(
    *, context: ExecutionContext, plan_node: ExecutionPlanNode, receipt: MutationReceipt
) -> CompensationIntent:
    fingerprint_payload = {
        "mode": str((plan_node.config.get("compensation") or {}).get("mode") or "none"),
        "mutation_id": receipt.mutation_id,
        "resource_ref": receipt.resource_ref,
        "result_fingerprint": receipt.result_fingerprint,
    }
    compensation_fingerprint = mutation_input_fingerprint(fingerprint_payload)
    compensation_id = build_compensation_id(
        original_mutation_id=receipt.mutation_id,
        resource_ref=receipt.resource_ref,
        compensation_fingerprint=compensation_fingerprint,
    )
    return CompensationIntent(
        compensation_id=compensation_id,
        original_mutation_id=receipt.mutation_id,
        execution_id=context.execution_id,
        node_id=plan_node.node_id,
        capability_id=plan_node.capability,
        component_id=plan_node.component_id,
        install_id=plan_node.install_id,
        resource_ref=receipt.resource_ref,
        compensation_fingerprint=compensation_fingerprint,
        idempotency_key=build_compensation_idempotency_key(
            original_mutation_id=receipt.mutation_id,
            resource_ref=receipt.resource_ref,
        ),
    )


def _mutation_receipt_from_result(result: NodeResult, intent: MutationIntent) -> MutationReceipt:
    receipt_payload = result.output.get("mutation_receipt")
    if isinstance(receipt_payload, dict) and receipt_payload:
        return MutationReceipt.from_dict(receipt_payload)
    result_payload = {key: value for key, value in result.output.items() if key != "mutation_receipt"}
    return MutationReceipt(
        mutation_id=intent.mutation_id,
        capability_id=intent.capability_id,
        component_id=intent.component_id,
        resource_ref=str(result.output.get("resource_ref") or f"runtime-mutation:{intent.mutation_id}"),
        applied_at=str(result.metadata.get("applied_at") or ""),
        idempotency_key=intent.idempotency_key,
        result_fingerprint=mutation_input_fingerprint(result_payload),
        install_id=intent.install_id,
        metadata={},
    )


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
