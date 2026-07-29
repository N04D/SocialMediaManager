# Host Signer Activation Runbook

1. Configure `secret.local_encrypted` with a healthy master key.
2. Create an `ed25519_private_key` reference with purpose `certification_signing`.
3. Generate the key inside the host.
4. Validate fingerprint and health.
5. Obtain independent security approval.
6. Enroll the signer from the secret reference.
7. Approve and activate the signer.
8. Sign and verify a deterministic evidence package.

Private key material is never exported.
