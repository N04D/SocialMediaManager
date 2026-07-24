# Plugin Host Browser Proxy

Browser-based external plugins receive opaque browser handles, not concrete providers or Playwright objects. Handles bind plugin host, context, workspace, account, provider, execution attempt, and expiry. The existing Browser Framework remains the only browser abstraction.
