"""Build the deterministic local plugin registry fixture."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))

from src.core.plugin_distribution import PluginPackageBuildService  # noqa: E402
from src.core.plugin_distribution.services import safe_json, sha256_file  # noqa: E402

PLUGIN = REPO / "templates" / "channel-plugin"
TARGETS = ROOT / "targets"
METADATA = ROOT / "metadata"
RELEASES = ROOT / "releases"


def main() -> None:
    for path in (TARGETS, METADATA, RELEASES):
        path.mkdir(parents=True, exist_ok=True)
    release_dir = RELEASES / "channel.example-0.1.0"
    if release_dir.exists():
        shutil.rmtree(release_dir)
    PluginPackageBuildService().create_release_directory(PLUGIN, release_dir)
    wheel = next(release_dir.glob("*.whl"))
    target_name = wheel.name
    shutil.copyfile(wheel, TARGETS / target_name)
    release = json.loads((release_dir / "plugin.release.json").read_text())
    expires = (datetime.now(UTC) + timedelta(days=3650)).isoformat()
    root = {"role": "root", "version": 1, "expires": expires, "threshold": 1, "keys": {"fixture-root-key": "TEST-ONLY"}}
    targets = {
        "role": "targets",
        "version": 1,
        "expires": expires,
        "targets": [
            {
                "path": target_name,
                "sha256": sha256_file(TARGETS / target_name),
                "size": (TARGETS / target_name).stat().st_size,
                "plugin_id": release["plugin_id"],
                "plugin_version": release["plugin_version"],
                "release_id": release["release_id"],
                "distribution_status": release["distribution_status"],
                "release_channel": release["release_channel"],
                "sdk_version": release["plugin_sdk_version"],
                "permissions": release["permissions"],
                "capabilities": release["capabilities"],
                "maintainers": release["maintainers"],
                "license": "MIT",
                "signer_policy": release["signer_policy_id"],
                "signer_identity_summary": "GitHub Actions fixture identity",
                "sdk_compatibility": "compatible",
                "artifacttype": "wheel",
                "name": "Example",
                "description": "Fixture community channel plugin.",
                "published_at": release["published_at"],
                "yanked": False,
                "revoked": False,
                "hashes": {
                    "release_metadata_sha256": sha256_file(release_dir / "plugin.release.json"),
                    "sbom_sha256": sha256_file(release_dir / "plugin.sbom.json"),
                    "compatibility_report_sha256": sha256_file(release_dir / "plugin.compatibility.json"),
                    "sigstore_sha256": sha256_file(release_dir / "plugin.sigstore.json"),
                },
            }
        ],
    }
    snapshot = {"role": "snapshot", "version": 1, "expires": expires, "targets_version": 1}
    timestamp = {"role": "timestamp", "version": 1, "expires": expires, "snapshot_version": 1}
    (ROOT / "trusted-root.json").write_text(safe_json(root))
    for name, payload in {
        "root.json": root,
        "targets.json": targets,
        "snapshot.json": snapshot,
        "timestamp.json": timestamp,
    }.items():
        (METADATA / name).write_text(safe_json(payload))
    (ROOT / "README.md").write_text(
        "# Plugin registry fixture\n\nUses TEST-ONLY metadata and fixture signing identities. No production keys.\n"
    )
    for scenario in [
        "healthy",
        "expired_timestamp",
        "expired_snapshot",
        "rollback",
        "hash_mismatch",
        "size_mismatch",
        "bad_signature",
        "unknown_signer",
        "revoked_signer",
        "yanked_release",
        "revoked_release",
        "delegated_namespace_conflict",
        "malformed_metadata",
        "unavailable_target",
        "truncated_download",
        "range_ignored",
        "registry_redirect",
        "stale_metadata",
    ]:
        (ROOT / "scenarios" / f"{scenario}.json").write_text(safe_json({"scenario": scenario, "fixture": True}))


if __name__ == "__main__":
    main()
