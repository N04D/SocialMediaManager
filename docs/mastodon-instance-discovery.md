# Mastodon Instance Discovery

Discovery starts with a user-provided origin and calls `GET /api/v2/instance`.

Validation rejects userinfo, paths, query strings, fragments, non-HTTP(S) schemes, production HTTP, private/loopback/link-local/multicast/reserved IPs, and cross-origin redirects. HTTP localhost is allowed only with the explicit fixture/development flag.

Snapshots include server/API version, official Mastodon compatibility status, status length, media count, URL character policy, MIME support, image byte/pixel limits, media description limit, PKCE/media support flags, rate-limit header support, expiry, warnings, and a capability checksum.

Planning stores the requirements checksum. Stale or changed limits block new preparation/execution until refreshed.
