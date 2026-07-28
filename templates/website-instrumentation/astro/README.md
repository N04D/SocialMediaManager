# Astro Website Instrumentation

Use an Astro layout to render the manifest markers and JSON page context from frontmatter.
Load `smm-analytics.js` as a static asset and mount CTA components with `data-smm-*` attributes.
Connect external consent by calling `window.SMMAnalytics.setConsent(true)`.
No Astro build is executed by Social Media Manager.
