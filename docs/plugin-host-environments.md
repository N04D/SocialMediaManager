# Plugin Host Environments

Every external plugin version uses its own virtual environment with `system_site_packages=False`, isolated mode (`python -I`), no inherited `PYTHONPATH` or `PYTHONHOME`, no pip runtime use, no source tree on sys.path, and only verified installed plugin code plus host-owned SDK/runtime. A venv is dependency isolation, not an OS sandbox.
