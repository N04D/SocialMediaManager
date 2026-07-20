# Media Framework v0.1

Media Framework v0.1 introduces media as a provider-independent domain. Channels work with `MediaAsset` IDs and ask `MediaRuntime` for references or temporary materializations. Storage providers own bytes and opaque storage references.

## Architecture

```text
Content / Channel publication
        |
        v
MediaAsset
        |
        v
MediaStorageProvider
        |
        +-- provider.media.storage.local
        +-- provider.media.storage.memory
```

Core owns media models, identifiers, statuses, contracts, capability names, errors, and validation. Core media imports no channels, browser providers, local storage provider, Pillow, FFmpeg, or cloud SDKs.

## Contract Versions

Central constants live in `src/core/media/contracts.py`:

- `MEDIA_FRAMEWORK_VERSION = "0.1.0"`
- `MEDIA_STORAGE_PROVIDER_CONTRACT_VERSION = "1.0"`
- `MEDIA_ASSET_CONTRACT_VERSION = "1.0"`
- `MEDIA_REFERENCE_CONTRACT_VERSION = "1.0"`
- `MEDIA_PLUGIN_CONTRACT_VERSION = "1.0"`

## Models

`MediaAsset` is product content and workspace-bound. It stores ownership, MIME, checksum, provider ID, opaque storage reference, status, source information, and metadata.

`MediaVariant` is a derivative of an asset for a purpose. Fase 9 stores the model only; image processing and variants are phase 10 scope.

`MediaReference` is provider-independent. It must not expose provider-internal absolute paths.

`MediaMaterialization` is a temporary local file reference for consumers such as browser uploads. It is not a permanent asset reference and must be cleaned up.

## Capabilities

Implemented:

- `media.storage`
- `media.storage.store`
- `media.storage.read`
- `media.storage.materialize`
- `media.storage.delete`
- `media.asset.manage`
- `media.variant.manage`

Reserved but not claimed: image/video processing, thumbnails, transcription, and generation.

## Artifact Boundary

`BrowserArtifact` and `MediaAsset` remain separate. Browser artifacts are diagnostic and session-bound; media assets are product content and workspace-bound. Screenshots are not automatically imported into the media library.
