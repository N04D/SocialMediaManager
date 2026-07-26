"""Read-only Plugin Sandbox doctor."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.plugin_sandbox import select_sandbox_controller  # noqa: E402

ROOT = Path(__file__).resolve().parent


def run() -> list[dict[str, str]]:
    capability = select_sandbox_controller().inspect_platform()
    rows = [
        {"status": "PASS" if capability.supported else "FAIL", "check": "controller", "message": capability.status},
        {
            "status": "PASS" if capability.production_ready else "FAIL",
            "check": "production_ready",
            "message": ",".join(capability.missing_controls) or "all required controls active",
        },
        {
            "status": "PASS",
            "check": "fixture_scenarios",
            "message": str(len(list((ROOT / "scenarios").glob("*.json")))),
        },
    ]
    controls = set(capability.available_controls)
    rows.extend(
        [
            {
                "status": "PASS"
                if all(
                    item in controls
                    for item in [
                        "user_namespace",
                        "mount_namespace",
                        "pid_namespace",
                        "ipc_namespace",
                        "uts_namespace",
                        "network_namespace",
                    ]
                )
                else "FAIL",
                "check": "namespace creation",
                "message": "required namespace set",
            },
            {"status": "PASS" if "uid_gid_mapping" in controls else "FAIL", "check": "uid/gid mapping", "message": ""},
            {"status": "PASS" if "landlock" in controls else "FAIL", "check": "Landlock ABI", "message": ""},
            {
                "status": "PASS" if "landlock" in controls and capability.production_ready else "FAIL",
                "check": "Landlock enforcement",
                "message": "",
            },
            {"status": "PASS" if "seccomp" in controls else "FAIL", "check": "seccomp load", "message": ""},
            {
                "status": "PASS" if "seccomp" in controls and capability.production_ready else "FAIL",
                "check": "seccomp denial probes",
                "message": "",
            },
            {
                "status": "PASS" if "network_default_deny" in controls and "network_namespace" in controls else "FAIL",
                "check": "network default-deny",
                "message": "",
            },
            {"status": "PASS" if "cgroup_v2" in controls else "WARN", "check": "cgroup", "message": "v2"},
            {
                "status": "PASS" if capability.production_ready else "FAIL",
                "check": "child attestation",
                "message": "",
            },
        ]
    )
    rows.extend({"status": "FAIL", "check": "missing_control", "message": item} for item in capability.missing_controls)
    return rows


if __name__ == "__main__":
    for item in run():
        print(f"{item['status']} {item['check']} {item['message']}")
