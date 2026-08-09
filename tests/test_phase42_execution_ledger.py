from __future__ import annotations

import unittest

from src.core.runtime import (
    ExecutionLedgerError,
    ExecutionRecord,
    ExecutionState,
    InMemoryExecutionLedger,
)


def execution_record(**overrides) -> ExecutionRecord:
    payload = {
        "deployment_id": "deploy-a",
        "playbook_id": "example.simple",
        "playbook_version": "1.0.0",
        "trigger_event_id": "evt_1",
        "correlation_id": "corr-1",
        "trace_id": "trace-1",
        "idempotency_key": "deploy-a:event-1",
    }
    payload.update(overrides)
    return ExecutionRecord(**payload)


class Phase42ExecutionLedgerTests(unittest.TestCase):
    def test_create_execution_preserves_correlation_trace_and_idempotency(self) -> None:
        ledger = InMemoryExecutionLedger()
        record = ledger.create_execution(execution_record())

        self.assertEqual(record.state, ExecutionState.PENDING.value)
        self.assertEqual(record.correlation_id, "corr-1")
        self.assertEqual(record.trace_id, "trace-1")
        self.assertEqual(record.idempotency_key, "deploy-a:event-1")
        self.assertEqual(ledger.get_execution(record.execution_id), record)

    def test_idempotency_key_returns_existing_execution(self) -> None:
        ledger = InMemoryExecutionLedger()
        first = ledger.create_execution(execution_record())
        second = ledger.create_execution(execution_record(execution_id="exec_different"))

        self.assertEqual(second.execution_id, first.execution_id)

    def test_state_transitions_and_history_retained(self) -> None:
        ledger = InMemoryExecutionLedger()
        record = ledger.create_execution(execution_record())

        running = ledger.record_transition(record.execution_id, ExecutionState.RUNNING.value, actor="worker")
        succeeded = ledger.record_transition(running.execution_id, ExecutionState.SUCCEEDED.value, actor="worker")

        self.assertEqual(succeeded.state, ExecutionState.SUCCEEDED.value)
        self.assertTrue(succeeded.started_at)
        self.assertTrue(succeeded.finished_at)
        transitions = ledger.list_transitions(record_id=record.execution_id)
        self.assertEqual([transition.to_state for transition in transitions], ["pending", "running", "succeeded"])
        self.assertEqual(transitions[-1].actor, "worker")

    def test_illegal_transition_and_terminal_restart_rejected(self) -> None:
        ledger = InMemoryExecutionLedger()
        record = ledger.create_execution(execution_record())

        with self.assertRaises(ExecutionLedgerError) as raised:
            ledger.record_transition(record.execution_id, ExecutionState.SUCCEEDED.value)
        self.assertEqual(raised.exception.code, "ledger.invalid_transition")

        running = ledger.record_transition(record.execution_id, ExecutionState.RUNNING.value)
        succeeded = ledger.record_transition(running.execution_id, ExecutionState.SUCCEEDED.value)
        with self.assertRaises(ExecutionLedgerError) as terminal:
            ledger.record_transition(succeeded.execution_id, ExecutionState.RUNNING.value)
        self.assertEqual(terminal.exception.code, "ledger.terminal_transition")

    def test_waiting_to_running_allowed(self) -> None:
        ledger = InMemoryExecutionLedger()
        record = ledger.create_execution(execution_record())

        ledger.record_transition(record.execution_id, ExecutionState.RUNNING.value)
        waiting = ledger.record_transition(record.execution_id, ExecutionState.WAITING.value)
        resumed = ledger.record_transition(record.execution_id, ExecutionState.RUNNING.value)

        self.assertEqual(waiting.state, ExecutionState.WAITING.value)
        self.assertEqual(resumed.state, ExecutionState.RUNNING.value)

    def test_node_executions_attempt_counters_and_transitions(self) -> None:
        ledger = InMemoryExecutionLedger()
        execution = ledger.create_execution(execution_record())
        first = ledger.create_node_execution(execution.execution_id, "write")
        second = ledger.create_node_execution(execution.execution_id, "write")

        self.assertEqual(first.attempt, 1)
        self.assertEqual(second.attempt, 2)

        running = ledger.record_node_transition(first.node_execution_id, ExecutionState.RUNNING.value)
        failed = ledger.record_node_transition(
            running.node_execution_id,
            ExecutionState.FAILED.value,
            error_code="component.unavailable",
            error_message="Component unavailable.",
        )

        self.assertEqual(failed.state, ExecutionState.FAILED.value)
        self.assertEqual(failed.error_code, "component.unavailable")
        self.assertEqual([node.attempt for node in ledger.list_node_executions(execution.execution_id)], [1, 2])

    def test_missing_records_and_bad_attempts_fail_cleanly(self) -> None:
        ledger = InMemoryExecutionLedger()

        with self.assertRaises(ExecutionLedgerError):
            ledger.record_transition("missing", ExecutionState.RUNNING.value)
        with self.assertRaises(ExecutionLedgerError):
            ledger.create_node_execution("missing", "node")

    def test_ledger_rejects_secret_shaped_metadata(self) -> None:
        with self.assertRaises(ExecutionLedgerError):
            ExecutionRecord(
                deployment_id="deploy-a",
                playbook_id="example.simple",
                playbook_version="1.0.0",
                metadata={"access_" + "token": "redacted-placeholder"},
            )


if __name__ == "__main__":
    unittest.main()
