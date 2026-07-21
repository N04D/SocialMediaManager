# Channel Content Requirements

`ChannelContentRequirements` is registered by channel plugins and evaluated by `ContentRequirementRegistry`.

Generic fields include body/title requirements, body length, supported languages, hashtag support, mentions, links, line breaks, media requirement flags, maximum media items, and whether a variant is required.

LinkedIn registers:

- `channel_plugin_id = "channel.linkedin"`
- `capability = "channel.publish.text"`
- body required
- title retained as metadata, not sent as a separate composer field
- canonical direct-use allowed when requirements pass
- maximum media items aligned with the LinkedIn media requirement set

The validator reports machine-readable violations. It never truncates or rewrites text.

