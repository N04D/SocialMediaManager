# Community Plugin Security

Community plugins are Python code and still require operator trust. Phase 18 did not provide sandboxing, subprocess isolation, dependency virtualization, resource limits, malware classification, or crash containment. Signatures prove provenance and integrity only.

Phase 19 changes external community plugins to run out of process in per-version virtual environments. This provides crash containment and dependency isolation, but it is still not a full OS sandbox and does not completely block direct filesystem or socket access.

Phase 20 adds OS sandbox policy, platform gates, and attestation before external plugin import. Sandboxed still does not mean malware-free. Direct network and broad filesystem access are not supported community-plugin privileges; HTTP and browser operations must go through host brokers.

## Owned publication boundaries

The Markdown Website channel demonstrates filesystem publishing with allowlisted repository references, no arbitrary remotes, no raw credentials, no site build commands, and no user-owned project `content/` or `drafts/` fixtures. Git push is not treated as public verification.
