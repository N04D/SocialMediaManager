# Media Usage Tracking

`MediaUsage` records structural and operational use of assets and variants.

Fields:

- `id`
- `workspace_id`
- `asset_id`
- `variant_id`
- `usage_type`
- `owner_type`
- `owner_id`
- `channel_plugin_id`
- `publication_id`
- `job_id`
- `status`
- `first_used_at`
- `last_used_at`
- `usage_count`
- `retained_until`
- `metadata`

Supported usage types are `linked`, `selected`, `materialized`, `processed`, `publish_attempt`, `published`, and `previewed`.

Structural usage includes active relations and verified historical publications. Operational usage includes preview, selection, materialization, processing, and publish attempts. Retention primarily respects structural usage, publication evidence, and active operational records. Old previews can expire and do not block cleanup indefinitely.

Usage registration is idempotent by key. Repeated use of the same job/relation/event increments the existing record rather than creating duplicate history.
