# Staging Analytics Security Boundaries

Only registered synthetic staging origins are accepted. Production origins,
production analytics accounts, arbitrary URLs, file URLs, URLs with credentials,
and unregistered private origins are blocked.

Browser events originate from an isolated Playwright page. Python services may
observe browser evidence and later read provider observations, but they do not
post event payloads to a provider endpoint.

The staging smoke uses no real content from `content/` or `drafts/`, no
production account, and no real visitor data. Phase 20.2 remains separately
blocked with `production_ready=false`.
