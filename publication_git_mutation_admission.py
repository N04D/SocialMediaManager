from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from publication_git_runtime_handlers import GIT_WEBSITE_COMPONENT_ID
from src.core.runtime.capabilities import CapabilityMode
from src.core.runtime.components import ComponentManifest
from src.core.runtime.installs import Install
from src.core.runtime.mutation_policies import (
    CompensationPolicy,
    MutationPolicy,
    ReadbackPolicy,
    RecoveryPolicy,
)

WEBSITE_ARTICLE_PUBLISH_CAPABILITY = "website.article.publish"


@dataclass(frozen=True)
class ProductionMutationAdmissionResult:
    capability_id: str
    component_id: str
    status: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    mutation_policy: MutationPolicy | None = None
    inspected_operations: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def admitted(self) -> bool:
        return self.status == "ADMITTED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "component_id": self.component_id,
            "inspected_operations": list(self.inspected_operations),
            "metadata": dict(self.metadata),
            "mutation_policy": self.mutation_policy.to_dict() if self.mutation_policy else {},
            "reasons": list(self.reasons),
            "status": self.status,
        }


def website_article_publish_admission(
    *,
    component: ComponentManifest,
    install: Install | None = None,
) -> ProductionMutationAdmissionResult:
    """Assess the existing Markdown Website publish path for runtime mutation admission.

    This function is intentionally conservative. It reports whether the current
    production integration already satisfies the Phase 51 safety contracts; it
    does not register a handler or upgrade permissions.
    """

    reasons: list[str] = []
    capability = component.capability(WEBSITE_ARTICLE_PUBLISH_CAPABILITY)
    if capability is None:
        reasons.append("BLOCKED_CAPABILITY_MISSING")
    elif capability.mode != CapabilityMode.WRITE.value:
        reasons.append("BLOCKED_CAPABILITY_MODE")

    permissions = dict(component.permissions or {})
    filesystem = dict(permissions.get("filesystem") or {})
    subprocess = dict(permissions.get("subprocess") or {})
    network = dict(permissions.get("network") or component.network_policy or {})

    if str(filesystem.get("mode") or "none") != "write":
        reasons.append("BLOCKED_COMPONENT_PERMISSION_MISMATCH")
    if str(subprocess.get("policy") or "") != "website-publish-git":
        reasons.append("BLOCKED_UNCONTROLLED_GIT_OPERATION")
    if bool(network.get("required", False)) is False:
        reasons.append("BLOCKED_REMOTE_EGRESS_POLICY")

    if install is not None:
        if not install.grants.allows_capability(WEBSITE_ARTICLE_PUBLISH_CAPABILITY):
            reasons.append("BLOCKED_CAPABILITY_NOT_GRANTED")
        if not install.grants.allow_mutations:
            reasons.append("BLOCKED_MUTATION_NOT_GRANTED")
        if not install.grants.allow_filesystem:
            reasons.append("BLOCKED_FILESYSTEM_NOT_GRANTED")
        if not install.grants.allow_subprocess:
            reasons.append("BLOCKED_SUBPROCESS_NOT_GRANTED")

    reasons.extend(
        (
            "BLOCKED_IDEMPOTENCY",
            "BLOCKED_READBACK",
            "BLOCKED_RECOVERY",
        )
    )

    policy = MutationPolicy(
        requires_approval=True,
        idempotency_required=True,
        readback=ReadbackPolicy.REQUIRED.value,
        compensation=CompensationPolicy.UNAVAILABLE.value,
        recovery=RecoveryPolicy.MANUAL.value,
        metadata={"admission": "blocked_until_runtime_publish_recovery_exists"},
    )
    return ProductionMutationAdmissionResult(
        capability_id=WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
        component_id=component.component_id,
        status="BLOCKED" if reasons else "ADMITTED",
        reasons=tuple(dict.fromkeys(reasons)),
        mutation_policy=policy,
        inspected_operations=_website_publish_operations(),
        metadata={
            "candidate": "Markdown Website article publication",
            "component_expected": GIT_WEBSITE_COMPONENT_ID,
            "handler_registered": False,
        },
    )


def _website_publish_operations() -> tuple[dict[str, Any], ...]:
    return (
        {
            "step": "render_markdown",
            "side_effect": "none",
            "idempotent": True,
            "readback_possible": True,
            "crash_ambiguity": "none",
        },
        {
            "step": "write_target_file",
            "side_effect": "filesystem write",
            "idempotent": "requires runtime idempotency journal",
            "readback_possible": True,
            "crash_ambiguity": "file may exist without commit",
        },
        {
            "step": "git_add_exact_paths",
            "side_effect": "git index mutation",
            "idempotent": "requires exact staged-set verification",
            "readback_possible": True,
            "crash_ambiguity": "index may remain staged",
        },
        {
            "step": "git_commit",
            "side_effect": "local Git history mutation",
            "idempotent": "requires commit lookup by approved intent",
            "readback_possible": True,
            "crash_ambiguity": "commit may exist before journal receipt",
        },
        {
            "step": "git_push",
            "side_effect": "remote Git mutation",
            "idempotent": "requires remote ref readback",
            "readback_possible": "not currently proven by generic runtime adapter",
            "crash_ambiguity": "push may succeed before journal receipt",
        },
    )
