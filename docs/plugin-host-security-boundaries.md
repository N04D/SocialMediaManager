# Plugin Host Security Boundaries

External code does not run in the main process. Process isolation contains crashes and hangs, while callbacks are the supported route to secrets, HTTP, media, browser, analytics, execution reporting, events, audit, state, and clock.

Phase 20 adds OS-level sandbox policy and attestation. The host still treats sandboxing as impact reduction, not proof of safety. There is no unsandboxed production fallback for external community plugins.
