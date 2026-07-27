# Publication Dependencies

`PublicationTargetDependency` gates one publication target on another target reaching a required execution state. The website-first funnel uses `publication_verified` on the Markdown Website target before LinkedIn or Mastodon targets become claimable.

The graph rejects self-dependencies and cycles. Failed or uncertain predecessors block dependents; timeouts do not silently bypass verification.
