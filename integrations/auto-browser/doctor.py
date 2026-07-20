from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.providers.auto_browser import AutoBrowserConfig, AutoBrowserProvider  # noqa: E402
from src.core.browser import BrowserSessionOptions, BrowserTarget, FileBackedBrowserProfileLockManager  # noqa: E402


@dataclass
class Check:
    name: str
    status: str
    message: str
    remediation: str = ""

    def to_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


def _redact(value: str) -> str:
    if not value:
        return ""
    return "***redacted***"


def _config_from_env(args: argparse.Namespace) -> AutoBrowserConfig:
    token_env = args.bearer_token_env or "AUTO_BROWSER_BEARER_TOKEN"
    return AutoBrowserConfig(
        enabled=True,
        base_url=args.base_url or os.environ.get("AUTO_BROWSER_BASE_URL", ""),
        bearer_token=os.environ.get(token_env, ""),
        operator_id=args.operator_id or os.environ.get("AUTO_BROWSER_OPERATOR_ID", "social-media-manager"),
        request_timeout=float(getattr(args, "request_timeout", 15.0)),
        readiness_timeout=float(getattr(args, "readiness_timeout", 5.0)),
        expected_server_version=args.expected_version,
        shared_upload_host_dir=os.environ.get(
            "AUTO_BROWSER_SHARED_UPLOAD_HOST_DIR",
            str(ROOT / "integrations" / "auto-browser" / "data" / "uploads-incoming"),
        ),
        shared_upload_controller_dir=os.environ.get(
            "AUTO_BROWSER_SHARED_UPLOAD_CONTROLLER_DIR",
            "/shared/uploads/incoming",
        ),
    )


def run_checks(args: argparse.Namespace) -> tuple[list[Check], int]:
    checks: list[Check] = []
    config = _config_from_env(args)
    messages = config.validate()
    if not config.bearer_token:
        messages.append(f"Auto Browser bearer token is not configured in {args.bearer_token_env}.")
    checks.append(
        Check(
            "configuration",
            "FAIL" if messages else "PASS",
            "; ".join(messages)
            if messages
            else f"base_url={config.safe_base_url()} token={_redact(config.bearer_token)}",
            "Set AUTO_BROWSER_BASE_URL and AUTO_BROWSER_BEARER_TOKEN, or pass --base-url.",
        )
    )
    lock_dir = ROOT / "studio_data" / "locks"
    mapping_path = ROOT / "studio_data" / "auto_browser_sessions.json"
    checks.append(Check("local lock directory", "PASS", str(lock_dir)))
    checks.append(Check("local mapping storage", "PASS", str(mapping_path)))
    if messages:
        return checks, 2

    provider = AutoBrowserProvider(
        auto_browser_config=config,
        lock_manager=FileBackedBrowserProfileLockManager(lock_dir),
        mapping_path=mapping_path,
    )
    health = provider.health_check()
    checks.append(Check("health", "PASS" if health.get("status") == "ready" else "FAIL", str(health.get("status"))))
    acceptable_versions = {"", args.expected_version}
    if args.expected_version in {"1.3.1", "1.4.0"}:
        acceptable_versions.update({"1.3.1", "1.4.0"})
    checks.append(
        Check(
            "server version",
            "PASS" if health.get("server_version") in acceptable_versions else "FAIL",
            str(health.get("server_version") or "unknown"),
        )
    )
    for feature in ["takeover_capability", "artifact_capability", "upload_capability", "evaluation_capability"]:
        value = str(health.get(feature) or "unknown")
        checks.append(Check(feature, "PASS" if value == "available" else "WARN", value))
    reconciliation = provider.reconcile_sessions()
    checks.append(
        Check(
            "reconciliation",
            "PASS" if reconciliation.get("status") in {"consistent", "unavailable"} else "WARN",
            str(reconciliation.get("status")),
        )
    )

    session = None
    try:
        session = provider.create_session(
            BrowserSessionOptions(
                profile_id="doctor-auto-browser",
                start_url=args.fixture_url,
                exclusive=True,
                metadata={"purpose": "auto_browser.doctor", "job_id": "doctor"},
            )
        )
        snapshot = session.snapshot()
        checks.append(Check("temporary session", "PASS", snapshot.url))
        session.navigate(args.fixture_url)
        checks.append(Check("navigation", "PASS", session.current_url()))
        checks.append(Check("observation", "PASS" if session.title() else "WARN", session.title()))
        target = BrowserTarget(role="button", accessible_name="Primary action")
        checks.append(
            Check("target resolution", "PASS" if session.element_exists(target) else "FAIL", "Primary action")
        )
        checks.append(Check("screenshot", "PASS" if session.screenshot().id else "FAIL", "screenshot artifact created"))
        result = session.evaluate("() => ({ok: true})")
        checks.append(
            Check(
                "evaluation",
                "PASS" if isinstance(result, dict) or result is not None else "WARN",
                "JSON result received",
            )
        )
    except Exception as exc:
        checks.append(Check("temporary session", "FAIL", str(exc), "Check controller readiness and fixture URL."))
    finally:
        if session is not None:
            session.close()

    exit_code = 0 if all(check.status != "FAIL" for check in checks) else 2
    return checks, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Auto Browser integration doctor.")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--bearer-token-env", default="AUTO_BROWSER_BEARER_TOKEN")
    parser.add_argument("--operator-id", default="")
    parser.add_argument("--expected-version", default="1.3.1")
    parser.add_argument("--fixture-url", default="http://127.0.0.1:8765/")
    parser.add_argument("--request-timeout", default=15.0, type=float)
    parser.add_argument("--readiness-timeout", default=5.0, type=float)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    checks, exit_code = run_checks(args)
    if args.json:
        print(json.dumps({"checks": [check.to_dict() for check in checks]}, indent=2))
    else:
        for check in checks:
            line = f"{check.status:4} {check.name}: {check.message}"
            if check.remediation and check.status == "FAIL":
                line += f" ({check.remediation})"
            print(line)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
