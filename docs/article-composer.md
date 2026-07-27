# Article Composer

The composer manages title, summary, Markdown body, tags, language, author, hero media, CTA, SEO metadata, and status.

Autosave is debounced and version checked. Conflicts return a conflict status instead of last-write-wins. Autosave never starts publication and does not write the full body to operational logs.

Immutable revisions are created explicitly from a known draft version.
