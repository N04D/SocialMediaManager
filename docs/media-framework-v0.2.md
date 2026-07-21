# Media Framework v0.2

Media Framework v0.2 adds safe image inspection, channel media requirements, deterministic image variants, and channel media resolution on top of the v0.1 storage and asset layer.

## Contract Versions

Central constants live in `src/core/media/contracts.py`:

- `MEDIA_FRAMEWORK_VERSION = "0.2.0"`
- `MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION = "1.0"`
- `MEDIA_ASSET_CONTRACT_VERSION = "1.0"`
- `MEDIA_REFERENCE_CONTRACT_VERSION = "1.0"`
- `MEDIA_PLUGIN_CONTRACT_VERSION = "1.0"`
- `MEDIA_INSPECTION_CONTRACT_VERSION = "1.0"`
- `MEDIA_PROCESSING_CONTRACT_VERSION = "1.0"`
- `MEDIA_REQUIREMENT_CONTRACT_VERSION = "1.0"`

## Inspection

`ImageInspector` supports JPEG and PNG only. It reads image headers to extract MIME, dimensions, size, checksum, status, inspector ID, and inspection time. It does not expose EXIF, GPS, embedded comments, storage references, browser artifacts, or local paths.

Assets imported through `MediaRuntime.import_asset()` are inspected when they are JPEG or PNG. Successful inspection updates `MediaAsset.width`, `MediaAsset.height`, and safe `image_inspection` metadata.

## Processing Runtime

`MediaProcessingRuntime` is registered centrally by `ApplicationPluginRuntime.media_processing_runtime(config)`.

It owns:

- `ImageInspector`;
- `media.image.processing.basic`;
- `ChannelMediaRequirementRegistry`;
- direct-use versus variant resolution;
- safe materialization of resolved assets or variants.

Channels ask this runtime to resolve media. Channels do not import storage providers or processors directly.

## Basic Processor

`media.image.processing.basic` is a media plugin capability for safe JPEG/PNG inspection and deterministic channel variants. Phase 10 does not add new image transformations. When a variant is requested, the processor creates a controlled copy variant with a deterministic variant key, source checksum, requirement ID, requirement version, and processor ID.

## Channel Requirements

`ChannelMediaRequirements` describes provider-independent channel constraints:

- channel plugin ID;
- capability;
- requirement ID and version;
- allowed MIME types;
- dimensions;
- max file size;
- max assets;
- processor plugin ID.

LinkedIn registers `channel.linkedin` / `linkedin.image_publish` in `channels/linkedin/media_requirements.py`:

- JPEG and PNG;
- max 25 MB;
- max 9 assets;
- requirement version `1.0`;
- processor `media.image.processing.basic`.

## Resolution

`resolve_channel_media()`:

1. loads registered requirements;
2. validates ownership and asset availability through `MediaRuntime`;
3. inspects images when dimensions are missing;
4. selects direct-use assets when requirements are already met;
5. creates or reuses deterministic variants when a variant is requested;
6. returns provider-independent selected and rejected items.

Results never contain storage references, materialized paths, or provider-internal locations.

## Variant Lifecycle

`MediaVariantStatus` supports:

- `pending`;
- `processing`;
- `available`;
- `failed`;
- `deleted`.

Variant records include `workspace_id`, `variant_key`, `source_checksum`, `requirement_id`, `requirement_version`, `generated_by_plugin_id`, dimensions, checksum, status, and safe inspection metadata.

The JSON repository replaces records with the same `asset_id` and `variant_key`, which makes repeated or concurrent variant creation idempotent at the repository boundary.

## LinkedIn Publish

LinkedIn image publish now resolves media through `MediaProcessingRuntime`:

```text
media_asset_ids or legacy image_paths
→ MediaRuntime lazy import when needed
→ MediaProcessingRuntime.resolve_channel_media()
→ direct asset or MediaVariant
→ temporary materialization
→ BrowserSession.upload
→ publication evidence
```

Publication evidence is stored in `PublishJob.result_details_json["media_publication_evidence"]` and, for live confirmed publish, copied into `PublishedPost.raw_result_json`. Evidence includes source asset ID, selected variant ID, direct-use flag, dimensions, checksum, requirement ID/version, processor plugin, owner, position, and publication timestamp.

## Boundaries

Core media imports no channels, browser framework, concrete storage provider, or concrete channel plugin. LinkedIn publish imports no concrete media provider and no media repository. Browser Framework v1 is unchanged.
