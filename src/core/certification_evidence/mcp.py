"""MCP-style query surface for certification evidence."""

from __future__ import annotations

from .service import CertificationEvidenceService


class CertificationEvidenceMCP:
    def __init__(self, service: CertificationEvidenceService | None = None) -> None:
        self.service = service or CertificationEvidenceService()

    def get_certification_evidence(self) -> dict:
        return self.service.list_evidence()

    def verify_certification_evidence(self, evidence_id: str) -> dict:
        return self.service.verify(evidence_id)

    def compare_certification_evidence(self, left_id: str, right_id: str) -> dict:
        return self.service.compare(left_id, right_id)

    def get_certification_freshness(self, evidence_id: str) -> dict:
        return self.service.freshness(evidence_id)

    def get_certification_trust_status(self, evidence_id: str) -> dict:
        evidence = self.service.get_evidence(evidence_id)["evidence"]
        return {
            "evidence_id": evidence_id,
            "trust_status": evidence["trust_status"],
            "signature_status": evidence["signature_status"],
        }

    def get_certification_reviews(self, evidence_id: str) -> dict:
        return self.service.reviews(evidence_id)

    def explain_readiness_evidence(self) -> dict:
        return self.service.readiness()

    def explain_ci_certification_status(self) -> dict:
        return self.service.remote_ci_status()

    def explain_staging_evidence_difference(self, left_id: str, right_id: str) -> dict:
        return self.service.compare(left_id, right_id)

    def get_certification_signers(self) -> dict:
        from src.core.trusted_signing.service import TrustedSignerService

        return TrustedSignerService(database_path=self.service.repository.database_path).status()

    def get_certification_signer_health(self, signer_id: str) -> dict:
        from src.core.trusted_signing.service import TrustedSignerService

        return TrustedSignerService(database_path=self.service.repository.database_path).health(signer_id)

    def get_ci_artifact_origins(self) -> dict:
        from src.core.ci_artifacts.service import CiArtifactImportService

        return CiArtifactImportService(database_path=self.service.repository.database_path).origins()

    def get_ci_workflow_runs(self, origin_id: str, commit_sha: str = "") -> dict:
        from src.core.ci_artifacts.service import CiArtifactImportService

        return CiArtifactImportService(database_path=self.service.repository.database_path).list_runs(
            origin_id, commit_sha=commit_sha
        )

    def get_ci_run_artifacts(self, origin_id: str, run_id: str) -> dict:
        from src.core.ci_artifacts.service import CiArtifactImportService

        return CiArtifactImportService(database_path=self.service.repository.database_path).artifacts(origin_id, run_id)

    def get_ci_artifact_import(self, import_id: str) -> dict:
        from src.core.ci_artifacts.service import CiArtifactImportService

        return CiArtifactImportService(database_path=self.service.repository.database_path).import_show(import_id)

    def get_ci_import_attestation(self, import_id: str) -> dict:
        from src.core.ci_artifacts.service import CiArtifactImportService

        return {
            "attestations": CiArtifactImportService(database_path=self.service.repository.database_path).import_show(
                import_id
            )["attestations"]
        }

    def explain_ci_artifact_trust(self, import_id: str) -> dict:
        return self.get_ci_artifact_import(import_id)

    def explain_ci_import_failure(self, import_id: str) -> dict:
        from src.core.ci_artifacts.service import CiArtifactImportService

        return CiArtifactImportService(database_path=self.service.repository.database_path).reconcile(import_id)

    def explain_signer_status(self, signer_id: str) -> dict:
        return self.get_certification_signer_health(signer_id)

    def compare_local_and_ci_evidence(self) -> dict:
        from src.core.ci_artifacts.service import CiArtifactImportService

        return CiArtifactImportService(database_path=self.service.repository.database_path).readiness()


__all__ = ["CertificationEvidenceMCP"]
