# Content Performance Analytics

Content readmodels aggregate compatible publication metrics by content item, revision, channel variant, media, channel, account, and campaign dimensions.

Rules:

- Use latest valid cumulative metric per unique publication.
- Sum across unique publications only.
- Keep incompatible channel metrics separate.
- Preserve revision and variant context.
- Report freshness, completeness, sample size, and warnings.
- Do not include full content bodies in general analytics responses.

Revision and variant comparisons are observational. The UI and API warn when channels, windows, samples, or campaign contexts differ.
