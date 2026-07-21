# Media Library Service

`MediaLibraryService` centralizes library behavior:

- `get_asset()`
- `search_assets()`
- `attach_asset()`
- `detach_asset()`
- `reorder_assets()`
- `set_primary_asset()`
- `list_owner_media()`
- `resolve_owner_media()`
- `list_asset_usage()`
- `evaluate_channel_suitability()`
- `request_delete()`
- `restore_asset()`
- `health_check()`

The service composes `MediaRuntime`, `MediaProcessingRuntime`, relation and usage repositories, retention service, and the channel requirement registry.

Search supports safe filters for workspace, names, type, MIME, status, created fields, provider ID, inspection status, dimensions, checksum, linked/used state, suitability, and deleted state. Results are paginated and sorted with asset ID as deterministic secondary ordering.

The service never returns local materialized paths or storage references in selection, search, retention, integrity, or API payloads.
