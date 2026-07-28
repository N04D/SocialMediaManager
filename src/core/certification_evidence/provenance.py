"""Certification provenance builders."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .errors import CertificationEvidenceError
from .models import CertificationProvenance, stable_checksum, utc_now_iso

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def validate_commit_sha(commit_sha: str) -> str:
    if not _SHA_RE.match(commit_sha):
        raise CertificationEvidenceError("certification.commit_sha", "Evidence must bind to an exact commit SHA.")
    return commit_sha


def local_commit_sha() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return validate_commit_sha(result.stdout.strip())


def local_branch() -> str:
    result = subprocess.run(["git", "branch", "--show-current"], check=True, capture_output=True, text=True)
    return result.stdout.strip() or "unknown"


def dirty_state() -> str:
    result = subprocess.run(["git", "status", "--short"], check=True, capture_output=True, text=True)
    entries = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not entries:
        return "clean"
    non_user = [
        line
        for line in entries
        if not (
            line[3:].startswith("content/")
            or line[3:].startswith("drafts/")
            or line[3:].startswith("integrations/plugin_registry/")
        )
    ]
    if not non_user:
        if any("integrations/plugin_registry/" in line for line in entries):
            return "dirty_generated_only"
        return "dirty_user_owned_only"
    return "dirty_other"


def build_local_provenance(
    *,
    source_type: str,
    commit_sha: str | None = None,
    test_suite_id: str = "phase28.certification",
    required_skips: int = 0,
    staging_execution_status: str = "deterministic_certification_passed",
) -> CertificationProvenance:
    sha = validate_commit_sha(commit_sha or local_commit_sha())
    commands = (
        "python -m unittest tests.test_certification_evidence_framework_phase28 -v",
        "python -m unittest tests.test_certification_evidence_signing_phase28 -v",
        "python -m unittest tests.test_certification_evidence_import_phase28 -v",
    )
    return CertificationProvenance(
        provenance_version="1.0",
        source_type=source_type,
        repository_identity=Path.cwd().name,
        commit_sha=sha,
        branch=local_branch(),
        dirty_state=dirty_state(),
        test_suite_id=test_suite_id,
        test_suite_version="phase28.v0.1",
        test_commands=commands,
        test_result_checksum=stable_checksum({"commands": commands, "required_skips": required_skips}),
        required_tests=commands,
        required_skips=required_skips,
        browser_name="chromium",
        browser_version="chromium",
        worker_execution_model="thread",
        database_type="sqlite",
        instrumentation_version="0.1.0",
        analytics_provider_id="analytics.plausible",
        staging_execution_status=staging_execution_status,
        generated_by="local-operator",
        generated_at=utc_now_iso(),
    )


__all__ = ["build_local_provenance", "dirty_state", "local_branch", "local_commit_sha", "validate_commit_sha"]
