# Markdown Website Security Boundaries

Repository and path access is allowlist-based. Public APIs do not accept arbitrary filesystem paths, raw remotes, raw credentials, SSH command strings, private keys, executable names, force-push options, or site build commands.

The real project `content/` and `drafts/` directories are user-owned and are not used as plugin fixtures or publication roots.
