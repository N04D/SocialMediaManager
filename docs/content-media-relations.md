# Content Media Relations

`ContentMediaRelation` links an owner to a media asset and optionally to a specific variant.

Fields:

- `id`
- `workspace_id`
- `owner_type`
- `owner_id`
- `asset_id`
- `variant_id`
- `role`
- `position`
- `channel_plugin_id`
- `publication_id`
- `required`
- `active`
- `created_at`
- `updated_at`
- `created_by`
- `metadata`

Supported owner types are `content`, `draft`, `publication`, `publication_attempt`, and compatibility-only `unknown`.

Supported roles are `primary`, `social_image`, `attachment`, `gallery`, `publication_media`, `source`, and `reference`.

Rules:

- one active `primary` per owner;
- stable non-negative `position`;
- no duplicate active relation for owner, asset, role, and position;
- variant must belong to the asset;
- deleted, failed, and quarantined assets cannot receive new active relations;
- relation metadata is redacted for paths and storage references.

Lazy migration reads explicit relations first, then `media_asset_ids`, then legacy image paths. It creates relations without removing old compatibility fields or rewriting user-owned content.
