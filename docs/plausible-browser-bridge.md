# Plausible Browser Bridge

Documentation basis, retrieved 2026-07-28:

- Plausible custom event goals: https://plausible.io/docs/custom-event-goals
- Plausible custom properties for events: https://plausible.io/docs/custom-props/for-custom-events
- Plausible Events API reference: https://plausible.io/docs/events-api

The browser bridge maps central SMM event names to Plausible browser-side
custom events through the public `plausible(eventName, { props })` interface.
Only allowlisted properties are forwarded. The bridge contains no Stats API
token, API key, site mutation path, or backend write path.

The Plausible Events API records pageviews and custom events at `/api/event`,
but SocialMediaManager backend services do not call that endpoint. Browser-side
reference code may send events only after a website operator installs it in a
site.
