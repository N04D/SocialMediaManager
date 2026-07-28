# Certification Evidence CI Import

CI-origin trust is host-owned. Import accepts managed references only; no
arbitrary artifact URL is trusted.

CI evidence is verified against repository identity, workflow identity, commit
SHA, required suites, required skip count, package checksum, and signature or
trusted CI-origin policy.

Unsigned CI evidence is not marked trusted by default. The UI and readiness model
distinguish `workflow_configured`, `artifact_not_imported`,
`artifact_imported_untrusted`, and `artifact_imported_verified`.
