(function () {
  "use strict";

  var state = {
    initialized: false,
    consent: false,
    consentMode: "after_external_consent",
    pageContext: {},
    events: {},
    sentKeys: {},
    sink: null
  };

  var propertyRules = {
    page_id: 80,
    content_id: 80,
    revision_id: 80,
    publication_id: 80,
    campaign_id: 80,
    cta_id: 80,
    cta_type: 32,
    placement: 80,
    destination_origin_class: 32,
    conversion_id: 80,
    conversion_type: 32,
    outcome: 32,
    smm_attribution_id: 120,
    utm_source: 80,
    utm_medium: 80,
    utm_campaign: 120,
    utm_content: 120
  };

  function safeText(value, limit) {
    var text = String(value || "");
    return text.replace(/[^A-Za-z0-9_.:/ -]/g, "").slice(0, limit || 80);
  }

  function attribution() {
    var params = new URLSearchParams(window.location.search || "");
    var out = {};
    ["utm_source", "utm_medium", "utm_campaign", "utm_content", "smm_attribution_id"].forEach(function (key) {
      if (params.has(key)) {
        out[key] = safeText(params.get(key), propertyRules[key]);
      }
    });
    return out;
  }

  function allowedProps(extra) {
    var raw = {};
    ["page_id", "content_id", "revision_id", "publication_id", "campaign_id"].forEach(function (key) {
      raw[key] = state.pageContext[key.replace("_id", "Id")] || state.pageContext[key] || "";
    });
    Object.keys(extra || {}).forEach(function (key) {
      raw[key] = extra[key];
    });
    Object.keys(attribution()).forEach(function (key) {
      raw[key] = attribution()[key];
    });
    var clean = {};
    Object.keys(raw).forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(propertyRules, key)) {
        clean[key] = safeText(raw[key], propertyRules[key]);
      }
    });
    return clean;
  }

  function canSend() {
    return state.consentMode !== "disabled" && (state.consentMode === "always_enabled" || state.consent === true);
  }

  function emit(eventName, props) {
    if (!canSend()) {
      return { sent: false, reason: "consent_denied" };
    }
    var payload = {
      name: safeText(eventName, 80),
      props: allowedProps(props || {})
    };
    var key = payload.name + ":" + JSON.stringify(payload.props);
    if (state.sentKeys[key]) {
      return { sent: false, reason: "duplicate" };
    }
    state.sentKeys[key] = true;
    if (typeof state.sink === "function") {
      state.sink(payload);
    }
    if (window.SMMAnalyticsBridge && typeof window.SMMAnalyticsBridge.send === "function") {
      window.SMMAnalyticsBridge.send(payload.name, payload.props);
    }
    return { sent: true, payload: payload };
  }

  function contextFromElement(element, kind) {
    if (!element || !element.getAttribute) {
      return {};
    }
    if (kind === "cta") {
      return {
        cta_id: element.getAttribute("data-smm-cta-id") || "",
        cta_type: element.getAttribute("data-smm-cta-type") || "custom",
        placement: element.getAttribute("data-smm-placement") || "",
        destination_origin_class: "same_origin"
      };
    }
    if (kind === "conversion") {
      return {
        conversion_id: element.getAttribute("data-smm-conversion-id") || "",
        conversion_type: element.getAttribute("data-smm-conversion-type") || "custom",
        cta_id: element.getAttribute("data-smm-cta-id") || "",
        outcome: "completed"
      };
    }
    return {
      destination_origin_class: "allowed_external",
      placement: element.getAttribute("data-smm-placement") || ""
    };
  }

  function delegated(event) {
    var target = event.target && event.target.closest ? event.target.closest("[data-smm-track]") : null;
    if (!target) {
      return;
    }
    var track = target.getAttribute("data-smm-track");
    if (track === "cta") {
      emit(state.events.cta_click || "SMM CTA Click", contextFromElement(target, "cta"));
    } else if (track === "conversion") {
      emit(state.events.conversion || "SMM Conversion", contextFromElement(target, "conversion"));
    } else if (track === "outbound") {
      emit(state.events.outbound_click || "SMM Outbound Click", contextFromElement(target, "outbound"));
    }
  }

  function initialize(config) {
    if (state.initialized) {
      return { initialized: true, duplicate: true };
    }
    var cfg = config || {};
    state.consentMode = cfg.consentMode || "after_external_consent";
    state.consent = state.consentMode === "always_enabled";
    state.pageContext = cfg.pageContext || {};
    state.sink = cfg.testSink || null;
    (cfg.events || []).forEach(function (item) {
      state.events[item.event_type] = item.event_name;
    });
    document.addEventListener("click", delegated, true);
    document.addEventListener("keydown", function (event) {
      if ((event.key === "Enter" || event.key === " ") && event.target && event.target.matches("[data-smm-track]")) {
        delegated(event);
      }
    }, true);
    state.initialized = true;
    return { initialized: true, duplicate: false };
  }

  window.SMMAnalytics = {
    initialize: initialize,
    setConsent: function (value) {
      state.consent = value === true;
    },
    trackCta: function (elementOrContext) {
      return emit(state.events.cta_click || "SMM CTA Click", elementOrContext && elementOrContext.getAttribute ? contextFromElement(elementOrContext, "cta") : elementOrContext);
    },
    trackOutbound: function (elementOrContext) {
      return emit(state.events.outbound_click || "SMM Outbound Click", elementOrContext && elementOrContext.getAttribute ? contextFromElement(elementOrContext, "outbound") : elementOrContext);
    },
    trackConversion: function (context) {
      return emit(state.events.conversion || "SMM Conversion", context || {});
    },
    getStatus: function () {
      return { initialized: state.initialized, consent: state.consent, consentMode: state.consentMode };
    }
  };
})();
