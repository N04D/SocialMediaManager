# CI Artifact Source Framework

CI artifact sources implement a provider-neutral read-only contract:

- validate origin;
- list matching workflow runs;
- get a concrete run and attempt;
- list artifacts for that run;
- download a concrete artifact by provider identity;
- report health and rate-limit state.

The artifact name is a filter, not identity. Identity is origin, run ID, run
attempt, and artifact ID.
