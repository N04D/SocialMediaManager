# Reconciliation Queue

Reconciliation items are durable and categorized as deployment pending, push uncertain, public URL mismatch, revision marker mismatch, content drift, media missing, dependency stalled, social publish uncertain, and analytics attribution issues.

Automatic checks are read-only. They may re-check a remote commit, URL marker, dependency, analytics binding, or derived readmodel. They do not push, repost, overwrite content, force-push, delete media, remove dependencies, or repeat an uncertain mutation.
