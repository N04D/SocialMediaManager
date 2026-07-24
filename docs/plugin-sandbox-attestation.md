# Sandbox Attestation

`PluginSandboxAttestation` records the sandbox plan ID, plugin host and process instance, platform, enforcement status, enforced and missing controls, filesystem, network, syscall, process, identity, and resource status, policy and environment checksums, safe platform evidence, and expiry.

Attestation must succeed before plugin activation and proxy registration. A stale or mismatched attestation blocks startup.
