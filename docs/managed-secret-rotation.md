# Managed Secret Rotation

Rotation creates a new encrypted secret version, validates it, requires approval where policy demands, and then activates the new version atomically.

Historical signatures remain bound to the old public key. The old secret value is not automatically destroyed; retention and revocation policy control cleanup.
