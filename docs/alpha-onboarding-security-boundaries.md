# Alpha Onboarding Security Boundaries

Onboarding state stores no secret values, tokens, browser cookies, private keys, article bodies, raw provider responses, or repository contents. Real mode uses registered resources only and rejects arbitrary repository paths. Analytics writes are never sent by the backend. Approvals and four-eyes policies remain enforced by existing services.
