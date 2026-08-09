from __future__ import annotations

from dataclasses import dataclass

import pytest

from publication_calendar_runtime_handlers import CalendarEventCreateHandler
from src.core.runtime import (
    CompensationPolicy,
    MutationPolicy,
    ReadbackPolicy,
    RecoveryPolicy,
    mutation_policy_fingerprint,
    resolve_effective_mutation_policy,
    validate_mutation_safety,
)
from tests.test_phase48_production_mutation import calendar_stack  # noqa: F401


@dataclass
class PolicyHandler:
    mutation_policy: MutationPolicy
    component_id: str = "test-policy-component"
    capability_id: str = "test.mutation.policy"


def test_mutation_policy_serialization_and_fingerprint_are_deterministic() -> None:
    policy = MutationPolicy(
        requires_approval=True,
        idempotency_required=True,
        readback=ReadbackPolicy.REQUIRED.value,
        compensation=CompensationPolicy.SUPPORTED.value,
        recovery=RecoveryPolicy.AUTOMATIC.value,
    )
    roundtrip = MutationPolicy.from_dict(policy.to_dict())

    assert roundtrip == policy
    assert mutation_policy_fingerprint(policy) == mutation_policy_fingerprint(roundtrip)
    assert len(policy.fingerprint()) == 64


def test_mutation_policy_rejects_unknown_enum_values() -> None:
    with pytest.raises(ValueError):
        MutationPolicy(
            requires_approval=True,
            idempotency_required=True,
            readback="sometimes",
        )


def test_effective_policy_allows_equal_and_stricter_requirements() -> None:
    minimum = MutationPolicy(
        False, True, ReadbackPolicy.OPTIONAL.value, CompensationPolicy.SUPPORTED.value, RecoveryPolicy.MANUAL.value
    )
    stricter = MutationPolicy(
        True, True, ReadbackPolicy.REQUIRED.value, CompensationPolicy.REQUIRED.value, RecoveryPolicy.AUTOMATIC.value
    )

    equal = resolve_effective_mutation_policy(minimum, minimum)
    tightened = resolve_effective_mutation_policy(minimum, stricter)

    assert equal.ready is True
    assert tightened.ready is True
    assert tightened.effective_policy == stricter


def test_effective_policy_rejects_downgrade_and_incompatible_compensation() -> None:
    minimum = MutationPolicy(
        True, True, ReadbackPolicy.REQUIRED.value, CompensationPolicy.UNAVAILABLE.value, RecoveryPolicy.MANUAL.value
    )
    weakened = MutationPolicy(
        False, True, ReadbackPolicy.REQUIRED.value, CompensationPolicy.UNAVAILABLE.value, RecoveryPolicy.MANUAL.value
    )
    compensation_required = MutationPolicy(
        True, True, ReadbackPolicy.REQUIRED.value, CompensationPolicy.REQUIRED.value, RecoveryPolicy.MANUAL.value
    )

    assert resolve_effective_mutation_policy(minimum, weakened).reason_code == "POLICY_DOWNGRADE_REJECTED"
    assert resolve_effective_mutation_policy(minimum, compensation_required).reason_code == "BLOCKED_COMPENSATION"


def test_preflight_blocks_missing_policy_idempotency_readback_compensation_and_recovery() -> None:
    assert validate_mutation_safety(handler=object()).reason_code == "BLOCKED_POLICY_MISSING"

    idempotent = PolicyHandler(
        MutationPolicy(
            True,
            True,
            ReadbackPolicy.UNAVAILABLE.value,
            CompensationPolicy.UNAVAILABLE.value,
            RecoveryPolicy.UNRECOVERABLE.value,
        )
    )
    assert validate_mutation_safety(handler=idempotent).reason_code == "BLOCKED_IDEMPOTENCY"

    readback = PolicyHandler(
        MutationPolicy(
            True,
            False,
            ReadbackPolicy.REQUIRED.value,
            CompensationPolicy.UNAVAILABLE.value,
            RecoveryPolicy.MANUAL.value,
        )
    )
    assert validate_mutation_safety(handler=readback, idempotency_key="key").reason_code == "BLOCKED_READBACK"

    compensation = PolicyHandler(
        MutationPolicy(
            True,
            False,
            ReadbackPolicy.UNAVAILABLE.value,
            CompensationPolicy.REQUIRED.value,
            RecoveryPolicy.MANUAL.value,
        )
    )
    assert validate_mutation_safety(handler=compensation, idempotency_key="key").reason_code == "BLOCKED_COMPENSATION"

    recovery = PolicyHandler(
        MutationPolicy(
            True,
            False,
            ReadbackPolicy.UNAVAILABLE.value,
            CompensationPolicy.UNAVAILABLE.value,
            RecoveryPolicy.AUTOMATIC.value,
        )
    )
    assert validate_mutation_safety(handler=recovery, idempotency_key="key").reason_code == "BLOCKED_RECOVERY"


def test_calendar_create_declares_phase51_production_policy(calendar_stack) -> None:  # noqa: F811
    handler = CalendarEventCreateHandler(
        calendar_service=calendar_stack["calendar_service"],
        occurrence_repository=calendar_stack["scheduling"].occurrence_repository,
    )

    policy = handler.mutation_policy

    assert policy.requires_approval is True
    assert policy.idempotency_required is True
    assert policy.readback == ReadbackPolicy.REQUIRED.value
    assert policy.compensation == CompensationPolicy.SUPPORTED.value
    assert policy.recovery == RecoveryPolicy.AUTOMATIC.value
    assert validate_mutation_safety(handler=handler, idempotency_key="mutation:key").ready is True
