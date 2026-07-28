# Website Instrumentation Security Boundaries

Instrumentation records use opaque IDs for content, revisions, publications,
campaigns, CTAs, conversions, and attribution. They are correlation IDs, not
authentication tokens.

Instrumentation payloads exclude article bodies, visitor IP addresses, user
agents, cookie IDs, fingerprints, names, email addresses, full unknown
querystrings, form input, and arbitrary properties. Unknown properties are
dropped by default.

The backend may render manifests, templates, frontmatter bindings, sidecar JSON,
and verification reports. It must not send tracking events to providers, install
tracking code into user-owned repositories, overwrite active website files, or
place cookies or persistent visitor storage.
