# Publication Execution

Owned website publication uses the existing execution phases: `prepared`, `mutation_started`, `mutation_acknowledged`, `mutation_verified`, `remote_acknowledged`, and `publication_verified`.

The Markdown Website channel does not create a second retry engine. Uncertain Git pushes require reconciliation before any further mutation.
