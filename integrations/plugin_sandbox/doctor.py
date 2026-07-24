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
    rows.extend({"status": "FAIL", "check": "missing_control", "message": item} for item in capability.missing_controls)
    return rows


if __name__ == "__main__":
    for item in run():
        print(f"{item['status']} {item['check']} {item['message']}")
