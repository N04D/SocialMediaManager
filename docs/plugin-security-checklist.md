# Plugin Security Checklist

General: no secrets in records or logs, no arbitrary paths, no cross-workspace access, no silent fallback, no automatic mutation retry, idempotency, rate limits, timeouts, response-size limits, safe errors, and audit.

API-first: SSRF validation, redirect policy, auth header binding, OAuth state, PKCE where relevant, token storage, and minimal scopes. Browser-based: no concrete provider imports, provider-managed profiles, locking, takeover, redacted artifacts, centralized targets, no credentials in screenshots, and session reconciliation.
