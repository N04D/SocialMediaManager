# Canonical Content Model

`ContentItem` is the central, provider-independent source object.

Fields:

- `id`, `workspace_id`
- `content_type`
- `title`, `body`, `summary`, `language`
- `status`, `current_revision_id`
- `created_at`, `updated_at`, `created_by`, `updated_by`
- `source_type`, `source_reference`
- safe `metadata`

Canonical content is not LinkedIn-specific. Hashtags, calls to action, and channel-specific text may live in `ChannelContentVariant`.

Statuses are controlled separately from publication target status. A failed target does not make canonical content an error object.

