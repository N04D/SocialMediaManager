# Content Funnel Dashboard

The funnel view connects:

```text
Social impressions -> Social engagement -> Link clicks -> Website visits -> Engaged visits -> CTA clicks -> Conversions
```

Rates are shown from the previous step and the first step, with zero-division guarded. Data quality is explicit: `complete`, `partial`, `delayed`, `unattributed`, or `conflicting`.

No causal claim is made from correlated publication and metric data.

Phase 23 stores observations durably and rebuilds derived readmodels. Incomplete attribution remains visible, and readmodel rebuilds never mutate source observations.
