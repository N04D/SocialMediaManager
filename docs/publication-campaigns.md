# Publication Campaigns

Campaigns group plans and schedules. They coordinate status, pause/resume, cancellation intent, and calendar filtering.

Campaigns do not own content text, media processing, channel browser flows, provider retry behavior, or platform-specific publication logic.

Models:

- `Campaign`
- `CampaignMember`
- `CampaignCoordinationPolicy`

Member types:

- `publication_plan`
- `publication_schedule`

Aggregate status is derived centrally by `CampaignService.derive_status()`.

Pause behavior:

- schedules stop materializing new occurrences;
- queued or running executions are not blindly cancelled;
- uncertain executions remain visible.

Cancellation behavior:

- future schedule occurrences are cancelled;
- non-queued concrete targets are cancelled through planning;
- queued or running targets use phase-13 cancellation behavior;
- historical evidence remains immutable.
