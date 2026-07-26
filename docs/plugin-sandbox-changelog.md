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

## 0.1.1

### Fixed

- Added a host-owned Linux launcher for namespace setup before `plugin_host_runtime`.
- Added child-side pre-plugin Landlock/seccomp enforcement and kernel attestation.
- Added `sandbox.attestation_accepted` import gate before external entrypoint loading.
- Added launcher integrity metadata and phase-20.1 native enforcement tests.

### Security

- Production readiness now requires real UID/GID mapping and namespace creation probes, not just namespace files in `/proc`.
