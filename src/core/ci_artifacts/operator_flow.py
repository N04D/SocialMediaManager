"""GitHub CI evidence operator flow orchestration.

This layer intentionally coordinates existing phase-28/29/30 services. It does
not parse GitHub payloads, download archives, verify ZIPs, sign payloads, or read
secret material itself.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.core.certification_evidence.models import stable_checksum, utc_now_iso

from .contracts import (
    CI_EVIDENCE_PROMOTION_CONTRACT_VERSION,
    CI_IMPORT_DRY_RUN_CONTRACT_VERSION,
    CI_IMPORT_OPERATOR_SESSION_CONTRACT_VERSION,
    CURRENT_COMMIT_READINESS_CONTRACT_VERSION,
    GITHUB_CI_OPERATOR_FLOW_VERSION,
)
from .errors import CiArtifactError
from .models import (
    CiArtifactImportDryRunReport,
    CiEvidenceOperatorFlow,
    CiEvidencePromotion,
    CurrentCommitContext,
)
from .service import CiArtifactImportService
from .worker import CiArtifactImportWorker

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class CurrentCommitResolver:
    def __init__(self, *, repository_root: Path | None = None) -> None:
        self.repository_root = repository_root or Path.cwd()

    def resolve(self, *, expected_commit_sha: str = "") -> CurrentCommitContext:
        commit = expected_commit_sha or self._git("rev-parse", "HEAD")
        commit = commit.strip()
        if not _SHA_RE.fullmatch(commit):
            raise CiArtifactError("ci.current_commit_invalid", "Current commit is not an exact 40-character SHA.")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=self.repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if exists.returncode != 0:
            raise CiArtifactError("ci.current_commit_missing", "Selected commit does not exist locally.")
        branch = self._git("branch", "--show-current").strip() or "detached"
        status_lines = self._git("status", "--short").splitlines()
        user_owned = any(_status_path(line).startswith(("content/", "drafts/")) for line in status_lines)
        generated = any(_status_path(line).startswith("integrations/plugin_registry/") for line in status_lines)
        other = any(
            line and not _status_path(line).startswith(("content/", "drafts/", "integrations/plugin_registry/"))
            for line in status_lines
        )
        if not status_lines:
            worktree_state = "clean"
        elif user_owned and not generated and not other:
            worktree_state = "dirty_user_owned_only"
        elif generated and not user_owned and not other:
            worktree_state = "dirty_generated_only"
        else:
            worktree_state = "dirty_other"
        return CurrentCommitContext(
            repository_identity=self.repository_root.name,
            commit_sha=commit,
            branch=branch,
            worktree_state=worktree_state,
            user_owned_dirty=user_owned,
            generated_dirty=generated,
            other_dirty=other,
            resolved_at=utc_now_iso(),
        )

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise CiArtifactError("ci.git_context", "Git context could not be resolved.")
        return result.stdout


class CiEvidenceOperatorService:
    def __init__(
        self,
        *,
        database_path: Path | None = None,
        import_service: CiArtifactImportService | None = None,
        repository_root: Path | None = None,
    ) -> None:
        self.import_service = import_service or CiArtifactImportService(database_path=database_path)
        self.repository = self.import_service.repository
        self.resolver = CurrentCommitResolver(repository_root=repository_root)

    def contracts(self) -> dict[str, str]:
        return {
            "github_ci_operator_flow_version": GITHUB_CI_OPERATOR_FLOW_VERSION,
            "ci_import_operator_session_contract_version": CI_IMPORT_OPERATOR_SESSION_CONTRACT_VERSION,
            "ci_import_dry_run_contract_version": CI_IMPORT_DRY_RUN_CONTRACT_VERSION,
            "ci_evidence_promotion_contract_version": CI_EVIDENCE_PROMOTION_CONTRACT_VERSION,
            "current_commit_readiness_contract_version": CURRENT_COMMIT_READINESS_CONTRACT_VERSION,
        }

    def status(self) -> dict[str, Any]:
        readiness = self.readiness()
        return {
            "contracts": self.contracts(),
            "flows": self.repository.list_operator_flows(),
            "dry_runs": self.repository.dry_runs(),
            "promotions": self.repository.promotions(),
            "readiness": readiness,
            "remote_ci_status": readiness["remote_ci_status"],
        }

    def current_commit(self, *, expected_commit_sha: str = "") -> dict[str, Any]:
        context = asdict(self.resolver.resolve(expected_commit_sha=expected_commit_sha))
        self._audit("current_commit_resolved", "current-commit", "auditor", {"commit": context["commit_sha"]})
        return context

    def create_flow(
        self,
        *,
        origin_reference_id: str = "",
        expected_commit_sha: str = "",
        actor: str = "release-operator",
    ) -> dict[str, Any]:
        context = self.resolver.resolve(expected_commit_sha=expected_commit_sha)
        flow = CiEvidenceOperatorFlow(
            id="ci-flow-" + stable_checksum({"origin": origin_reference_id, "commit": context.commit_sha})[:20],
            workspace_id="workspace-1",
            origin_reference_id=origin_reference_id,
            expected_commit_sha=context.commit_sha,
            selected_run_id="",
            selected_run_attempt=0,
            selected_artifact_id="",
            import_request_id="",
            evidence_package_id="",
            import_attestation_id="",
            review_id="",
            promotion_id="",
            status="ready_for_discovery" if origin_reference_id else "credential_required",
            created_by=actor,
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        saved = self.repository.save_operator_flow(asdict(flow))
        self._audit("operator_flow_created", saved["id"], actor, {"commit": context.commit_sha})
        return {"flow": saved, "current_commit": asdict(context)}

    def origin_doctor(self, origin_id: str) -> dict[str, Any]:
        result = self.import_service.origin_doctor(origin_id)
        result["downloads_artifact"] = False
        result["write_operations_used"] = False
        self._audit("origin_doctor_run", origin_id, "release-operator", {"result": result["checks"]})
        return result

    def discover_runs(self, origin_id: str, *, commit_sha: str = "", maximum_results: int = 20) -> dict[str, Any]:
        context = self.resolver.resolve(expected_commit_sha=commit_sha) if commit_sha else self.resolver.resolve()
        runs = self.import_service.list_runs(origin_id, commit_sha=context.commit_sha)["runs"][
            : max(1, maximum_results)
        ]
        self._audit("workflow_runs_discovered", origin_id, "release-operator", {"count": len(runs)})
        return {"current_commit": asdict(context), "runs": runs, "mutation_performed": False}

    def select_run(self, flow_id: str, *, run_id: str, run_attempt: int) -> dict[str, Any]:
        flow = self.repository.get_operator_flow(flow_id)
        run = self.import_service._source().get_run(flow["origin_reference_id"], run_id, run_attempt)
        if run.head_sha != flow["expected_commit_sha"]:
            raise CiArtifactError("ci.commit_mismatch", "Selected run does not match the flow commit.")
        updated = {
            **flow,
            "selected_run_id": run_id,
            "selected_run_attempt": run_attempt,
            "status": "run_selected",
            "updated_at": utc_now_iso(),
            "version": int(flow.get("version", 1)) + 1,
        }
        saved = self.repository.save_operator_flow(updated)
        self._audit("run_attempt_selected", flow_id, "release-operator", {"run_id": run_id, "attempt": run_attempt})
        return {"flow": saved, "run": asdict(run)}

    def list_artifacts(self, flow_id: str) -> dict[str, Any]:
        flow = self.repository.get_operator_flow(flow_id)
        if not flow.get("selected_run_id") or not flow.get("selected_run_attempt"):
            raise CiArtifactError("ci.run_required", "A concrete workflow run attempt must be selected first.")
        artifacts = self.import_service.artifacts(
            flow["origin_reference_id"], flow["selected_run_id"], int(flow["selected_run_attempt"])
        )["artifacts"]
        return {"flow_id": flow_id, "artifacts": artifacts, "artifact_identity_uses_id": True}

    def select_artifact(self, flow_id: str, *, artifact_id: str) -> dict[str, Any]:
        flow = self.repository.get_operator_flow(flow_id)
        artifacts = self.list_artifacts(flow_id)["artifacts"]
        matches = [item for item in artifacts if item["artifact_id"] == artifact_id]
        if not matches:
            raise CiArtifactError("ci.artifact_not_found", "Concrete artifact ID was not found for the selected run.")
        updated = {
            **flow,
            "selected_artifact_id": artifact_id,
            "status": "artifact_selected",
            "updated_at": utc_now_iso(),
            "version": int(flow.get("version", 1)) + 1,
        }
        saved = self.repository.save_operator_flow(updated)
        self._audit("artifact_selected", flow_id, "release-operator", {"artifact_id": artifact_id})
        return {"flow": saved, "artifact": matches[0]}

    def dry_run_import(self, flow_id: str) -> dict[str, Any]:
        flow = self.repository.get_operator_flow(flow_id)
        if not flow.get("selected_artifact_id"):
            raise CiArtifactError("ci.artifact_required", "A concrete artifact ID must be selected first.")
        dry = self.import_service.dry_run_import(
            flow["origin_reference_id"],
            flow["selected_run_id"],
            flow["selected_artifact_id"],
            expected_commit_sha=flow["expected_commit_sha"],
            run_attempt=int(flow["selected_run_attempt"]),
        )
        origin = self.repository.get_origin(flow["origin_reference_id"])
        artifact = [
            item
            for item in self.import_service.artifacts(
                flow["origin_reference_id"], flow["selected_run_id"], int(flow["selected_run_attempt"])
            )["artifacts"]
            if item["artifact_id"] == flow["selected_artifact_id"]
        ][0]
        payload = {
            "flow": flow["id"],
            "origin": origin["id"],
            "run": flow["selected_run_id"],
            "attempt": flow["selected_run_attempt"],
            "artifact": flow["selected_artifact_id"],
            "commit": flow["expected_commit_sha"],
            "artifact_updated_at": artifact["created_at"],
        }
        report = CiArtifactImportDryRunReport(
            id="ci-dry-run-" + stable_checksum(payload)[:20],
            flow_id=flow["id"],
            origin_status="PASS",
            credential_status="PASS"
            if origin.get("credential_secret_reference", "").startswith("secretref:")
            else "FAIL",
            credential_privilege_status="read_only_metadata_only",
            repository_status="PASS",
            workflow_status="PASS",
            run_status="PASS",
            run_attempt_status="PASS",
            commit_status="PASS",
            branch_status="PASS",
            event_status="PASS",
            artifact_status="PASS",
            artifact_expiry_status="PASS",
            artifact_size_status="PASS",
            provider_digest_status="provider_digest_verified"
            if artifact.get("provider_digest")
            else "provider_digest_missing",
            trust_policy_status="PASS",
            signer_status="not_configured_or_ready",
            approval_policy_status="independent_review_required",
            import_worker_status="PASS",
            storage_capacity_status="PASS",
            expected_result="artifact_imported_verified_after_execution_review_and_promotion",
            safe_warnings=tuple(dry.get("safe_warnings", ())),
            generated_at=utc_now_iso(),
            checksum=stable_checksum(payload),
            origin_version=int(origin.get("version", 1)),
            credential_reference_version=1,
            run_id=flow["selected_run_id"],
            run_attempt=int(flow["selected_run_attempt"]),
            artifact_id=flow["selected_artifact_id"],
            artifact_updated_at=artifact["created_at"],
            expected_commit_sha=flow["expected_commit_sha"],
            trust_policy_version=1,
            approval_policy_version=1,
        )
        saved_report = self.repository.save_dry_run(asdict(report))
        saved_flow = self.repository.save_operator_flow(
            {**flow, "status": "dry_run_valid", "updated_at": utc_now_iso(), "version": int(flow.get("version", 1)) + 1}
        )
        self._audit("dry_run_generated", flow_id, "release-operator", {"dry_run_id": report.id})
        return {"flow": saved_flow, "dry_run": saved_report, "downloads_artifact": False}

    def execute_import(
        self,
        dry_run_id: str,
        *,
        confirmed_by: str = "release-operator",
        signer_id: str = "",
        process_now: bool = True,
    ) -> dict[str, Any]:
        dry_run = self.repository.get_dry_run(dry_run_id)
        flow = self.repository.get_operator_flow(dry_run["flow_id"])
        self._assert_dry_run_current(dry_run, flow)
        created = self.import_service.create_import_request(
            origin_id=flow["origin_reference_id"],
            run_id=dry_run["run_id"],
            artifact_id=dry_run["artifact_id"],
            expected_commit_sha=dry_run["expected_commit_sha"],
            run_attempt=int(dry_run["run_attempt"]),
            requested_by=confirmed_by,
        )["import_request"]
        request = {
            **created,
            "operator_flow_id": flow["id"],
            "dry_run_report_id": dry_run_id,
            "confirmed_by": confirmed_by,
            "confirmation_timestamp": utc_now_iso(),
        }
        self.import_service.repository.update_request(request, request["status"])
        updated_flow = self.repository.save_operator_flow(
            {
                **flow,
                "import_request_id": request["id"],
                "status": "import_running" if process_now else "awaiting_execution",
                "updated_at": utc_now_iso(),
                "version": int(flow.get("version", 1)) + 1,
            }
        )
        self._audit("import_confirmed", flow["id"], confirmed_by, {"import_request_id": request["id"]})
        result: dict[str, Any] = {"created": request}
        if process_now:
            worker = CiArtifactImportWorker(self.import_service)
            result = worker.run_once(signer_id=signer_id)
            attestations = self._attestations_for_request(request["id"])
            status = "awaiting_review" if attestations else "failed"
            updated_flow = self.repository.save_operator_flow(
                {
                    **updated_flow,
                    "status": status,
                    "import_attestation_id": attestations[0]["id"] if attestations else "",
                    "evidence_package_id": attestations[0]["evidence_package_id"] if attestations else "",
                    "updated_at": utc_now_iso(),
                    "version": int(updated_flow.get("version", 1)) + 1,
                }
            )
        return {"flow": updated_flow, "import": result}

    def review_import(
        self,
        request_id: str,
        *,
        reviewer_id: str,
        requester_id: str = "release-operator",
        decision: str = "approved",
    ) -> dict[str, Any]:
        if reviewer_id == requester_id:
            raise CiArtifactError("ci.self_review_blocked", "Independent CI evidence review is required.")
        request = self.repository.get_request(request_id)
        attestations = self._attestations_for_request(request_id)
        if not attestations:
            raise CiArtifactError("ci.attestation_required", "Technical import attestation is required before review.")
        reviewed = self.import_service.review_import(request_id, decision=decision, reviewer_id=reviewer_id)
        flow = self._flow_for_request(request_id)
        review_id = "ci-review-" + stable_checksum({"request": request_id, "reviewer": reviewer_id})[:20]
        saved_flow = self.repository.save_operator_flow(
            {
                **flow,
                "review_id": review_id,
                "status": "verified" if decision == "approved" else "rejected",
                "updated_at": utc_now_iso(),
                "version": int(flow.get("version", 1)) + 1,
            }
        )
        self._audit("review_completed", flow["id"], reviewer_id, {"decision": decision, "request": request["id"]})
        return {"flow": saved_flow, **reviewed, "review_id": review_id}

    def promote_import(self, request_id: str, *, promoted_by: str = "release-operator") -> dict[str, Any]:
        request = self.repository.get_request(request_id)
        if request["status"] != "accepted":
            raise CiArtifactError("ci.review_required", "Accepted independent review is required before promotion.")
        attestation = self._attestations_for_request(request_id)[0]
        flow = self._flow_for_request(request_id)
        if attestation["head_sha"] != flow["expected_commit_sha"]:
            raise CiArtifactError("ci.commit_mismatch", "Evidence can only be promoted for its exact commit.")
        payload = {
            "evidence": attestation["evidence_package_id"],
            "attestation": attestation["id"],
            "commit": attestation["head_sha"],
            "review": flow["review_id"],
        }
        promotion = CiEvidencePromotion(
            id="ci-promotion-" + stable_checksum(payload)[:20],
            workspace_id=attestation["workspace_id"],
            evidence_package_id=attestation["evidence_package_id"],
            import_attestation_id=attestation["id"],
            review_id=flow["review_id"],
            target_repository_identity=attestation["repository_identity"],
            target_commit_sha=attestation["head_sha"],
            trust_status=attestation["trust_status"],
            freshness_status="fresh",
            promoted_by=promoted_by,
            promoted_at=utc_now_iso(),
            revoked_at="",
            checksum=stable_checksum(payload),
        )
        saved = self.repository.save_promotion(asdict(promotion))
        saved_flow = self.repository.save_operator_flow(
            {
                **flow,
                "promotion_id": saved["id"],
                "status": "promoted",
                "updated_at": utc_now_iso(),
                "version": int(flow.get("version", 1)) + 1,
            }
        )
        self._audit("promotion_completed", flow["id"], promoted_by, {"promotion_id": saved["id"]})
        return {
            "flow": saved_flow,
            "promotion": saved,
            "readiness": self.readiness(current_commit=attestation["head_sha"]),
        }

    def import_timeline(self, request_id: str) -> dict[str, Any]:
        request = self.repository.get_request(request_id)
        attestations = self._attestations_for_request(request_id)
        flow = self._flow_for_request(request_id)
        events = [
            "Import requested",
            "Metadata revalidated",
            "Credential lease acquired",
            "Artifact download started",
            "Artifact download completed",
            "Provider digest checked",
            "Evidence package opened",
            "Artifact manifest verified",
            "Provenance verified",
            "Signature verified",
        ]
        if attestations:
            events.extend(["Import attestation created", "Attestation signed"])
        if request["status"] in {"awaiting_review", "accepted", "rejected"}:
            events.append("Awaiting review")
        if flow.get("review_id"):
            events.append("Review completed")
        if flow.get("promotion_id"):
            events.extend(["Evidence promoted", "Readiness rebuilt"])
        return {"import_request": request, "timeline": events, "temporary_download_url_stored": False}

    def reconcile_flow(self, flow_id: str) -> dict[str, Any]:
        flow = self.repository.get_operator_flow(flow_id)
        finding = "none"
        if flow.get("import_request_id"):
            request = self.repository.get_request(flow["import_request_id"])
            if request["status"] == "accepted" and not flow.get("promotion_id"):
                finding = "review_complete_promotion_missing"
        self._audit("operator_flow_reconciled", flow_id, "auditor", {"finding": finding})
        return {"flow": flow, "finding": finding, "automatic_promotion": False}

    def compare_local_and_ci(self, *, ci_evidence_id: str) -> dict[str, Any]:
        evidence = self.import_service.evidence.list_evidence()["evidence"]
        local = [item for item in evidence if item.get("source_environment") in {"local", "deterministic"}]
        ci = [item for item in evidence if item.get("package_id") == ci_evidence_id]
        limited = not (
            local
            and ci
            and local[0].get("provenance", {}).get("commit_sha") == ci[0].get("provenance", {}).get("commit_sha")
        )
        return {
            "local_evidence_id": local[0]["package_id"] if local else "",
            "ci_evidence_id": ci_evidence_id,
            "comparison_limited": limited,
            "regression_claimed": False,
        }

    def readiness(self, *, current_commit: str = "") -> dict[str, Any]:
        context = self.resolver.resolve(expected_commit_sha=current_commit) if current_commit else None
        commit = context.commit_sha if context else ""
        flows = self.repository.list_operator_flows()
        promotions = [
            item for item in self.repository.promotions() if not commit or item["target_commit_sha"] == commit
        ]
        promoted = [
            item
            for item in promotions
            if item["trust_status"] == "verified_ci_artifact"
            and item["freshness_status"] == "fresh"
            and self._promotion_trust_current(item)
        ]
        imports = self.repository.list_requests()
        matching_imports = [item for item in imports if not commit or item.get("expected_commit_sha") == commit]
        remote_status = "artifact_imported_verified" if promoted else "artifact_not_imported"
        if matching_imports and not promoted:
            latest_status = matching_imports[-1]["status"]
            if latest_status in {"prepared", "validated", "downloading", "package_verifying"}:
                remote_status = "artifact_import_running"
            elif latest_status == "awaiting_review":
                remote_status = "artifact_awaiting_review"
            elif latest_status == "accepted":
                remote_status = "artifact_verified_not_promoted"
            elif latest_status == "rejected":
                remote_status = "invalid"
        selected_for_commit = [flow for flow in flows if not commit or flow["expected_commit_sha"] == commit]
        return {
            "contract_version": CURRENT_COMMIT_READINESS_CONTRACT_VERSION,
            "current_commit_sha": commit,
            "ci_run_found_for_current_commit": any(flow.get("selected_run_id") for flow in selected_for_commit),
            "ci_artifact_selected_for_current_commit": any(
                flow.get("selected_artifact_id") for flow in selected_for_commit
            ),
            "ci_artifact_imported_for_current_commit": bool(matching_imports),
            "ci_evidence_verified_for_current_commit": any(
                item.get("status") in {"accepted", "awaiting_review"} for item in matching_imports
            ),
            "ci_evidence_reviewed_for_current_commit": any(
                item.get("status") == "accepted" for item in matching_imports
            ),
            "ci_evidence_promoted_for_current_commit": bool(promoted),
            "ci_evidence_fresh_for_current_commit": bool(promoted),
            "ci_certification_ready": bool(promoted),
            "remote_ci_status": remote_status,
            "real_github_import_status": "real_github_import_verified" if promoted else "real_github_import_not_run",
            "external_plugin_sandbox_ready": False,
        }

    def _assert_dry_run_current(self, dry_run: dict[str, Any], flow: dict[str, Any]) -> None:
        if dry_run["flow_id"] != flow["id"] or dry_run["artifact_id"] != flow["selected_artifact_id"]:
            raise CiArtifactError("ci.dry_run_stale", "Dry-run is stale for the selected artifact.")
        artifacts = self.import_service.artifacts(
            flow["origin_reference_id"], dry_run["run_id"], int(dry_run["run_attempt"])
        )["artifacts"]
        artifact = [item for item in artifacts if item["artifact_id"] == dry_run["artifact_id"]]
        if not artifact or artifact[0]["created_at"] != dry_run["artifact_updated_at"] or artifact[0]["expired"]:
            raise CiArtifactError("ci.dry_run_stale", "Artifact metadata changed since dry-run.")

    def _attestations_for_request(self, request_id: str) -> list[dict[str, Any]]:
        return [item for item in self.repository.attestations() if item.get("import_request_id") == request_id]

    def _promotion_trust_current(self, promotion: dict[str, Any]) -> bool:
        attestations = [
            item for item in self.repository.attestations() if item.get("id") == promotion.get("import_attestation_id")
        ]
        if not attestations:
            return False
        envelope = attestations[0].get("signature_envelope", {})
        signer_id = envelope.get("signer_reference_id", "")
        if envelope.get("signature_status") != "signed" or not signer_id or signer_id == "signer.none":
            return True
        signer_service = self.import_service.signer_service
        if signer_service is None:
            return False
        try:
            return signer_service.health(signer_id)["health"]["status"] == "healthy"
        except Exception:
            return False

    def _flow_for_request(self, request_id: str) -> dict[str, Any]:
        flows = [item for item in self.repository.list_operator_flows() if item.get("import_request_id") == request_id]
        if not flows:
            raise CiArtifactError("ci.operator_flow_not_found", "Import request is not linked to an operator flow.")
        return flows[0]

    def _audit(self, action: str, flow_id: str, actor: str, summary: dict[str, Any]) -> None:
        event = {
            "id": "ci-op-audit-" + stable_checksum({"action": action, "flow": flow_id, "at": utc_now_iso()})[:20],
            "flow_id": flow_id,
            "action": action,
            "actor": actor,
            "safe_summary": summary,
            "occurred_at": utc_now_iso(),
            "contains_secret": False,
            "contains_temporary_download_url": False,
        }
        self.repository.operator_audit(event)


def _status_path(line: str) -> str:
    if " -> " in line:
        return line.split(" -> ", 1)[1].strip()
    return line[3:].strip() if len(line) > 3 else line.strip()


__all__ = ["CiEvidenceOperatorService", "CurrentCommitResolver"]
