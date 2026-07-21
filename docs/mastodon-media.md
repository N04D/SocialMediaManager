# Mastodon Media

Image publishing uses `MediaLibraryService.resolve_owner_media()` and `MediaRuntime.materialize()` through the existing media library. Mastodon imports no concrete media storage provider.

Phase 16 supports JPEG and PNG, at most four images, further constrained by instance discovery.

Upload uses `POST /api/v2/media`. Attachment IDs are tracked as `MastodonRemoteMediaUpload` until a status is created. If media is uploaded but no status is created, the record remains an orphan candidate for explicit reconciliation. Cleanup is only allowed when ownership and unattached status are clear.

Alt text resolution order is relation metadata, asset metadata, explicit target metadata, then null with a warning. AI-generated alt text is not used.
