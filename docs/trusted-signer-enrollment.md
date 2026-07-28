# Trusted Signer Enrollment

Enrollment uses an existing secret reference:

1. Operator selects `private_key_secret_reference`.
2. The signer service reads the key call-scoped.
3. Ed25519 format is validated.
4. Public key and fingerprint are derived.
5. A sign/verify probe is executed.
6. The signer is stored as `pending_approval`.
7. An independent operator approves and activates it.

No key file path or raw key argument is accepted by public API or CLI.
