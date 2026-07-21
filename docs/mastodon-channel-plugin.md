# Mastodon Channel Plugin

`channel.mastodon` is the second channel plugin because Mastodon has an official REST API for connect, publish, media upload, and metrics. It proves that the channel runtime can publish without a browser provider.

The plugin exposes only:

- `channel.connect`
- `channel.disconnect`
- `channel.status`
- `channel.publish.text`
- `channel.publish.image`
- `channel.metrics.collect`
- `channel.health`

It does not implement ActivityPub, forks, browser automation, server-side scheduling, replies, polls, threads, DMs, editing, deletion, video, or audio.

Architecture:

`MastodonChannelRuntime` owns `MastodonApiClient`, `MastodonApiTransport`, OAuth, instance discovery, requirements, publish, and metrics adapters. Planning, execution, media, content, and analytics remain provider-neutral.
