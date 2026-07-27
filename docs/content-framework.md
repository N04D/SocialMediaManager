# Content Framework

Phase 22 clarifies the owned-publication content lifecycle: drafts are mutable, content revisions are immutable, channel variant snapshots are immutable, and publication snapshots remain bound to the version explicitly scheduled.

Markdown Website publications consume immutable content revisions and website variants containing title, slug, summary, Markdown body, SEO metadata, CTA metadata, tags, language, author, and structured media references.

The renderer never rereads mutable drafts after the publication snapshot is created.
