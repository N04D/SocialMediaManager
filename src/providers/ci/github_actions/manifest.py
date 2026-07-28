"""Provider identity for the GitHub Actions CI artifact source."""

MANIFEST = {
    "provider_id": "ci.github_actions",
    "provider_version": "0.1.0",
    "provider_family": "ci_artifacts",
    "execution_mode": "built_in_in_process",
    "data_access": "read_only",
}

__all__ = ["MANIFEST"]
