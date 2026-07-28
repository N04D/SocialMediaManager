# CI Certification Security Boundaries

Phase 29 blocks:

- arbitrary GitHub repository or workflow URLs;
- artifact URLs as user input;
- artifact name as sole identity;
- fork and pull request runs by default;
- wrong-commit evidence;
- unsigned or unimported CI evidence as trusted;
- GitHub write operations;
- private key persistence.

Provider digest and internal package checksum are separate verification layers.
Fase 20.2 remains separately blocked with `production_ready=false`.
