from __future__ import annotations

import argparse
import json

from pipeline import load_config
from plugin_runtime import get_plugin_runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch prepared publication targets.")
    parser.add_argument("command", choices=["run-once", "reconcile", "health", "due"])
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--target-id", default="")
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    runtime = get_plugin_runtime(config, reset=True, strict=False)
    service = runtime.publication_execution_service(config)
    if args.command == "health":
        payload = service.health_check()
    elif args.command == "due":
        payload = {
            "due": [
                item.__dict__
                for item in service.find_due_targets(
                    workspace_id=args.workspace_id,
                    batch_size=args.batch_size,
                    dry_run=True,
                )
            ]
        }
    elif args.command == "reconcile":
        if args.target_id:
            payload = {
                "result": service.reconcile_target(
                    args.target_id,
                    workspace_id=args.workspace_id,
                    dry_run=args.dry_run,
                ).__dict__
            }
        elif args.plan_id:
            payload = {
                "results": [
                    result.__dict__
                    for result in service.reconcile_plan(
                        args.plan_id,
                        workspace_id=args.workspace_id,
                        dry_run=args.dry_run,
                    )
                ]
            }
        else:
            payload = {"recovered": [result.__dict__ for result in service.recover_expired_claims()]}
    else:
        payload = service.dispatch_due_targets(
            workspace_id=args.workspace_id,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
