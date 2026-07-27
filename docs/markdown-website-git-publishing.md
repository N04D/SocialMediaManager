# Markdown Website Git Publishing

Git commands are executed with fixed argument lists and `shell=False`. The publisher stages only exact mutation manifest paths and never uses broad commands such as `git add .`, `git add -A`, force push, hard reset, or clean.

Dirty unrelated files are preserved. Dirty overlap on target paths blocks publication with `conflicting_user_change`.
