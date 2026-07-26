# Sandbox Attestation

`PluginSandboxAttestation` records the sandbox plan ID, plugin host and process instance, platform, enforcement status, enforced and missing controls, filesystem, network, syscall, process, identity, and resource status, policy and environment checksums, safe platform evidence, and expiry.

Attestation must succeed before plugin activation and proxy registration. A stale or mismatched attestation blocks startup.

Phase 20.1 splits attestation into parent-side launcher/process evidence and child-side kernel evidence. The child runtime applies Landlock and seccomp before external plugin import, returns actual kernel state, and waits for `sandbox.attestation_accepted`. Only then may `plugin.activate` load the external entrypoint.
