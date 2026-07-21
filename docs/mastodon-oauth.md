# Mastodon OAuth

The plugin uses OAuth Authorization Code with PKCE S256.

Flow:

1. Validate instance origin and SSRF policy.
2. Discover instance capabilities.
3. Reuse or create an instance-bound app through `POST /api/v1/apps`.
4. Store client credentials as secret references.
5. Generate random state and PKCE verifier.
6. Store temporary flow state as secret references with expiry.
7. Exchange callback code through `/oauth/token`.
8. Verify identity with `/api/v1/accounts/verify_credentials`.
9. Store the user access token as a secret reference.
10. Revoke temporary state/verifier secrets.

Minimum scopes are `profile`, `read:statuses`, `write:statuses`, and `write:media`. Broad `read`/`write`, admin, notifications, follows, and DM scopes are not requested.
