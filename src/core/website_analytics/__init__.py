"""Website Analytics Provider Framework v0.1 public surface."""

from .contracts import (
    PLAUSIBLE_ANALYTICS_ADAPTER_VERSION,
    WEBSITE_ANALYTICS_ACCOUNT_CONTRACT_VERSION,
    WEBSITE_ANALYTICS_ATTRIBUTION_CONTRACT_VERSION,
    WEBSITE_ANALYTICS_CURSOR_CONTRACT_VERSION,
    WEBSITE_ANALYTICS_DATA_QUALITY_CONTRACT_VERSION,
    WEBSITE_ANALYTICS_EVENT_MAPPING_CONTRACT_VERSION,
    WEBSITE_ANALYTICS_PROVIDER_CONTRACT_VERSION,
    WEBSITE_ANALYTICS_PROVIDER_FRAMEWORK_VERSION,
    WEBSITE_ANALYTICS_SYNC_CONTRACT_VERSION,
)
from .errors import WebsiteAnalyticsError, WebsiteAnalyticsProviderError
from .models import (
    AnalyticsProviderOriginReference,
    ProviderMetricObservation,
    WebsiteAnalyticsAccount,
    WebsiteAnalyticsAttribution,
    WebsiteAnalyticsDataQualityReport,
    WebsiteAnalyticsEventMapping,
    WebsiteAnalyticsQuery,
    WebsiteAnalyticsSyncState,
)
from .service import WebsiteAnalyticsService

__all__ = [
    "AnalyticsProviderOriginReference",
    "PLAUSIBLE_ANALYTICS_ADAPTER_VERSION",
    "ProviderMetricObservation",
    "WEBSITE_ANALYTICS_ACCOUNT_CONTRACT_VERSION",
    "WEBSITE_ANALYTICS_ATTRIBUTION_CONTRACT_VERSION",
    "WEBSITE_ANALYTICS_CURSOR_CONTRACT_VERSION",
    "WEBSITE_ANALYTICS_DATA_QUALITY_CONTRACT_VERSION",
    "WEBSITE_ANALYTICS_EVENT_MAPPING_CONTRACT_VERSION",
    "WEBSITE_ANALYTICS_PROVIDER_CONTRACT_VERSION",
    "WEBSITE_ANALYTICS_PROVIDER_FRAMEWORK_VERSION",
    "WEBSITE_ANALYTICS_SYNC_CONTRACT_VERSION",
    "WebsiteAnalyticsAccount",
    "WebsiteAnalyticsAttribution",
    "WebsiteAnalyticsDataQualityReport",
    "WebsiteAnalyticsError",
    "WebsiteAnalyticsEventMapping",
    "WebsiteAnalyticsProviderError",
    "WebsiteAnalyticsQuery",
    "WebsiteAnalyticsService",
    "WebsiteAnalyticsSyncState",
]
