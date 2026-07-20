# Media Legacy Path Migration

Existing drafts and derivatives may contain `image_paths` or `media_paths`. Phase 9 keeps those records intact and uses lazy migration during LinkedIn image publish.

Flow:

1. If `media_asset_ids` exist, use them.
2. If only legacy paths exist, validate each path.
3. Accept only files inside known media/content roots.
4. Reject traversal, symlinks, missing files, and paths outside allowed roots.
5. Import one asset through `MediaRuntime`.
6. Store a legacy path to asset mapping.
7. Update derivative metadata with `media_asset_ids`.
8. Leave the original file untouched.

There is no startup bulk import. This compatibility layer is temporary and can be removed after content records consistently use asset IDs.
