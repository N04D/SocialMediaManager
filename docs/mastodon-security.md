# Mastodon Security

Secrets are stored only through opaque local secret references. Account/app records do not contain access tokens, authorization codes, PKCE verifiers, client secrets, cookies, local paths, or raw OAuth responses.

SSRF controls include origin normalization, DNS resolution, blocked address ranges, redirect target validation, exact-origin token binding, no cross-origin auth header forwarding, bounded response sizes, JSON content-type validation, and localhost-only development opt-in.

Disconnect revokes remotely when possible, always revokes the local token reference, and never deletes content, publications, analytics, or shared app registration.
