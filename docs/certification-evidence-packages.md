# Certification Evidence Packages

Packages are managed ZIP containers with `manifest.json`, `provenance.json`,
`report.json`, safe `artifacts/*`, and `signature.json`.

All JSON is canonical UTF-8 with stable key ordering. Artifact paths are relative
and checked against traversal, absolute paths, duplicate normalized paths,
symlinks, size bombs and compression-ratio abuse.

Packages must not include raw databases, cookies, Authorization headers, raw
provider responses, raw event payloads, full content, private remotes, or
user-owned `content/` and `drafts/` data.
