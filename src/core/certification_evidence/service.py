"""Application service for certification evidence trust and operator control."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.core.staging_analytics.service import StagingAnalyticsCertificationService

from .canonical import canonical_json_text
from .comparisons import compare_evidence
from .contracts import CERTIFICATION_EVIDENCE_FRAMEWORK_VERSION
from .errors import CertificationEvidenceError
from .freshness import default_freshness_policy, freshness_status
from .import_export import export_to_managed_bytes, import_from_managed_bytes
from .integrity import integrity_findings, safe_repairs
from .models import (
    CertificationArtifactManifest,
    CertificationEvidencePackage,
    CertificationImportRecord,
    CertificationProvenance,
    CertificationRevocation,
    stable_checksum,
    utc_now_iso,
)
from .packages import build_package, verify_artifact_manifest
from .persistence import DatabaseCertificationEvidenceRepository
from .provenance import build_local_provenance, local_commit_sha, validate_commit_sha
from .reviews import build_review
from .signatures import verify_signature
from .trust import default_ci_origin, default_trust_policy, evaluate_trust


class CertificationEvidenceService:
    def __init__(self, *, database_path: Path | None = None) -> None:
        self.repository = DatabaseCertificationEvidenceRepository(database_path)
        self.staging = StagingAnalyticsCertificationService(database_path=database_path)

    def canonical_report(self, report: dict[str, Any]) -> dict[str, Any]:
        canonical_text = canonical_json_text(report)
        return {
            "schema_version": "1.0",
            "canonical_json": canonical_text,
            "checksum": stable_checksum(canonical_text),
        }

    def create_from_staging_run(
        self,
        run_id: str,
        *,
        signer_reference_id: str = "",
        source_type: str = "local",
        evidence_type: str = "deterministic_staging_certification",
        commit_sha: str | None = None,
    ) -> dict[str, Any]:
        report_payload = self.staging.report(run_id)["report"]
        if (
            isinstance(report_payload, dict)
            and report_payload.get("provider_observed_status") == "staging_provider_certification_not_run"
        ):
            report_payload = self._not_run_report(run_id)
        provenance = build_local_provenance(
            source_type=source_type,
            commit_sha=commit_sha,
            required_skips=0,
            staging_execution_status=report_payload.get(
                "provider_observed_status", "deterministic_certification_passed"
            ),
        )
        artifacts = {
            "artifacts/test-summary.json": (
                "safe_testsummary",
                {
                    "required_skips": provenance.required_skips,
                    "required_tests": provenance.required_tests,
                    "test_suite_id": provenance.test_suite_id,
                },
            ),
            "artifacts/reconciliation.json": (
                "safe_reconciliation",
                {
                    "run_id": report_payload.get("run_id", run_id),
                    "provider_observed_status": report_payload.get("provider_observed_status", "not_observed"),
                    "mapping_status": report_payload.get("mapping_status", "unknown"),
                },
            ),
        }
        package, artifact_bytes = build_package(
            workspace_id="workspace-1",
            evidence_type=evidence_type,
            report=report_payload,
            provenance=provenance,
            artifacts=artifacts,
            signer_reference_id=signer_reference_id,
        )
        return self._persist_verified_package(package, artifact_bytes, provenance, import_source="local")

    def generate_deterministic_evidence(self, *, signer_reference_id: str = "") -> dict[str, Any]:
        result = self.staging.deterministic_certification()
        return self.create_from_staging_run(result["run"]["id"], signer_reference_id=signer_reference_id)

    def export_evidence(self, evidence_id: str) -> dict[str, Any]:
        evidence = self._stored_full(evidence_id)
        package = self._package_from_dict(evidence)
        artifacts = {path: payload.encode("utf-8") for path, payload in evidence["artifacts"].items()}
        exported = export_to_managed_bytes(package, artifacts)
        return {
            "output_reference": exported["output_reference"],
            "file_name": exported["file_name"],
            "media_type": exported["media_type"],
            "size_bytes": exported["size_bytes"],
            "package_checksum": package.package_checksum,
            "data": exported["data"],
        }

    def import_evidence(self, data: bytes, *, import_source: str = "managed-local") -> dict[str, Any]:
        manifest, artifacts = import_from_managed_bytes(data)
        package = self._package_from_dict(manifest)
        verify_artifact_manifest(package, artifacts)
        provenance = json.loads(artifacts[package.provenance_reference].decode("utf-8"))
        report = json.loads(artifacts[package.report_reference].decode("utf-8"))
        payload_for_signature = {
            "evidence_type": package.evidence_type,
            "workspace_id": package.workspace_id,
            "report": report,
            "provenance": provenance,
            "artifact_manifest": [asdict(item) for item in package.artifact_manifest],
        }
        signature_status = verify_signature(payload_for_signature, package.signature_envelope)
        if signature_status in {"invalid", "payload_mismatch"}:
            trust_status = "invalid"
        else:
            trust_status = self._trust_status(package, CertificationProvenance(**provenance), signature_status)
        freshness = self._freshness_status(package.evidence_type, CertificationProvenance(**provenance))
        saved = self.repository.save_package(
            package=manifest | {"report": report, "provenance": provenance},
            artifacts=artifacts,
            provenance=provenance,
            trust_status=trust_status,
            freshness_status=freshness,
            signature_status=signature_status,
        )
        self.repository.save_import_record(
            CertificationImportRecord(
                package_id=package.package_id,
                package_checksum=package.package_checksum,
                signer_reference_id=package.signature_envelope.signer_reference_id,
                imported_at=utc_now_iso(),
                import_source=import_source,
                trust_status=trust_status,
                first_seen_at=utc_now_iso(),
            )
        )
        return {
            "evidence": saved,
            "import_status": "imported",
            "trust_status": trust_status,
            "freshness_status": freshness,
        }

    def list_evidence(self) -> dict[str, Any]:
        return {"evidence": self.repository.list_packages(), "remote_ci_status": self.remote_ci_status()}

    def get_evidence(self, evidence_id: str) -> dict[str, Any]:
        return {"evidence": self.repository.get_package(evidence_id)}

    def verify(self, evidence_id: str) -> dict[str, Any]:
        evidence = self._stored_full(evidence_id)
        package = self._package_from_dict(evidence)
        provenance = CertificationProvenance(**evidence["provenance"])
        payload_for_signature = {
            "evidence_type": package.evidence_type,
            "workspace_id": package.workspace_id,
            "report": evidence["report"],
            "provenance": evidence["provenance"],
            "artifact_manifest": [asdict(item) for item in package.artifact_manifest],
        }
        signature_status = verify_signature(payload_for_signature, package.signature_envelope)
        trust_status = self._trust_status(package, provenance, signature_status)
        freshness = self._freshness_status(package.evidence_type, provenance)
        return {
            "evidence_id": evidence_id,
            "signature_status": signature_status,
            "trust_status": trust_status,
            "freshness_status": freshness,
            "commit_matches": provenance.commit_sha == local_commit_sha(),
            "technical_valid": trust_status not in {"invalid", "revoked"},
        }

    def compare(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self._stored_full(left_id)
        right = self._stored_full(right_id)
        comparison = compare_evidence(left, right)
        return {"comparison": self.repository.save_comparison(comparison)}

    def review(
        self, evidence_id: str, *, decision: str = "approved", reviewer_id: str = "operator", safe_comment: str = ""
    ) -> dict[str, Any]:
        evidence = self.repository.get_package(evidence_id)
        review = build_review(
            workspace_id=evidence["workspace_id"],
            evidence_id=evidence_id,
            evidence_checksum=evidence["package_checksum"],
            decision=decision,
            reviewer_id=reviewer_id,
            safe_comment=safe_comment,
        )
        return {"review": self.repository.save_review(review)}

    def reviews(self, evidence_id: str) -> dict[str, Any]:
        return {"reviews": self.repository.list_reviews(evidence_id)}

    def revoke(
        self, evidence_id: str, *, reason: str = "operator_revoked", reviewer_id: str = "operator"
    ) -> dict[str, Any]:
        evidence = self.repository.get_package(evidence_id)
        seed = stable_checksum({"evidence_id": evidence_id, "reason": reason})
        revocation = CertificationRevocation(
            id="cert-revoke-" + seed[:16],
            workspace_id=evidence["workspace_id"],
            target_type="evidence_package",
            target_id=evidence_id,
            reason=reason[:200],
            revoked_at=utc_now_iso(),
            revoked_by=reviewer_id,
        )
        return {"revocation": self.repository.save_revocation(revocation)}

    def freshness(self, evidence_id: str) -> dict[str, Any]:
        evidence = self._stored_full(evidence_id)
        status = self._freshness_status(evidence["evidence_type"], CertificationProvenance(**evidence["provenance"]))
        return {"evidence_id": evidence_id, "freshness_status": status, "import_does_not_refresh": True}

    def policies(self) -> dict[str, Any]:
        return {
            "trust_policy": asdict(default_trust_policy()),
            "freshness_policy": asdict(default_freshness_policy()),
            "approval_policy": {
                "deterministic_local": {"approval_required": False},
                "live_staging": {"approval_required": True, "minimum_approvals": 1},
            },
            "signing_policy": {
                "local_development": {"unsigned_behavior": "allow_local_only"},
                "ci_import": {"unsigned_behavior": "reject"},
            },
        }

    def remote_ci_status(self) -> dict[str, str]:
        try:
            from src.core.ci_artifacts.service import CiArtifactImportService

            readiness = CiArtifactImportService(database_path=self.repository.database_path).readiness(
                current_commit=local_commit_sha()
            )
            artifact_status = str(readiness["remote_ci_status"])
            return {
                "workflow_configured": "true",
                "artifact_status": artifact_status,
                "ci_passed_claim": "not_claimed" if artifact_status == "artifact_not_imported" else "import_verified",
            }
        except Exception:
            pass
        return {
            "workflow_configured": "true",
            "artifact_status": "artifact_not_imported",
            "ci_passed_claim": "not_claimed",
        }

    def readiness(self) -> dict[str, Any]:
        evidence = self.repository.list_packages()
        valid = any(
            item["trust_status"] in {"signed_local", "unsigned_local", "verified_ci_artifact"} for item in evidence
        )
        trusted = any(item["trust_status"] in {"signed_local", "verified_ci_artifact"} for item in evidence)
        fresh = any(item["freshness_status"] == "fresh" for item in evidence)
        reviewed = any(self.repository.list_reviews(item["package_id"]) for item in evidence)
        return {
            "certification_evidence_valid": valid,
            "certification_evidence_trusted": trusted,
            "certification_evidence_fresh": fresh,
            "certification_evidence_commit_matches": all(
                (item.get("provenance") or {}).get("commit_sha") in {"", local_commit_sha()} for item in evidence
            ),
            "certification_evidence_reviewed": reviewed,
            "deterministic_certification_status": "available" if evidence else "missing",
            "staging_certification_status": "not_required",
            "staging_certification_ready": False,
            "external_plugin_sandbox_ready": False,
            "sandbox_phase20_2_status": {"production_ready": False},
        }

    def dry_run_staging_profile(self, profile_id: str) -> dict[str, Any]:
        validation = self.staging.validate_profile(profile_id)
        return {
            "profile_id": profile_id,
            "dry_run": True,
            "browser_opened": False,
            "event_sent": False,
            "validation": validation,
            "active_run_status": "none",
            "explicit_confirmation_required": True,
        }

    def execute_staging_profile(self, profile_id: str, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise CertificationEvidenceError(
                "certification.confirmation_required", "Explicit confirmation is required."
            )
        return self.staging.create_run(profile_id, execute_staging=True)

    def support_bundle(self) -> dict[str, Any]:
        evidence = self.repository.list_packages()
        return {
            "certification": {
                "framework_version": CERTIFICATION_EVIDENCE_FRAMEWORK_VERSION,
                "evidence": [
                    {
                        "package_id": item["package_id"],
                        "package_checksum": item["package_checksum"],
                        "trust_status": item["trust_status"],
                        "freshness_status": item["freshness_status"],
                        "signature_status": item["signature_status"],
                        "signer_fingerprint": item["signature_envelope"].get("public_key_fingerprint", ""),
                        "commit_binding": (item.get("provenance") or {}).get("commit_sha", ""),
                        "required_skips": (item.get("provenance") or {}).get("required_skips", 0),
                        "review_count": len(self.repository.list_reviews(item["package_id"])),
                    }
                    for item in evidence
                ],
                "contains_private_key": False,
                "contains_raw_package": False,
                "contains_user_content": False,
                "contains_tokens": False,
            }
        }

    def integrity(self) -> dict[str, Any]:
        packages = self.repository.list_packages()
        return {"findings": integrity_findings(packages), "safe_repairs": safe_repairs()}

    def _persist_verified_package(
        self,
        package: CertificationEvidencePackage,
        artifact_bytes: dict[str, bytes],
        provenance: CertificationProvenance,
        *,
        import_source: str,
    ) -> dict[str, Any]:
        report = json.loads(artifact_bytes[package.report_reference].decode("utf-8"))
        payload_for_signature = {
            "evidence_type": package.evidence_type,
            "workspace_id": package.workspace_id,
            "report": report,
            "provenance": asdict(provenance),
            "artifact_manifest": [asdict(item) for item in package.artifact_manifest],
        }
        signature_status = verify_signature(payload_for_signature, package.signature_envelope)
        trust_status = self._trust_status(package, provenance, signature_status)
        freshness = self._freshness_status(package.evidence_type, provenance)
        saved = self.repository.save_package(
            package=asdict(package) | {"report": report, "provenance": asdict(provenance)},
            artifacts=artifact_bytes,
            provenance=asdict(provenance),
            trust_status=trust_status,
            freshness_status=freshness,
            signature_status=signature_status,
        )
        self.repository.save_import_record(
            CertificationImportRecord(
                package_id=package.package_id,
                package_checksum=package.package_checksum,
                signer_reference_id=package.signature_envelope.signer_reference_id,
                imported_at=utc_now_iso(),
                import_source=import_source,
                trust_status=trust_status,
                first_seen_at=utc_now_iso(),
            )
        )
        return {"evidence": saved, "artifacts": artifact_bytes}

    def _trust_status(
        self, package: CertificationEvidencePackage, provenance: CertificationProvenance, signature_status: str
    ) -> str:
        return evaluate_trust(
            package=package,
            provenance=provenance,
            signature_status=signature_status,
            policy=default_trust_policy(package.workspace_id),
            current_commit=local_commit_sha(),
            ci_origin=default_ci_origin() if provenance.source_type == "ci" else None,
        )

    def _freshness_status(self, evidence_type: str, provenance: CertificationProvenance) -> str:
        return freshness_status(
            provenance=provenance,
            policy=default_freshness_policy(evidence_type=evidence_type),
            current_commit=local_commit_sha(),
            current_framework_version="phase28",
            now=utc_now_iso(),
        )

    def _stored_full(self, evidence_id: str) -> dict[str, Any]:
        evidence = self.repository.get_package(evidence_id)
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT artifact_path, payload_json FROM certification_artifacts WHERE package_id = ?", (evidence_id,)
            ).fetchall()
        evidence["artifacts"] = {row["artifact_path"]: row["payload_json"] for row in rows}
        if "report.json" in evidence["artifacts"]:
            evidence["report"] = json.loads(evidence["artifacts"]["report.json"])
        if "provenance.json" in evidence["artifacts"]:
            evidence["provenance"] = json.loads(evidence["artifacts"]["provenance.json"])
        return evidence

    def _package_from_dict(self, payload: dict[str, Any]) -> CertificationEvidencePackage:
        signature = payload["signature_envelope"]
        from .models import CertificationSignatureEnvelope

        return CertificationEvidencePackage(
            package_id=payload["package_id"],
            package_version=payload["package_version"],
            evidence_type=payload["evidence_type"],
            workspace_id=payload["workspace_id"],
            source_environment=payload["source_environment"],
            source_origin=payload["source_origin"],
            generated_at=payload["generated_at"],
            report_reference=payload["report_reference"],
            provenance_reference=payload["provenance_reference"],
            artifact_manifest=tuple(CertificationArtifactManifest(**item) for item in payload["artifact_manifest"]),
            signature_envelope=CertificationSignatureEnvelope(**signature),
            package_checksum=payload["package_checksum"],
        )

    def _not_run_report(self, run_id: str) -> dict[str, Any]:
        return {
            "framework_version": "0.1.0",
            "profile_id": "unknown",
            "run_id": run_id,
            "provider_observed_status": "staging_provider_certification_not_run",
            "mapping_status": "not_run",
            "certification_passed": False,
            "live_staging_executed": False,
            "deterministic_only": True,
            "checksum": stable_checksum(run_id),
        }


def parse_package_data(data: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    return import_from_managed_bytes(data)


__all__ = ["CertificationEvidenceService", "parse_package_data", "validate_commit_sha"]
