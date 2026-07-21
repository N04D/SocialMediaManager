# Media Framework v0.3

Media Framework v0.3 adds the media library layer above v0.2 processing. It does not add new image transformations: `media.image.processing.basic` still creates safe copy variants only.

## Contract Versions

- `MEDIA_FRAMEWORK_VERSION = "0.3.0"`
- `MEDIA_LIBRARY_CONTRACT_VERSION = "1.0"`
- `MEDIA_RELATION_CONTRACT_VERSION = "1.0"`
- `MEDIA_USAGE_CONTRACT_VERSION = "1.0"`
- `MEDIA_RETENTION_CONTRACT_VERSION = "1.0"`

Existing storage, asset, reference, plugin, inspection, processing, and requirement contracts remain `1.0`.

## Architecture

```text
Content / Draft / Publication
        |
        v
ContentMediaRelation
        |
        v
MediaAsset -> MediaVariant
        |
        v
MediaUsage / Retention / Integrity
```

`MediaLibraryService` is registered in `ApplicationPluginRuntime` as `media.library.service`. Dashboard and LinkedIn use that one service.

## Source Of Truth

Relations and usage records are JSON repository records in `studio_data`. Derived counters are rebuilt from relation and usage repositories. Storage references remain internal to `MediaRuntime` and storage providers.

## Boundaries

Core media imports no channel or browser code. `MediaLibraryService` imports no concrete storage provider, concrete processor, or channel plugin. LinkedIn publish uses `MediaLibraryService` and imports no media repositories.
