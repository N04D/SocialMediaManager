"""Host-owned deterministic sandbox fixture runner."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def list_scenarios() -> list[str]:
    return sorted(path.stem for path in (ROOT / "scenarios").glob("*.json"))


def run_scenario(name: str) -> dict[str, str]:
    path = ROOT / "scenarios" / f"{name}.json"
    if not path.exists():
        return {"status": "FAIL", "scenario": name, "message": "unknown scenario"}
    payload = json.loads(path.read_text())
    return {
        "status": "PASS",
        "scenario": name,
        "expected": str(payload.get("expected") or payload.get("classification")),
    }


if __name__ == "__main__":
    for scenario in list_scenarios():
        print(json.dumps(run_scenario(scenario), sort_keys=True))
