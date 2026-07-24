# Plugin Host Architecture

Each active external plugin version gets one child process for `plugin id + version`. Built-in plugins remain in-process. External provider and media plugins stay disabled until a complete adapter exists. There is no in-process fallback.
