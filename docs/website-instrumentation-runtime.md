# Website Instrumentation Runtime

`web/instrumentation/smm-analytics.js` is a dependency-free reference runtime.
It exposes `SMMAnalytics.initialize`, `trackCta`, `trackOutbound`,
`trackConversion`, `setConsent`, and `getStatus`.

The runtime sends only centrally allowlisted properties, does not accept
arbitrary event names, and does not read form values or DOM text as analytics
payload. It uses no cookies, `localStorage`, `sessionStorage`, fingerprinting,
`eval`, `new Function`, or `innerHTML`.

Consent modes are technical modes only: `disabled`, `always_enabled`, and
`after_external_consent`. Phase 26 does not provide legal consent advice or a
consent banner.
