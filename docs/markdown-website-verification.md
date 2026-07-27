# Markdown Website Verification

Git push is not publication verification. `WebsitePublicationVerifier` checks the public URL through a safe HTTP facade, validates origin, content type, redirect outcome, revision marker, publication target marker, and snapshot checksum marker.

Deployment delay is represented as pending verification. Dependent social targets remain blocked until verification succeeds.
