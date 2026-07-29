"""Deterministic GitHub CI operator flow scenarios."""

from __future__ import annotations

from pathlib import Path

from integrations.ci_artifacts.fake_source import fake_github_source
from integrations.managed_secrets.fixtures import encrypted_facade
from src.core.certification_evidence.service import CertificationEvidenceService
from src.core.ci_artifacts.operator_flow import CiEvidenceOperatorService
from src.core.ci_artifacts.service import CiArtifactImportService
from src.core.managed_secrets.service import PurposeBoundSecretReader
from src.core.trusted_signing.service import TrustedSignerService
from src.providers.ci.github_actions.origins import default_github_origin_payload

PHASE31_COMMIT = "94d4407bfe7e6383af990e93d843f0e1e43d48e0"


def build_operator_stack(root: Path, *, commit: str = PHASE31_COMMIT) -> dict:
    database_path = root / "app.sqlite"
    facade = encrypted_facade(database_path, root / "vault")
    facade.authz.grant_role("alice", "secret_operator")
    facade.authz.grant_role("bob", "security_approver")
    github_secret = facade.create_reference(
        secret_type="github_read_only_token",
        display_name="GitHub Actions read credential",
        purpose_allowlist=("github_actions_read",),
        created_by="alice",
    )["secret"]
    facade.set_value(github_secret["id"], b"github-token-synthetic-read-only", actor="alice")
    facade.validate(github_secret["id"])
    facade.approve(
        github_secret["id"],
        action_type="approve_github_credential",
        requester_id="alice",
        approver_id="bob",
    )
    facade.activate(github_secret["id"], action_type="approve_github_credential")

    signer_secret = facade.create_reference(
        secret_type="ed25519_private_key",
        display_name="Managed host signer",
        purpose_allowlist=("certification_signing",),
        created_by="alice",
    )["secret"]
    facade.generate_ed25519(signer_secret["id"], actor="alice")
    facade.validate(signer_secret["id"])
    facade.approve(
        signer_secret["id"],
        action_type="activate_production_signer",
        requester_id="alice",
        approver_id="bob",
    )
    facade.activate(signer_secret["id"], action_type="activate_production_signer")
    signer_reader = PurposeBoundSecretReader(facade, purpose="certification_signing", consumer="trusted_signer")
    signer_service = TrustedSignerService(database_path=database_path, secret_reader=signer_reader)
    signer_service.enroll(
        signer_id="signer.phase31.managed",
        display_name="Phase 31 managed host signer",
        private_key_secret_reference=signer_secret["id"],
        operator_id="alice",
    )
    signer_service.approve("signer.phase31.managed", reviewer_id="bob", requester_id="alice")
    signer_service.activate("signer.phase31.managed")

    evidence = CertificationEvidenceService(database_path=database_path)
    staging_run_id = evidence.staging.deterministic_certification()["run"]["id"]
    package_record = evidence.create_from_staging_run(staging_run_id, source_type="ci", commit_sha=commit)["evidence"]
    package_bytes = evidence.export_evidence(package_record["package_id"])["data"]

    github_reader = PurposeBoundSecretReader(facade, purpose="github_actions_read", consumer="github_actions")
    source = fake_github_source(package_bytes, commit_sha=commit, secret_reader=github_reader)
    origin = default_github_origin_payload()
    origin["credential_secret_reference"] = github_secret["id"]
    source.origins[origin["id"]]["credential_secret_reference"] = github_secret["id"]
    ci_service = CiArtifactImportService(database_path=database_path, source=source, signer_service=signer_service)
    ci_service.register_origin(origin)
    operator = CiEvidenceOperatorService(database_path=database_path, import_service=ci_service)
    return {
        "database_path": database_path,
        "facade": facade,
        "signer_service": signer_service,
        "ci_service": ci_service,
        "operator": operator,
        "source": source,
        "origin": origin,
        "commit": commit,
        "run_id": "1001",
        "run_attempt": 1,
        "artifact_id": "5001",
        "signer_id": "signer.phase31.managed",
        "package_id": package_record["package_id"],
    }


def complete_promoted_flow(stack: dict) -> dict:
    operator = stack["operator"]
    flow = operator.create_flow(
        origin_reference_id=stack["origin"]["id"], expected_commit_sha=stack["commit"], actor="alice"
    )["flow"]
    operator.select_run(flow["id"], run_id=stack["run_id"], run_attempt=stack["run_attempt"])
    operator.select_artifact(flow["id"], artifact_id=stack["artifact_id"])
    dry = operator.dry_run_import(flow["id"])["dry_run"]
    executed = operator.execute_import(dry["id"], confirmed_by="alice", signer_id=stack["signer_id"])
    request_id = executed["flow"]["import_request_id"]
    operator.review_import(request_id, reviewer_id="bob", requester_id="alice")
    promoted = operator.promote_import(request_id, promoted_by="alice")
    return {"flow": promoted["flow"], "request_id": request_id, "promotion": promoted["promotion"]}


__all__ = ["PHASE31_COMMIT", "build_operator_stack", "complete_promoted_flow"]
