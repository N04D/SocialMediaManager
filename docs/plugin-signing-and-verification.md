# Plugin Signing and Verification

Release artifacts use Sigstore bundles. The verifier checks artifact digest, bundle validity, certificate identity, OIDC issuer, transparency log status, signed timestamp status, and signer policy. A valid signature from an unknown identity is labeled `signature_valid_identity_untrusted`, not verified publisher. Offline bundle verification is supported and explicitly labeled.
