# Publication Uncertain Handling

Uncertain attempts represent possible external mutation without trustworthy verification.

Resolution values:

- `published_verified`
- `not_published_verified`
- `duplicate_detected`
- `cannot_determine`
- `abandoned_by_operator`

`published_verified` marks the target published. `not_published_verified` can allow a new generation after confirmation. `cannot_determine` never triggers automatic retry.

Evidence is stored as safe IDs or references, not full page contents.

