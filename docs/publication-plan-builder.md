# Publication Plan Builder

The default owned-publication plan contains:

- Markdown Website target first.
- LinkedIn target after website `publication_verified`.
- Mastodon target after website `publication_verified`.

Plan mutations use optimistic concurrency. A social target containing a website URL without a website dependency is at least a warning.
