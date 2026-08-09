from __future__ import annotations

from publication_git_mutation_admission import (
    WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
    website_article_publish_admission,
)
from publication_git_runtime_handlers import (
    GIT_REPOSITORY_STATUS_READ_CAPABILITY,
    GIT_WEBSITE_COMPONENT_ID,
    register_git_runtime_handlers,
)
from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime import CapabilityHandlerRegistry, CapabilityMode
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.mutation_policies import CompensationPolicy, ReadbackPolicy, RecoveryPolicy


def _git_component():
    return next(item for item in phase41_component_manifests() if item.component_id == GIT_WEBSITE_COMPONENT_ID)


def _git_install():
    return next(item for item in phase41_sample_installs() if item.install_id == "github-don-website")


def test_phase52_selects_website_article_publish_as_candidate_semantics() -> None:
    component = _git_component()
    capability = component.capability(WEBSITE_ARTICLE_PUBLISH_CAPABILITY)

    assert capability is not None
    assert capability.mode == CapabilityMode.WRITE.value
    assert component.capability("github.file.write") is not None


def test_phase52_admission_is_blocked_with_structured_reasons() -> None:
    result = website_article_publish_admission(component=_git_component(), install=_git_install())

    assert result.status == "BLOCKED"
    assert not result.admitted
    assert "BLOCKED_COMPONENT_PERMISSION_MISMATCH" not in result.reasons
    assert "BLOCKED_UNCONTROLLED_GIT_OPERATION" not in result.reasons
    assert "BLOCKED_REMOTE_EGRESS_POLICY" not in result.reasons
    assert "BLOCKED_IDEMPOTENCY" in result.reasons
    assert "BLOCKED_READBACK" in result.reasons
    assert "BLOCKED_RECOVERY" in result.reasons


def test_phase52_candidate_policy_is_conservative_but_not_admitted() -> None:
    result = website_article_publish_admission(component=_git_component(), install=_git_install())

    assert result.mutation_policy is not None
    assert result.mutation_policy.requires_approval is True
    assert result.mutation_policy.idempotency_required is True
    assert result.mutation_policy.readback == ReadbackPolicy.REQUIRED.value
    assert result.mutation_policy.compensation == CompensationPolicy.UNAVAILABLE.value
    assert result.mutation_policy.recovery == RecoveryPolicy.MANUAL.value
    assert result.metadata["handler_registered"] is False


def test_phase52_admission_documents_publish_side_effect_lifecycle() -> None:
    result = website_article_publish_admission(component=_git_component(), install=_git_install())
    operations = {item["step"]: item for item in result.inspected_operations}

    assert operations["write_target_file"]["side_effect"] == "filesystem write"
    assert operations["git_add_exact_paths"]["side_effect"] == "git index mutation"
    assert operations["git_commit"]["side_effect"] == "local Git history mutation"
    assert operations["git_push"]["side_effect"] == "remote Git mutation"
    assert "push may succeed before journal receipt" in operations["git_push"]["crash_ambiguity"]


def test_phase52_git_runtime_handler_remains_read_only() -> None:
    registry = CapabilityHandlerRegistry()
    register_git_runtime_handlers(registry, repositories_by_install_id={})

    assert registry.resolve(GIT_WEBSITE_COMPONENT_ID, GIT_REPOSITORY_STATUS_READ_CAPABILITY)
    try:
        registry.resolve(GIT_WEBSITE_COMPONENT_ID, WEBSITE_ARTICLE_PUBLISH_CAPABILITY)
    except PlaybookExecutionError as exc:
        assert exc.code == "HANDLER_NOT_FOUND"
    else:  # pragma: no cover
        raise AssertionError("website.article.publish must not be registered in Phase 52")


def test_phase52_manifest_and_install_stay_read_only_for_generic_runtime() -> None:
    component = _git_component()
    install = _git_install()

    assert component.permissions["filesystem"]["read"] == ["repository"]
    assert component.permissions["subprocess"]["policy"] == "named-operations"
    assert WEBSITE_ARTICLE_PUBLISH_CAPABILITY not in install.grants.allowed_capabilities
    assert install.grants.allow_mutations is False
