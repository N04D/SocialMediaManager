# Markdown Website Architecture

The flow is `content revision -> website variant -> deterministic Markdown -> safe Git mutation -> optional push -> public URL verification -> dependent LinkedIn/Mastodon release -> funnel analytics`.

Repository access is mediated by `WebsiteRepositoryReference`. Public APIs use `repository_reference_id`; they do not accept raw repository URLs, raw filesystem paths, SSH commands, tokens, or private keys.
