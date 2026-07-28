# Generic Website Instrumentation

Include `/instrumentation/smm-analytics.js` and, for Plausible, `/instrumentation/plausible-bridge.js`.
Render the generated `smm-analytics-config` JSON script and public meta markers in the page head.
Mark CTAs with `data-smm-track="cta"` and conversion triggers with `data-smm-track="conversion"`.
Use CSP script directives that allow the managed static runtime and the provider browser script only.
This reference contains no credentials, no inline secret, no automatic install, and no site build command.
