# Content Legacy Migration

`LegacyContentAdapter` supports lazy compatibility with existing draft/content files.

Flow:

1. A legacy identifier is requested.
2. Existing mapping is reused when present.
3. The source file is read safely.
4. A canonical `ContentItem` and first `ContentRevision` are created.
5. Compatibility metadata records the source.
6. The original content file is not rewritten.

No startup bulk migration exists in phase 12.

Media remains linked through existing `ContentMediaRelation` and MediaLibraryService compatibility flows.

