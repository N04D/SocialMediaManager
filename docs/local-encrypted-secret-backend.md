# Local Encrypted Secret Backend

`secret.local_encrypted` uses AES-256-GCM from `cryptography`. Each secret version has a unique random nonce and associated data binding:

- secret reference ID;
- backend version;
- secret type;
- workspace or host scope;
- secret version.

Vault records contain metadata, nonce, ciphertext, algorithm, and checksums over encrypted data. They do not contain plaintext checksums or secret values. Vault paths are managed by host configuration and must not live under `content/` or `drafts/`.
