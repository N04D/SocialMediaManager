"""Read-only doctor for the local plugin registry fixture."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))

from src.core.plugin_distribution import PluginRegistryService, PluginRegistrySource  # noqa: E402


def run(*, verify_artifacts: bool = False) -> list[dict[str, str]]:
    source = PluginRegistrySource(
        id="fixture",
        name="Community registry fixture",
        metadata_base_url=str(ROOT / "metadata"),
        targets_base_url=str(ROOT / "targets"),
        trusted_root_path=str(ROOT / "trusted-root.json"),
        enabled=True,
        allow_download=True,
        allow_install=True,
        status="configured",
    )
    try:
        service = PluginRegistryService(source, Path("/tmp/smm-plugin-registry-doctor"))
        service.refresh()
        entries = service.list_plugins()
        result = [{"status": "PASS", "code": "registry.metadata", "safe_message": "Registry metadata refreshed."}]
        result.append(
            {"status": "PASS", "code": "registry.entries", "safe_message": f"{len(entries)} plugin entries available."}
        )
        if verify_artifacts:
            result.append(
                {
                    "status": "WARN",
                    "code": "artifact.verification_explicit",
                    "safe_message": "Artifact verification is explicit and not part of default doctor.",
                }
            )
        return result
    except Exception as exc:
        return [
            {
                "status": "FAIL",
                "code": getattr(exc, "code", "registry.doctor_failed"),
                "safe_message": str(getattr(exc, "safe_message", exc)),
            }
        ]


if __name__ == "__main__":
    for item in run():
        print(f"{item['status']} {item['code']} {item['safe_message']}")
