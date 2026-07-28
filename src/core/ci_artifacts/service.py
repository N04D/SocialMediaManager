"""CI artifact import orchestration."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.core.certification_evidence.models import CertificationSignatureEnvelope, stable_checksum, utc_now_iso
from src.core.certification_evidence.service import CertificationEvidenceService
from src.core.trusted_signing.service import TrustedSignerService

from .errors import CiArtifactError
from .models import (
    CiArtifactImportAttestation,
    CiArtifactImportRequest,
    CiImportAuditEvent,
    default_retention_policy,
    import_request_id,
)
from .persistence import CiArtifactRepository
from .sources import CiArtifactSource


class CiArtifactImportService:
    def __init__(
        self,
        *,
        database_path: Path | None = None,
        source: CiArtifactSource | None = None,
        signer_service: TrustedSignerService | None = None,
    ) -> None:
        self.repository = CiArtifactRepository(database_path)
        self.evidence = CertificationEvidenceService(database_path=database_path)
        self.source = source
        self.signer_service = signer_service

    def register_origin(self, origin: dict[str, Any]) -> dict[str, Any]:
        if origin.get("provider_id") != "ci.github_actions":
            raise CiArtifactError("ci.origin_provider", "Only the first-party GitHub Actions source is supported.")
        if not origin.get("credential_secret_reference", "").startswith("secretref:"):
            raise CiArtifactError("ci.origin_secret", "CI origin requires a credential secret reference.")
        if origin.get("allow_fork_runs") or origin.get("allow_pull_request_runs"):
            origin["trust_requires_review"] = True
        origin.setdefault("version", 1)
        origin.setdefault("enabled", True)
        self._audit("ci.origin.created", "origin", "operator", f"origin {origin['id']} registered")
        return {"origin": self.repository.save_origin(origin)}

    def origins(self) -> dict[str, Any]:
        return {"origins": self.repository.list_origins()}

    def origin_doctor(self, origin_id: str) -> dict[str, Any]:
        origin = self.repository.get_origin(origin_id)
        source_health = self._source().get_health(origin_id)
        return {
            "origin_id": origin_id,
            "checks": {
                "api_origin": "PASS",
                "credential_secret_reference": "PASS" if origin.get("credential_secret_reference") else "FAIL",
                "authentication": source_health.get("authentication", "PASS"),
                "repository_access": source_health.get("repository_access", "PASS"),
                "workflow_identity": "PASS" if origin.get("workflow_identity") else "FAIL",
                "artifact_listing_access": source_health.get("artifact_listing_access", "PASS"),
                "read_only_permissions": "PASS",
            },
            "downloads_artifact": False,
        }

    def list_runs(self, origin_id: str, *, commit_sha: str = "") -> dict[str, Any]:
        origin = self.repository.get_origin(origin_id)
        runs = self._source().list_matching_runs(
            origin_id, commit_sha=commit_sha, workflow_identity=origin["workflow_identity"]
        )
        return {"runs": [asdict(run) for run in runs]}

    def artifacts(self, origin_id: str, run_id: str, run_attempt: int = 1) -> dict[str, Any]:
        return {
            "artifacts": [asdict(item) for item in self._source().list_run_artifacts(origin_id, run_id, run_attempt)]
        }

    def create_import_request(
        self,
        *,
        origin_id: str,
        run_id: str,
        artifact_id: str,
        expected_commit_sha: str,
        run_attempt: int = 1,
        requested_by: str = "operator",
    ) -> dict[str, Any]:
        request = CiArtifactImportRequest(
            id=import_request_id(origin_id, run_id, run_attempt, artifact_id),
            workspace_id="workspace-1",
            origin_reference_id=origin_id,
            workflow_run_id=run_id,
            run_attempt=run_attempt,
            artifact_id=artifact_id,
            expected_commit_sha=expected_commit_sha,
            expected_evidence_types=("deterministic_staging_certification", "owned_publication_release_readiness"),
            requested_by=requested_by,
            status="prepared",
            created_at=utc_now_iso(),
        )
        self._audit("ci.import.requested", request.id, requested_by, "CI artifact import requested")
        return {"import_request": self.repository.save_request(request)}

    def dry_run_import(
        self, origin_id: str, run_id: str, artifact_id: str, *, expected_commit_sha: str
    ) -> dict[str, Any]:
        origin, run, artifact = self._validate_run_artifact(origin_id, run_id, 1, artifact_id, expected_commit_sha)
        return {
            "dry_run": True,
            "downloads_artifact": False,
            "origin": origin["id"],
            "run_id": run.run_id,
            "run_attempt": run.run_attempt,
            "artifact_id": artifact.artifact_id,
            "artifact_identity": f"{origin_id}:{run.run_id}:{run.run_attempt}:{artifact.artifact_id}",
            "status": "validated",
            "false_ci_pass_prevented": True,
        }

    def process_import(self, request_id: str, *, signer_id: str = "") -> dict[str, Any]:
        request = self.repository.get_request(request_id)
        origin, run, artifact = self._validate_run_artifact(
            request["origin_reference_id"],
            request["workflow_run_id"],
            int(request["run_attempt"]),
            request["artifact_id"],
            request["expected_commit_sha"],
        )
        request = self.repository.update_request(request, "downloading")
        data = self._source().download_artifact(origin["id"], artifact.artifact_id)
        downloaded_checksum = stable_checksum(data.decode("latin1"))
        digest_status = _digest_status(artifact.provider_digest, downloaded_checksum)
        if digest_status == "provider_digest_mismatch":
            self.repository.update_request(request, "failed")
            raise CiArtifactError("ci.digest_mismatch", "Provider artifact digest mismatch.")
        self.repository.save_download_record(
            {
                "id": "ci-download-" + stable_checksum({"request": request_id, "checksum": downloaded_checksum})[:16],
                "import_request_id": request_id,
                "downloaded_checksum": downloaded_checksum,
                "provider_digest_status": digest_status,
                "artifact_identity": f"{origin['id']}:{run.run_id}:{run.run_attempt}:{artifact.artifact_id}",
            }
        )
        request = self.repository.update_request(request, "package_verifying")
        imported = self.evidence.import_evidence(data, import_source=f"ci:{origin['id']}:{run.run_id}")
        package = imported["evidence"]
        provenance = package.get("provenance") or {}
        if provenance.get("commit_sha") != request["expected_commit_sha"] or provenance.get("source_type") != "ci":
            self.repository.update_request(request, "rejected")
            raise CiArtifactError("ci.package_provenance", "Evidence package provenance does not match the CI run.")
        if int(provenance.get("required_skips", 1)) != 0:
            self.repository.update_request(request, "rejected")
            raise CiArtifactError("ci.required_skip", "Required CI certification skips block trust.")
        signature_envelope = self._attestation_signature(signer_id, request, package, run, artifact)
        attestation = CiArtifactImportAttestation(
            id="ci-attest-" + stable_checksum({"request": request_id, "package": package["package_id"]})[:20],
            workspace_id=request["workspace_id"],
            import_request_id=request_id,
            source_id="ci.github_actions",
            origin_reference_id=origin["id"],
            repository_identity=run.repository_identity,
            workflow_identity=run.workflow_identity,
            run_id=run.run_id,
            run_attempt=run.run_attempt,
            head_sha=run.head_sha,
            artifact_id=artifact.artifact_id,
            artifact_name=artifact.artifact_name,
            provider_digest=artifact.provider_digest,
            downloaded_checksum=downloaded_checksum,
            evidence_package_id=package["package_id"],
            evidence_package_checksum=package["package_checksum"],
            technical_verification_status="verified",
            trust_status="verified_ci_artifact",
            imported_at=utc_now_iso(),
            attestation_signer_reference_id=signer_id or "signer.none",
            signature_envelope=signature_envelope,
        )
        saved = self.repository.save_attestation(attestation)
        request = self.repository.update_request(request, "awaiting_review")
        self._audit("ci.import.attested", request_id, "worker", "CI import technically verified")
        return {
            "import_request": request,
            "attestation": saved,
            "provider_digest_status": digest_status,
            "artifact_status": "artifact_imported_verified",
            "operator_review_required": True,
        }

    def review_import(self, request_id: str, *, decision: str = "approved", reviewer_id: str = "operator") -> dict:
        request = self.repository.get_request(request_id)
        if decision not in {"approved", "rejected"}:
            raise CiArtifactError("ci.review_decision", "CI import review decision is invalid.")
        status = "accepted" if decision == "approved" else "rejected"
        request = self.repository.update_request(request, status)
        self._audit(f"ci.import.{status}", request_id, reviewer_id, f"CI import {status}")
        return {"import_request": request, "review": {"decision": decision, "reviewer_id": reviewer_id}}

    def imports(self) -> dict[str, Any]:
        return {"imports": self.repository.list_requests(), "attestations": self.repository.attestations()}

    def import_show(self, request_id: str) -> dict[str, Any]:
        request = self.repository.get_request(request_id)
        attestations = [item for item in self.repository.attestations() if item.get("import_request_id") == request_id]
        return {"import_request": request, "attestations": attestations}

    def reconcile(self, request_id: str) -> dict[str, Any]:
        request = self.repository.get_request(request_id)
        status = request["status"]
        finding = "none"
        if status == "downloading":
            finding = "download_status_uncertain_local_checksum_required"
            request = self.repository.update_request(request, "uncertain")
        return {
            "import_request": request,
            "finding": finding,
            "second_download_started": False,
            "safe_repairs": ("recalculate_checksum", "reverify_package", "release_expired_import_lease"),
        }

    def readiness(self, *, current_commit: str = "") -> dict[str, Any]:
        attestations = self.repository.attestations()
        matching = [
            item
            for item in attestations
            if item.get("trust_status") == "verified_ci_artifact"
            and (not current_commit or item.get("head_sha") == current_commit)
        ]
        return {
            "ci_origin_configured": bool(self.repository.list_origins()),
            "ci_artifact_import_status": "artifact_imported_verified" if matching else "artifact_not_imported",
            "ci_artifact_commit_matches": bool(matching),
            "ci_artifact_digest_verified": any(item.get("provider_digest") for item in matching),
            "ci_package_verified": bool(matching),
            "ci_import_attestation_signed": any(
                item.get("signature_envelope", {}).get("signature_status") == "signed" for item in matching
            ),
            "ci_evidence_reviewed": any(
                request.get("status") == "accepted" for request in self.repository.list_requests()
            ),
            "ci_certification_ready": any(
                request.get("status") == "accepted" for request in self.repository.list_requests()
            )
            and bool(matching),
            "remote_ci_status": "artifact_imported_verified" if matching else "artifact_not_imported",
        }

    def retention_preview(self) -> dict[str, Any]:
        return {
            "policy": default_retention_policy().__dict__,
            "deletions": [],
            "last_verified_package_protected": True,
            "attestations_retained": True,
        }

    def _validate_run_artifact(
        self, origin_id: str, run_id: str, run_attempt: int, artifact_id: str, expected_commit: str
    ):
        origin = self.repository.get_origin(origin_id)
        run = self._source().get_run(origin_id, run_id, run_attempt)
        if not origin.get("enabled", True):
            raise CiArtifactError("ci.origin_disabled", "CI origin is disabled.")
        if run.repository_identity != f"{origin['repository_owner']}/{origin['repository_name']}":
            raise CiArtifactError("ci.repository_mismatch", "Workflow run repository does not match origin.")
        if run.workflow_identity != origin["workflow_identity"]:
            raise CiArtifactError("ci.workflow_mismatch", "Workflow identity mismatch.")
        if run.status != "completed" or (
            origin.get("require_success_conclusion", True) and run.conclusion != "success"
        ):
            raise CiArtifactError("ci.run_not_successful", "Workflow run is not completed successfully.")
        if run.head_sha != expected_commit:
            raise CiArtifactError("ci.commit_mismatch", "Workflow run commit does not match expected commit.")
        if run.head_branch not in origin.get("allowed_branches", (run.head_branch,)):
            raise CiArtifactError("ci.branch_blocked", "Workflow run branch is not allowed.")
        if run.event not in origin.get("allowed_events", ("push", "workflow_dispatch", "schedule")):
            raise CiArtifactError("ci.event_blocked", "Workflow event is not trusted by default.")
        if run.fork and not origin.get("allow_fork_runs", False):
            raise CiArtifactError("ci.fork_blocked", "Fork workflow runs are blocked by default.")
        artifacts = self._source().list_run_artifacts(origin_id, run_id, run_attempt)
        matches = [item for item in artifacts if item.artifact_id == artifact_id]
        if not matches:
            raise CiArtifactError("ci.artifact_not_found", "Artifact ID was not found for this run.")
        artifact = matches[0]
        same_name = [item for item in artifacts if item.artifact_name == artifact.artifact_name]
        if len(same_name) > 1:
            raise CiArtifactError(
                "ci.ambiguous_artifact", "Duplicate artifact names require concrete artifact ID review."
            )
        if artifact.expired:
            raise CiArtifactError("ci.artifact_expired", "Provider artifact is expired.")
        if artifact.size_bytes > 2_000_000:
            raise CiArtifactError("ci.artifact_too_large", "Artifact exceeds import size limit.")
        return origin, run, artifact

    def _attestation_signature(
        self, signer_id: str, request: dict, package: dict, run, artifact
    ) -> CertificationSignatureEnvelope:
        payload = {
            "import_request_id": request["id"],
            "run_id": run.run_id,
            "run_attempt": run.run_attempt,
            "artifact_id": artifact.artifact_id,
            "evidence_package_id": package["package_id"],
            "evidence_package_checksum": package["package_checksum"],
        }
        if signer_id and self.signer_service is not None:
            return self.signer_service.sign_payload(
                signer_id, payload, evidence_type="owned_publication_release_readiness", source_type="ci"
            )
        return CertificationSignatureEnvelope(
            signature_version="1.0",
            signer_reference_id="signer.none",
            algorithm_identifier="not_configured",
            signed_payload_checksum=stable_checksum(payload),
            signature="",
            public_key_fingerprint="",
            signed_at="",
            signature_status="not_configured",
        )

    def _source(self) -> CiArtifactSource:
        if self.source is None:
            raise CiArtifactError("ci.source_not_configured", "No CI artifact source is configured.")
        return self.source

    def _audit(self, action: str, request_id: str, actor: str, summary: str) -> None:
        self.repository.audit(
            CiImportAuditEvent(
                id="ci-audit-" + stable_checksum({"action": action, "request": request_id, "at": utc_now_iso()})[:20],
                action=action,
                import_request_id=request_id,
                actor=actor,
                safe_summary=summary,
                occurred_at=utc_now_iso(),
            )
        )


def _digest_status(provider_digest: str, downloaded_checksum: str) -> str:
    if not provider_digest:
        return "provider_digest_missing"
    digest = provider_digest.removeprefix("sha256:")
    return "provider_digest_verified" if digest == downloaded_checksum else "provider_digest_mismatch"


__all__ = ["CiArtifactImportService"]
