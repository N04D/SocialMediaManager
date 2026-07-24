# Plugin Sandbox Changelog

## 0.1.0

### Added

- OS Sandbox Framework contracts, models, policy compiler, attestation, integrity, and violation records.
- Linux, Windows, macOS, unsupported, and fakeable controller surfaces.
- Plugin Host integration with fail-closed sandbox gating before external plugin handshake.
- Sandbox CLI, API payloads, UI summaries, fixture scenarios, and phase-20 tests.

### Security

- Direct network remains unsupported for community plugins.
- `content/`, `drafts/`, home credentials, repository roots, and broad host paths are denied by policy.
- Development override is explicit and labeled as degraded.
