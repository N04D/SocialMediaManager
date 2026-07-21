# Publication Execution Security

Execution records expose IDs, statuses, phases, mutation state, retry decisions, lease status, safe error codes, and shortened snapshot checksums.

They do not expose:

- content bodies;
- confirmation tokens;
- browser session IDs;
- takeover URLs;
- storage references;
- local paths;
- provider secrets;
- full remote payloads;
- stack traces.

Boundary tests assert that core execution imports no channel code, execution services import no LinkedIn runtime or browser provider, and LinkedIn imports no execution repositories.

