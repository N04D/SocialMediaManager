# GitHub CI Origin Onboarding

GitHub Actions origins are host-owned references. Operators select a registered GitHub API origin, repository owner/name/identity, exact workflow identity or path, allowed branches, allowed events, artifact name patterns and a managed credential reference.

The public flow does not accept arbitrary GitHub URLs, artifact URLs, repository download links or workflow dispatch targets.

The doctor validates authentication, repository identity, workflow identity, run listing access, artifact listing access, branch/event policies and rate-limit state. It does not download artifacts and does not perform write probes.
