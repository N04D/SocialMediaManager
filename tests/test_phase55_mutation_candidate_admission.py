from __future__ import annotations

from typing import Any

import pytest
from publication_git_mutation_admission import (
    WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
    website_article_publish_admission,
)
from publication_git_runtime_handlers import (
    GIT_WEBSITE_COMPONENT_ID,
    register_and_activate_website_publish,
    website_article_publish_candidate,
)
from runtime_foundation_mappings import phase41_component_manifests
from src.core.runtime.candidates import (
    MutationHandlerCandidate,
    ProductionMutationActivationResult,
    admit_and_register_mutation,
    compute_candidate_evidence_fingerprint,
)
from src.core.runtime.capabilities import CapabilityDescriptor, CapabilityMode
from src.core.runtime.components import ComponentManifest
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.handlers import CapabilityHandler, CapabilityHandlerRegistry
from src.core.runtime.installs import ComponentBinding, Install, InstallGrants
from src.core.runtime.mutation_policies import (
    CompensationPolicy,
    MutationPolicy,
    ReadbackPolicy,
    RecoveryPolicy,
)


def _git_component() -> ComponentManifest:
    manifests = {m.component_id: m for m in phase41_component_manifests()}
    return manifests[GIT_WEBSITE_COMPONENT_ID]


def _admitted_install() -> Install:
    return Install(
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
        ),
    )


def test_candidate_inspection_does_not_register_in_registry() -> None:
    registry = CapabilityHandlerRegistry()
    component = _git_component()
    resolver = lambda iid: None

    candidate = website_article_publish_candidate(repository_resolver=resolver)

    # Inspect candidate and admission without touch registry
    assert candidate.component_id == GIT_WEBSITE_COMPONENT_ID
    assert candidate.capability_id == WEBSITE_ARTICLE_PUBLISH_CAPABILITY
    with pytest.raises(PlaybookExecutionError) as exc_info:
        registry.resolve(GIT_WEBSITE_COMPONENT_ID, WEBSITE_ARTICLE_PUBLISH_CAPABILITY)
    assert exc_info.value.code == "HANDLER_NOT_FOUND"

    admission_result = website_article_publish_admission(
        component=component,
        install=_admitted_install(),
        candidate=candidate,
    )
    assert admission_result.status == "ADMITTED"
    assert admission_result.admitted

    # Handler still NOT executable in registry before activation!
    with pytest.raises(PlaybookExecutionError) as exc_info2:
        registry.resolve(GIT_WEBSITE_COMPONENT_ID, WEBSITE_ARTICLE_PUBLISH_CAPABILITY)
    assert exc_info2.value.code == "HANDLER_NOT_FOUND"


def test_controlled_activation_registers_handler() -> None:
    registry = CapabilityHandlerRegistry()
    component = _git_component()
    install = _admitted_install()
    resolver = lambda iid: None

    activation_result = register_and_activate_website_publish(
        registry,
        component=component,
        install=install,
        repository_resolver=resolver,
    )

    assert activation_result.status == "ADMITTED"
    assert activation_result.activated
    assert activation_result.handler is not None

    # Now handler is executable from registry!
    resolved_handler = registry.resolve(GIT_WEBSITE_COMPONENT_ID, WEBSITE_ARTICLE_PUBLISH_CAPABILITY)
    assert resolved_handler is not None
    assert resolved_handler.component_id == GIT_WEBSITE_COMPONENT_ID
    assert resolved_handler.capability_id == WEBSITE_ARTICLE_PUBLISH_CAPABILITY


def test_fingerprint_stale_blocks_activation() -> None:
    registry = CapabilityHandlerRegistry()
    component = _git_component()
    install = _admitted_install()

    original_candidate = website_article_publish_candidate(repository_resolver=lambda iid: None)
    initial_fingerprint = original_candidate.fingerprint()

    # Tampered candidate with different identity or policy
    tampered_candidate = MutationHandlerCandidate(
        component_id=GIT_WEBSITE_COMPONENT_ID,
        capability_id=WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
        build_handler=original_candidate.build_handler,
        mutation_policy=MutationPolicy(
            requires_approval=False,  # Policy tampered!
            idempotency_required=True,
            readback=ReadbackPolicy.REQUIRED.value,
            compensation=CompensationPolicy.UNAVAILABLE.value,
            recovery=RecoveryPolicy.MANUAL.value,
        ),
        handler_identity="tampered_identity",
    )

    # Admission evaluator that returns ADMITTED with stale fingerprint
    def mock_evaluator(*, component: Any, install: Any, candidate: Any) -> Any:
        class DummyResult:
            status = "ADMITTED"
            reasons = ()
            metadata = {"evidence_fingerprint": initial_fingerprint}  # Fingerprint mismatch!

        return DummyResult()

    result = admit_and_register_mutation(
        candidate=tampered_candidate,
        component=component,
        install=install,
        registry=registry,
        admission_evaluator=mock_evaluator,
    )

    assert result.status == "ADMISSION_STALE"
    assert not result.activated
    with pytest.raises(PlaybookExecutionError) as exc_info:
        registry.resolve(GIT_WEBSITE_COMPONENT_ID, WEBSITE_ARTICLE_PUBLISH_CAPABILITY)
    assert exc_info.value.code == "HANDLER_NOT_FOUND"


def test_caller_supplied_admitted_flag_forbidden() -> None:
    registry = CapabilityHandlerRegistry()
    component = _git_component()
    # Unadmitted install missing permissions
    unadmitted_install = Install(
        install_id="unadmitted",
        workspace_id="local",
        provider="github",
        account_ref="unadmitted_repo",
        grants=InstallGrants(allowed_capabilities=(), allow_mutations=False),
    )

    activation_result = register_and_activate_website_publish(
        registry,
        component=component,
        install=unadmitted_install,
        repository_resolver=lambda iid: None,
    )

    assert activation_result.status == "BLOCKED"
    assert not activation_result.activated
    assert "BLOCKED_CAPABILITY_NOT_GRANTED" in activation_result.reasons
    with pytest.raises(PlaybookExecutionError) as exc_info:
        registry.resolve(GIT_WEBSITE_COMPONENT_ID, WEBSITE_ARTICLE_PUBLISH_CAPABILITY)
    assert exc_info.value.code == "HANDLER_NOT_FOUND"
