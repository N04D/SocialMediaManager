(function () {
  "use strict";

  var allowed = {
    page_id: true,
    content_id: true,
    revision_id: true,
    publication_id: true,
    campaign_id: true,
    cta_id: true,
    cta_type: true,
    placement: true,
    destination_origin_class: true,
    conversion_id: true,
    conversion_type: true,
    outcome: true,
    smm_attribution_id: true,
    utm_source: true,
    utm_medium: true,
    utm_campaign: true,
    utm_content: true,
    smm_synthetic_run_id: true
  };

  function clean(props) {
    var out = {};
    Object.keys(props || {}).forEach(function (key) {
      if (allowed[key]) {
        out[key] = String(props[key]).slice(0, 160);
      }
    });
    return out;
  }

  window.SMMAnalyticsBridge = {
    provider: "analytics.plausible",
    version: "0.1.0",
    send: function (eventName, props) {
      if (typeof window.plausible !== "function") {
        return { sent: false, reason: "plausible_runtime_missing" };
      }
      window.plausible(String(eventName).slice(0, 80), { props: clean(props || {}) });
      return { sent: true };
    },
    getStatus: function () {
      return { provider: "analytics.plausible", runtimePresent: typeof window.plausible === "function" };
    }
  };
})();
