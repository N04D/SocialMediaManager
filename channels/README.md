# Channel Plugins

Each direct subfolder inside `channels/` is a drop-in plugin candidate.

A plugin is discovered when the folder contains a valid `channel.manifest.json`.
The server scans the folder at startup and on manual rescan through the channels
API or Config UI.

Minimal plugin:

```text
channels/
  blog/
    channel.manifest.json
    README.md
```

Full plugin layout used by the LinkedIn MVP:

```text
channels/
  linkedin/
    channel.manifest.json
    rules.yaml
    prompts/
      linkedin-post.md
    server/
      index.py
      actions.py
    worker/
      index.py
      browser.py
      session.py
      connect.py
      publish.py
      metrics.py
    README.md
```

Manifest-driven fields are rendered in `Config > Channels`. Invalid manifests do
not crash the application; they surface as registry health errors instead.

