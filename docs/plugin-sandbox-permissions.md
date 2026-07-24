# Sandbox Permissions

Manifest permissions are converted into a least-privilege sandbox policy.

- `outbound_network` allows `host.http.request`; it does not allow direct sockets.
- `browser_session` allows `host.browser.*`; it does not allow launching browsers.
- `secret_storage` allows scoped secret callbacks only.
- `media_read` and `media_materialization` allow call-scoped media transfers only.
- `analytics_ingestion` and `execution_reporting` allow broker callbacks only.
- `subprocess` is unsupported for community channel plugins in phase 20.

Broad direct permissions such as `filesystem_all`, `network_all`, `home_access`, `host_process_access`, `kernel_access`, `device_access`, `arbitrary_subprocess`, and `direct_network` are incompatible with phase 20.
