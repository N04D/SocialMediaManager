# macOS Sandbox

macOS is production-ready only when official App Sandbox enforcement is demonstrably active: code-signed host app, App Sandbox entitlement, signed helper or XPC service, correct helper entitlements, sandbox inheritance or separate helper/XPC architecture, plugin-scoped container data, and sandbox attestation.

`sandbox-exec`, custom undocumented profiles, and private sandbox APIs are not production mechanisms. Without signing and entitlements, community activation is blocked except for explicit development override.
