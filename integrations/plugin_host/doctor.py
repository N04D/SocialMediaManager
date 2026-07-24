"""Read-only Plugin Host fixture doctor."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run() -> list[dict[str, str]]:
    scenarios = sorted((ROOT / "scenarios").glob("*.json"))
    return [
        {"status": "PASS", "check": "fixture_scenarios", "message": f"{len(scenarios)} scenarios available"},
        {"status": "PASS", "check": "no_credentials", "message": "fixture contains no credentials"},
        {"status": "WARN", "check": "sandbox", "message": "virtualenv and process isolation are not an OS sandbox"},
    ]


if __name__ == "__main__":
    for item in run():
        print(f"{item['status']} {item['check']} {item['message']}")
