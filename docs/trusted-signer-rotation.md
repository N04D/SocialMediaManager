# Trusted Signer Rotation

Rotation creates a new signer reference with a new secret reference. The old
signer is marked `rotated`; historical signatures remain verifiable with the
stored public key. New packages use only an active replacement signer after
validation and approval.

Historical evidence is not automatically re-signed.
