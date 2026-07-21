# Media Framework Changelog

## v0.2.0

- Raised `MEDIA_FRAMEWORK_VERSION` to `0.2.0`.
- Added `MEDIA_INSPECTION_CONTRACT_VERSION`, `MEDIA_PROCESSING_CONTRACT_VERSION`, and `MEDIA_REQUIREMENT_CONTRACT_VERSION`.
- Added safe header-based JPEG and PNG inspection through `ImageInspector`.
- Added `media.image.processing.basic`.
- Added `MediaProcessingRuntime` with a channel media requirement registry.
- Added `ChannelMediaRequirements` and provider-independent media resolution.
- Added LinkedIn image publish requirements for `channel.linkedin` / `linkedin.image_publish`.
- Activated `MediaVariant` lifecycle fields, deterministic variant keys, and idempotent variant save behavior.
- Routed LinkedIn image publish through `MediaProcessingRuntime`.
- Added publication evidence with source asset, selected variant, requirement version, checksum, and processor metadata.
- Preserved lazy legacy path migration before media resolution.

Known limitations:

- no new image transformations beyond safe inspection and controlled copy variants;
- no video or audio processing;
- no thumbnails;
- no cloud storage or CDN;
- relation-based media library remains future phase scope.

## v0.1.0

- Added central media contract versions.
- Added `MediaAsset`, `MediaVariant`, `MediaReference`, and `MediaMaterialization`.
- Added generic media errors.
- Added `MediaStorageProvider` contract.
- Added `provider.media.storage.local`.
- Added `InMemoryMediaStorageProvider`.
- Added `MediaRuntime` and JSON repositories.
- Added safe asset import, checksum validation, MIME allowlist, and materialization cleanup.
- Added lazy migration for legacy image paths.
- Added LinkedIn image publish support for `media_asset_ids`.

Known limitations:

- no image inspection beyond MIME/size/checksum;
- no thumbnails or variants generated yet;
- no S3/cloud provider;
- no bulk media library UI;
- legacy path compatibility remains temporary.
