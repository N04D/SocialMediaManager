# Media Library Security

Media library responses expose safe metadata only:

- asset ID;
- display and original filename;
- media type and MIME;
- dimensions;
- file size;
- status;
- shortened checksum;
- timestamps;
- inspection status;
- relation and usage counts;
- suitability.

Responses do not expose storage references, object paths, local materialized paths, Auto Browser transfer paths, EXIF, GPS, embedded comments, provider secrets, cookies, or browser artifacts.

The preview endpoint supports JPEG and PNG only, checks workspace ownership and asset status, streams bytes through the storage provider, and sends safe headers including `X-Content-Type-Options: nosniff`.

Integrity scans are read-only. Safe repair is limited to future counter rebuilds and stale operational usage expiry; unknown objects, publication evidence, and user content are not automatically deleted or rewritten.
