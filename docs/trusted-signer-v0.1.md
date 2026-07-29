# Trusted Signer v0.1

Phase 29 adds a host-owned signer boundary for certification evidence.
The production-capable algorithm is Ed25519 through the established
`cryptography` library. When that library or a configured signer is absent,
production signing is reported as `not_configured`.

Private key material is never stored in application data, evidence packages,
support bundles, CLI output, API responses, or logs. The persistent signer
record stores only a `private_key_secret_reference`, public key, fingerprint,
status, approval metadata, allowed evidence types, and allowed source types.

Phase 30 wires signers to managed secrets. The preferred local path is
host-side Ed25519 generation directly into `secret.local_encrypted`; private
key material is not exported and is read only through a `certification_signing`
lease.

Host import attestations are local statements that this host imported and
verified a concrete CI artifact. They are not Sigstore, SLSA, or universal
supply-chain attestations.
