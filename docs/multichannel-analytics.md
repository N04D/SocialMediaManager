# Multichannel Analytics

Comparable groups:

- LinkedIn reactions and Mastodon favourites: `reaction_count`.
- LinkedIn comments and Mastodon replies: `comment_count`.
- LinkedIn reposts/shares and Mastodon reblogs: `share_count`.

Multichannel comparisons are `valid_with_warnings` because platform context, measurement windows, and interaction meanings differ. Counts are observational and not causal.

Do not compare LinkedIn impressions, views, clicks, or reach with Mastodon missing metrics. Mastodon missing denominators are represented as `unavailable_by_channel`, and engagement rate by impressions is `null` with reason `denominator_unavailable`.
