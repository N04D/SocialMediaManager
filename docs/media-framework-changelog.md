# Media Framework Changelog

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
