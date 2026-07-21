# Publication Dispatcher

The dispatcher scans prepared publication targets and makes existing `PublishJob` records available to the current worker infrastructure.

Due targets are ordered by:

1. resolved scheduled UTC time;
2. target position;
3. target ID.

Targets are dispatchable when the plan is active, the target is ready or prepared, the schedule is due, a snapshot exists, the target is not stale, no active lease exists, no successful or uncertain attempt exists, the account is connected, and kill switches allow execution.

CLI:

- `python -m publication_dispatcher due --dry-run`
- `python -m publication_dispatcher run-once`
- `python -m publication_dispatcher reconcile --dry-run`
- `python -m publication_dispatcher health`

Dispatch does not call channel runtimes or open a browser.

