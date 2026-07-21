# Multichannel Publication

One `ContentItem` can produce one `PublicationPlan` with both `channel.linkedin` and `channel.mastodon` targets. Each target carries its own account, variant, media relations, options, requirements checksum, snapshot checksum, and execution attempt.

LinkedIn may use a browser provider. Mastodon is API-first. The execution dispatcher does not import either runtime directly; it queues targets and workers resolve channel runtimes through plugin runtime.

Partial failure preserves terminal evidence per target. A Mastodon pre-mutation failure may be retried after revalidation. A Mastodon uncertain mutation requires operator review and never causes a duplicate LinkedIn publication.
