# YouTube destination plugin

`channel.youtube` consumes generic managed short-video assets and confirmed
generic caption/title variants. It uses the official YouTube Data API v3
resumable `videos.insert` protocol and read-only `videos.list` reconciliation.

The default is private, with subscriber notifications disabled. OAuth tokens
and resumable session URLs are sensitive and are never rendered or logged.
The real upload smoke is intentionally separate from the offline test suite.
