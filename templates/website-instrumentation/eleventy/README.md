# Eleventy Website Instrumentation

Use the data cascade to expose the generated page context to a layout include.
Load `/instrumentation/smm-analytics.js`; the CTA component writes only allowlisted `data-smm-*` attributes.
No credentials or provider API tokens are included in the template.
