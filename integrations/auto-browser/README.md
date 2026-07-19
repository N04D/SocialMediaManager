# Auto Browser Integration

Phase 5 treats Auto Browser as an external browser controller. The application does not vendor Auto Browser code and does not require it to start.

Tested upstream:

- Repository: `LvcidPsyche/auto-browser`
- Server release: `v1.4.0`
- Server commit: `a7414a4`
- Python packages inspected: `auto-browser-client==1.4.0`, `auto-browser-mcp==1.4.0`
- Transport used by this app: deterministic REST, not MCP agent transport

Configure locally through `config.json` and environment secrets:

```json
{
  "auto_browser_enabled": true,
  "auto_browser_base_url": "http://127.0.0.1:8081",
  "auto_browser_bearer_token_env": "AUTO_BROWSER_BEARER_TOKEN",
  "auto_browser_operator_id": "social-media-manager",
  "auto_browser_expected_server_version": "1.4.0"
}
```

Security defaults:

- Bind the controller and takeover viewer to localhost unless you have a protected private network.
- Store the bearer token only in the referenced environment variable.
- Keep TLS verification enabled for non-local URLs.
- Do not enable captcha solving, stealth, or platform-security bypass features.
- Do not copy legacy Playwright cookies into Auto Browser profiles automatically.

Migration route for an existing LinkedIn account:

1. Select `provider.browser.autobrowser` for the LinkedIn channel account.
2. Run LinkedIn Connect.
3. Complete one manual login through the generic human takeover route.
4. Let the provider save the Auto Browser auth profile.
5. Run session check.
6. Publish, metrics, and scraping can then reuse the Auto Browser profile.
7. Switching back to `provider.browser.legacy` reuses the existing legacy browser profile.

Doctor checks should remain non-destructive: health, readiness, version, feature availability, and auth only. They must not open LinkedIn or publish content.
