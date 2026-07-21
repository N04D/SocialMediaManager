# Plugin Wheel Security

Wheels are inspected as ZIP files without importing plugin code. The verifier rejects traversal, absolute paths, drive paths, UNC-like paths, null bytes, control characters, symlink-like entries, duplicate normalized paths, case collisions, excessive path length, excessive file count, excessive uncompressed size, native binaries, startup hooks, bundled SDK copies, forbidden dependencies, secrets, and reserved namespaces.
