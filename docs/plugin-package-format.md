# Plugin Package Format

Phase 18 accepts only pure-Python `py3-none-any` wheels. Sdists, source zip archives, editable installs, VCS installs, platform wheels, native extensions, direct URL dependencies, console scripts, GUI scripts, `.pth`, `sitecustomize.py`, credential files, embedded virtualenvs, and package-index configuration are rejected.

The project-owned entrypoint group is `social_media_manager.plugins`. A wheel declares exactly one entrypoint named exactly like the plugin id.
