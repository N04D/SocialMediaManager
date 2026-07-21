from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta

from config import load_config

from plugin_runtime import get_plugin_runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview and materialize publication schedules")
    parser.add_argument("command", choices=["preview", "materialize", "reconcile", "health"])
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--workspace-id", default="default")
    parser.add_argument("--schedule-id", default="")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--starts-at-local", default="")
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--frequency", default="daily")
    parser.add_argument("--interval", type=int, default=1)
    parser.add_argument("--count", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    runtime = get_plugin_runtime(config, reset=False, strict=True)
    service = runtime.schedule_materialization_service(config)
    if args.command == "health":
        print(json.dumps(service.health_check(), indent=2, sort_keys=True))
        return 0
    if args.command == "preview":
        starts_at = args.starts_at_local or (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0).isoformat()
        result = service.preview_recurrence(
            starts_at_local=starts_at,
            timezone=args.timezone,
            recurrence={"frequency": args.frequency, "interval": args.interval, "count": args.count},
            maximum=args.count,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "materialize":
        result = (
            service.materialize_schedule(
                args.schedule_id,
                workspace_id=args.workspace_id,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            if args.schedule_id
            else service.materialize_due_horizon(
                workspace_id=args.workspace_id,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "reconcile":
        occurrences = service.occurrence_repository.list_all(workspace_id=args.workspace_id)
        results = [
            service.reconcile_occurrence(item.id, workspace_id=args.workspace_id, dry_run=args.dry_run)
            for item in occurrences[: args.batch_size]
        ]
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
