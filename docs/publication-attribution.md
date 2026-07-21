# Publication Attribution

`PublicationAttribution` links analytics to the exact publication context.

It captures publication ID, remote publication ID, channel/account, content item, content revision/checksum, channel variant/checksum, publication plan, target, schedule, occurrence, campaign, execution attempt, snapshot checksum, media relation IDs, media asset IDs, media variant IDs, requirement versions, and timestamps.

Attribution is built primarily from immutable publication evidence, target snapshots, execution evidence, and existing publication records. Current mutable content or media relations are only fallback sources and produce `partial` attribution.

Historical attribution is immutable: later content edits, relation changes, or campaign membership changes do not rewrite what was actually published.

Backfill is explicit, bounded, and dry-run by default. Title-only or body-text-only matching is rejected.
