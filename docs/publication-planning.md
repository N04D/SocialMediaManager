# Publication Planning

`PublicationPlan` records publication intent for a canonical content item and selected revision.

`PublicationTarget` records a channel, account, capability, selected variant, selected media relations, scheduled intent, validation status, snapshot checksum, and job linkage.

Planning and execution are separate:

- planning validates content, variants, media, account presence, and timing;
- preparation creates an immutable snapshot;
- queueing creates existing `PublishJob` records;
- channel workers execute jobs later through existing runtime paths.

Queueing does not open a browser.

