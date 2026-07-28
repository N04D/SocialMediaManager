# Website Analytics Security Boundaries

The provider framework is read-only. Authorization headers are injected by the
host-owned HTTP facade and are never persisted, logged, shown in UI, exposed
through MCP, or included in support bundles.

The account model stores `secret_reference_id`, never raw tokens. The origin
registry is host-owned; public APIs do not accept arbitrary hosts, ports,
schemes, proxies, file URLs, or credentials in URLs.

Observations store safe dimensions only: UTM fields, `smm_attribution_id`,
landing path context, event names, CTA IDs, and conversion types. IP addresses,
user agents, cookies, visitor IDs, names, email addresses, and unknown
querystring parameters are discarded.
