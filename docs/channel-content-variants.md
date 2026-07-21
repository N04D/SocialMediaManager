# Channel Content Variants

`ChannelContentVariant` stores explicit channel text.

Fields:

- `content_item_id`, `source_revision_id`
- `channel_plugin_id`, `capability`
- `variant_type`
- `title`, `body`, `summary`
- `hashtags`, `mentions`, `call_to_action`
- `status`, `validation_status`, `requirement_version`
- `variant_checksum`

Variant types are `manual`, `adapted`, `imported`, `legacy`, and `generated_placeholder`. Phase 12 does not use AI generation; a placeholder is only a prepared empty state.

A ready variant points to the revision it was validated against. When canonical content changes, ready variants for older revisions are marked `stale`.

