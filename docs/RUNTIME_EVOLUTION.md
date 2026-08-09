# Runtime Evolution

Phase 41 introduced contracts for a generic local-first workflow runtime without changing existing social publication behavior.
Phase 42 adds portable playbook contracts, deployment bindings, side-effect-free execution plans, and an in-memory execution ledger.
Phase 43 adds the first deterministic executor for internal/test capabilities only.
Phase 44 connects the first read-only production capability bridge: `calendar.event.read`.
Phase 45 connects the second read-only production capability bridge: `git.repository.status.read`.

## Scope

- No rewrite.
- Existing Python stack, plugins, scheduler/workers, storage, dashboard, LinkedIn, YouTube, Markdown Website/Git, calendar, and analytics behavior remain unchanged.
- No production platform playbook execution is introduced in this phase.
- The only production bridge introduced in Phase 44 is local read-only calendar access.
- Phase 45 adds local read-only repository status access only.
- No destructive storage migration is introduced in this phase.

## Future Runtime Shape

```mermaid
flowchart TD
    ExternalIn[External Platform]
    ComponentIn[Component]
    Event[Event]
    Playbook[Future Playbook Runtime]
    Install[Install]
    ComponentOut[Component]
    ExternalOut[External Platform]

    ExternalIn --> ComponentIn
    ComponentIn -->|emits| Event
    Event --> Playbook
    Playbook -->|requires capability| Install
    Install -->|resolves| ComponentOut
    ComponentOut --> ExternalOut
```

The side-effectful production Playbook Runtime is future work. Phase 43 executes only internal/test capabilities. Production platform capabilities remain on the legacy path.

Phase 44 keeps that boundary and adds one narrow exception: `calendar.event.read` can be executed through a production adapter that calls the existing local `ExecutionCalendarService`. This bridge is read-only and does not add calendar create/update/delete, external calendar providers, browser automation, HTTP calls, or production social mutations.

Phase 45 adds a second narrow read-only bridge for local Website/Git repository state. It does not connect file writes, website publication, GitHub APIs, remote fetch/pull, Git push, or arbitrary Git commands.

## Phase 42 Portable Playbooks

```mermaid
flowchart TD
    PlaybookDefinition[PlaybookDefinition]
    RequirementA[requirement A]
    RequirementB[requirement B]
    Deployment[PlaybookDeployment]
    InstallA[Install A]
    InstallB[Install B]
    ComponentsA[Components]
    ComponentsB[Components]
    ExecutionPlan[ExecutionPlan]

    PlaybookDefinition -->|requires| RequirementA
    PlaybookDefinition -->|requires| RequirementB
    RequirementA --> Deployment
    RequirementB --> Deployment
    Deployment -->|binds requirements| InstallA
    Deployment -->|binds requirements| InstallB
    InstallA --> ComponentsA
    InstallB --> ComponentsB
    ComponentsA --> ExecutionPlan
    ComponentsB --> ExecutionPlan
```

```mermaid
flowchart TD
    Event[Event]
    ExecutionRecord[ExecutionRecord]
    NodeExecutionRecords[NodeExecutionRecords]

    Event --> ExecutionRecord
    ExecutionRecord --> NodeExecutionRecords
```

The distinction is explicit:

- `PlaybookDefinition` is portable intent. It can require logical slots and capabilities, but it must not contain install IDs, account IDs, workspace IDs, tokens, credentials, or secret references.
- `PlaybookDeployment` is environment-specific binding. It maps requirement slots to concrete installs and may contain non-secret configuration.
- `ExecutionPlan` is resolved representation. It contains concrete install/component/capability resolution and is produced without executing components.
- `ExecutionLedger` records execution and node state transitions for future observability, retries, approvals, and audit.

## New Contracts

| Contract | File | Purpose |
| --- | --- | --- |
| Event | `src/core/runtime/events.py` | Universal event envelope with source, correlation, causation, external ID, idempotency key, payload, and metadata. |
| Capability | `src/core/runtime/capabilities.py` | Extensible dot-namespaced capability descriptor with `read`, `write`, and `event` modes. |
| Component | `src/core/runtime/components.py` | Technical implementation manifest that can provide multiple capabilities. |
| Install | `src/core/runtime/installs.py` | Configured account/workspace instance with capability-to-component bindings and secret references only. |
| Resolver | `src/core/runtime/resolver.py` | Resolves `install_id + capability` to an install and component manifest. |
| Compatibility adapter | `src/core/runtime/legacy.py` | Describes capabilities from legacy plugin manifests without changing plugin behavior. |
| Phase 41 mappings | `runtime_foundation_mappings.py` | Concrete PoC component manifests and sample installs for existing domains, kept outside the generic core. |
| PlaybookDefinition | `src/core/runtime/playbooks.py` | Portable, versioned DAG definition with logical capability requirements, nodes, and edges. |
| PlaybookDeployment | `src/core/runtime/deployments.py` | Workspace binding from playbook requirement slots to concrete installs, validated through the capability resolver. |
| ExecutionPlan | `src/core/runtime/plans.py` | Deterministic, side-effect-free resolved plan containing install and component selections. |
| ExecutionLedger | `src/core/runtime/ledger.py` | Protocol plus in-memory implementation for execution and node execution state history. |
| ExecutionContext | `src/core/runtime/execution_context.py` | Per-execution context with trigger event, correlation/trace IDs, variables, and completed node outputs. |
| NodeResult | `src/core/runtime/results.py` | Handler result contract with `success`, `failure`, `wait`, and `skip` outcomes. |
| CapabilityHandler | `src/core/runtime/handlers.py` | Technical execution contract keyed by component and capability. |
| PlaybookExecutor | `src/core/runtime/executor.py` | Deterministic DAG orchestrator that updates the ledger and calls registered internal handlers only. |
| ExecutionTrace | `src/core/runtime/tracing.py` | Structured helper for execution, node execution, and transition history. |
| CalendarEventReadHandler | `publication_calendar_runtime_handlers.py` | Read-only production adapter from `calendar.event.read` to the existing `ExecutionCalendarService`. |
| GitRepositoryStatusReadHandler | `publication_git_runtime_handlers.py` | Read-only production adapter from `git.repository.status.read` to the existing Markdown Website `GitPublisher`. |

## Phase 43 Deterministic Executor

```mermaid
flowchart TD
    EventEnvelope[EventEnvelope]
    Deployment[PlaybookDeployment]
    Plan[ExecutionPlan]
    Executor[PlaybookExecutor]
    NodeExecutor[Node execution loop]
    HandlerRegistry[CapabilityHandlerRegistry]
    Handler[Component Handler]
    Result[NodeResult]
    Ledger[ExecutionLedger]

    EventEnvelope --> Deployment
    Deployment --> Plan
    Plan --> Executor
    Executor --> NodeExecutor
    NodeExecutor --> HandlerRegistry
    HandlerRegistry --> Handler
    Handler --> Result
    Result --> Ledger
    Executor --> Ledger
```

Execution lifecycle:

```mermaid
flowchart TD
    Event[Event]
    Plan[ExecutionPlan]
    Pending[ExecutionRecord: PENDING]
    Running[RUNNING]
    NodeA[Node A]
    NodeB[Node B]
    Succeeded[SUCCEEDED]

    Event --> Plan
    Plan --> Pending
    Pending --> Running
    Running --> NodeA
    NodeA --> NodeB
    NodeB --> Succeeded
```

WAIT lifecycle:

```mermaid
flowchart TD
    Running[RUNNING]
    NodeWait[Node WAIT]
    Waiting[Execution WAITING]
    Resume[resume]
    RunningAgain[RUNNING]
    Succeeded[SUCCEEDED]

    Running --> NodeWait
    NodeWait --> Waiting
    Waiting --> Resume
    Resume --> RunningAgain
    RunningAgain --> Succeeded
```

Phase 43 execution boundaries:

- `PlaybookDefinition` remains portable intent and contains no install IDs, account IDs, tokens, or secret references.
- `PlaybookDeployment` binds logical requirements to installs before execution.
- `ExecutionPlan` contains concrete install/component selections but no transport details or secret values.
- `PlaybookExecutor` executes a validated DAG deterministically and sequentially.
- Capability handlers are resolved by `component_id + capability_id`, not by capability alone.
- Input resolution supports literals, trigger event payload paths, and previous node outputs. It does not use Python eval, JavaScript, Jinja, or arbitrary expression execution.
- Conditions support a small deterministic operator set: `equals`, `not_equals`, `exists`, `gt`, `gte`, `lt`, `lte`, and `contains`.
- Transform nodes are deterministic/internal only, such as identity, field mapping, and uppercase string transformation.
- Retry is attempt-count based with no sleep/backoff in Phase 43.
- WAIT/resume is supported for internal handlers. No external callbacks, timers, approvals, or platform listeners are introduced.
- The Phase 43 reference flow uses only `test.*` capabilities and internal handlers.

Production isolation:

- `PluginRuntime`, `LinkedInChannelRuntime`, `YouTubeChannelService`, `GitPublisher`, and `ExecutionCalendarService` are not called by the Phase 43 executor.
- Existing dashboard, worker, scheduler, plugin runtime, and channel production paths remain unchanged.
- No LinkedIn publish/reply, YouTube upload, Git write/push, calendar mutation, browser automation, HTTP/API call, subprocess call, Research/RAG, agent planning, or visual editor behavior is added.

## Phase 44 Calendar Read Bridge

```mermaid
flowchart TD
    EventEnvelope[EventEnvelope]
    Playbook[Portable Playbook]
    Deployment[PlaybookDeployment]
    Plan[ExecutionPlan]
    Executor[PlaybookExecutor]
    Registry[CapabilityHandlerRegistry]
    Handler[CalendarEventReadHandler<br/>READ ONLY]
    Service[ExecutionCalendarService]
    Storage[Local Calendar Storage]

    EventEnvelope --> Playbook
    Playbook --> Deployment
    Deployment --> Plan
    Plan --> Executor
    Executor --> Registry
    Registry --> Handler
    Handler --> Service
    Service --> Storage
```

Current calendar responsibilities:

- `ExecutionCalendarService.list_calendar_entries` reads local publication calendar entries from schedule occurrences and publication targets.
- Existing UI/API routes call the same service directly, especially `/api/execution-calendar` and the content calendar page.
- The service supports workspace, start/end range, timezone label, channel plugin, campaign, status, attention-required, and limit filtering.
- `ExecutionCalendarService.summarize_range` is also read-only, but Phase 44 does not expose it as a generic capability.
- Calendar mutations remain in existing scheduling/campaign services such as schedule creation, materialization, pause/resume/cancel, and campaign coordination.

Safe `calendar.event.read` output:

- The production adapter returns normalized event dictionaries with IDs, title, start/end, status, timezone, source, workspace, entry type, safe schedule/campaign/target references, attention flag, blockers, and safe summary.
- It does not return repository objects, ORM/dataclass instances, storage paths, credentials, secret references, browser/session data, or arbitrary metadata dumps.

Business logic that must not move into the generic runtime:

- Recurrence calculation, materialization, schedule lifecycle, campaign coordination, authorization consumption, publication target lifecycle, and UI/API routing stay in the existing scheduling/calendar services.
- The generic executor has no `if calendar.event.read` switch. It only resolves a component/capability handler and records deterministic execution state.

Production adapter pattern:

- `CalendarEventReadHandler` lives outside `src/core/runtime/`.
- Registration is explicit through `register_calendar_runtime_handlers(handler_registry, calendar_service=...)`.
- The handler registers only `calendar.event.read` for component `publication-calendar-local`.
- No hidden import-time global registration is used.
- Later component packaging can describe `publication-calendar-local` as providing `calendar.event.read` with `CalendarEventReadHandler` as its handler entrypoint, without adding marketplace or dynamic installation in Phase 44.

## Phase 45 Git/Website Read Bridge

Inspection findings:

| Read operation | Existing implementation | Uses filesystem? | Uses subprocess? | Uses network? | Mutation risk? | Currently exposed where? |
| --- | --- | --- | --- | --- | --- | --- |
| Repository branch/HEAD state | `GitPublisher.head_state` | Reads Git worktree metadata | `git branch --show-current`, `git rev-parse --verify HEAD`, `git cat-file -e`, and for unborn repos `git rev-parse --is-inside-work-tree` | No | Read-only commands when called directly | Markdown Website publisher preflight/evidence |
| Worktree status | `GitPublisher.git(..., "status", "--porcelain")` and `changed_paths` | Reads worktree/index state | `git status --porcelain` | No | Read-only command when arguments are fixed | Publication preflight/conflict detection |
| Commit verification reads | `GitPublisher.verify_commit` | Reads Git object metadata | `git cat-file`, `git rev-parse`, `git show --name-only` | No | Read-only commands when commit ID is known from publish flow | Publication verification |
| File content read | No general public capability found | N/A | N/A | N/A | Would need path policy and output contract | Not exposed as a generic read capability |

Chosen capability:

- `github.file.read` remains too broad because the existing Markdown Website code does not expose general repository file-content reads.
- Phase 45 therefore bridges `git.repository.status.read`.
- The name is semantically accurate: the handler returns local repository state, branch, HEAD commit, clean/dirty status, and optionally changed paths.
- The capability belongs to the existing `github-markdown-website` component because that component represents the local Markdown Website Git worktree transport.
- The capability mode is `read`.

```mermaid
flowchart TD
    Executor[PlaybookExecutor]
    Registry[CapabilityHandlerRegistry]
    CalendarHandler[CalendarReadHandler]
    GitHandler[GitRepositoryStatusReadHandler]
    CalendarService[Calendar Service]
    GitService[Git/Website Service]
    LocalDB[Local DB]
    LocalRepo[Local Repository]

    Executor --> Registry
    Registry --> CalendarHandler
    Registry --> GitHandler
    CalendarHandler --> CalendarService
    GitHandler --> GitService
    CalendarService --> LocalDB
    GitService --> LocalRepo
```

Phase 45 runtime path:

```text
Event
-> Portable Playbook
-> PlaybookDeployment
-> ExecutionPlan
-> PlaybookExecutor
-> CapabilityHandlerRegistry
-> GitRepositoryStatusReadHandler
-> GitPublisher
-> normalized NodeResult
-> ExecutionLedger
```

Read-only Git safety:

- The handler does not accept a command string.
- The input contract only accepts `include_changed_paths`.
- Invalid fields such as `command`, `path`, `../secret.txt`, or `/etc/passwd` are rejected because this capability is not path-based.
- `GitRepositoryStatusReadHandler` uses `WebsiteRepositoryReference` and existing repository validation.
- Runtime tests observe only fixed read-only Git commands: `branch --show-current`, `rev-parse --verify HEAD`, `cat-file -e <commit>^{commit}`, `status --porcelain`, and `rev-parse --is-inside-work-tree` for unborn repositories.
- Mutating and remote commands such as `add`, `commit`, `push`, `reset`, `checkout`, `clean`, `merge`, `rebase`, `fetch`, `pull`, `tag`, and `ls-remote` are blocked by tripwire tests.
- Repository integrity tests prove HEAD, tracked files, and tracked contents are preserved across runtime execution.

Legacy isolation:

- Existing `GitPublisher.publish`, Website publication, reconciliation, GitHub Pages/public URL verification, and UI/API flows remain unchanged.
- The new route is additive:

```text
Generic Runtime
-> GitRepositoryStatusReadHandler
-> GitPublisher
```

while the current production Website path remains:

```text
Current Website flow
-> GitPublisher.publish
```

## Phase 46 External Network Read Bridge

Phase 46 connects exactly one production network read capability to the generic runtime:

```text
youtube.video.metadata.read
```

Inspection findings:

| Candidate capability | Existing implementation | Actually uses network? | Authenticated? | Read-only? | Returns remote data? | Side effects? | Suitable for Phase 46? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `youtube.transcript.import` | `YouTubeSourcePlugin.import_source` parses caller-supplied transcript and stores local content | No | No | No, local import/write | No remote data | Writes local content records | No |
| `youtube.transcript.read` | `YouTubeSourcePlugin.parse_timestamped_transcript` parses supplied text; health reports transcript retrieval `not_configured` | No | No | Local parse only | No remote data | None for parse | No |
| `youtube.video.read` | `YouTubeSourcePlugin.validate_video_ref` validates URL/video ID and import metadata | No | No | Local validation/import support | No remote data | Import path writes local content | No |
| `youtube.publication.status.read` | `YouTubeChannelService.reconcile` calls `YouTubeTransport.get_video` for uploaded publication evidence | Yes | Yes, access token | Yes | Yes | None in `get_video`; tied to publication evidence status update | Partial |
| `youtube.video.metadata.read` | `YouTubeChannelService.read_video_metadata` calls existing `YouTubeTransport.get_video` | Yes | Yes, access token | Yes | Yes | None | Yes |

`youtube.video.metadata.read` is semantically correct because it reads remote YouTube Data API video metadata through the existing channel service and transport. It is more precise than `youtube.video.read` and avoids claiming transcript retrieval, which the current source plugin explicitly reports as not configured.

Phase 46 runtime path:

```text
Event
-> Portable Playbook
-> PlaybookDeployment
-> ExecutionPlan
-> PlaybookExecutor
-> CapabilityHandlerRegistry
-> YouTubeVideoMetadataReadHandler
-> YouTubeChannelService
-> HttpYouTubeTransport.get_video
-> External Network GET
-> normalized NodeResult
-> ExecutionLedger
```

Egress policy:

- The generic `ComponentManifest` now has a forward-compatible `network_policy` dictionary.
- `youtube-upload-channel` declares `network_policy.required = true`.
- Allowed domains are `www.googleapis.com` for YouTube Data API reads/uploads and `oauth2.googleapis.com` for the existing OAuth token endpoint.
- No wildcard egress is declared.
- The Phase 46 reference execution observes one `GET` request to `https://www.googleapis.com/youtube/v3/videos`.
- The handler accepts only `video_id`. It rejects URLs, arbitrary domains, metadata endpoints, local addresses, file URIs, and caller-controlled HTTP methods.

Authentication boundary:

- Playbooks contain no account IDs, install IDs, tokens, or secrets.
- Deployments bind the logical `youtube_source` requirement to a concrete install.
- Installs contain only config and secret references such as `access_token_ref`; raw tokens are resolved only at the production handler boundary.
- Access tokens are passed to the existing service/transport and never written into `ExecutionContext`, `NodeResult`, `ExecutionLedger`, or trace output.

Retry and timeout ownership:

- `HttpYouTubeTransport` already requires a bounded timeout and passes it to `urllib.request.urlopen`.
- Phase 46 does not add a second transport retry loop.
- Node-level retry remains owned by `PlaybookExecutor` through node config.
- Tests assert the success path performs exactly one network attempt.

External error normalization:

- Timeouts/network failures map to structured runtime failure.
- YouTube 429 maps to `RATE_LIMITED`.
- Authentication failure maps to `YOUTUBE_AUTHENTICATION_REQUIRED`.
- Missing videos map to `YOUTUBE_VIDEO_NOT_FOUND`.
- Malformed provider responses map to `YOUTUBE_RESPONSE_MALFORMED`.
- Provider response bodies, authorization headers, cookies, and raw token data are not exposed as runtime output.

Three production bridge proof:

```mermaid
flowchart TD
    Executor[PlaybookExecutor]
    Registry[CapabilityHandlerRegistry]
    CalendarRead[CalendarRead]
    GitRead[GitRead]
    RemoteRead[RemoteRead]
    CalendarService[Local Service]
    GitService[Git Service]
    YouTubeService[YouTube Service]
    LocalDB[Local DB]
    Repository[Repository]
    Network[Network]

    Executor --> Registry
    Registry --> CalendarRead
    Registry --> GitRead
    Registry --> RemoteRead
    CalendarRead --> CalendarService
    GitRead --> GitService
    RemoteRead --> YouTubeService
    CalendarService --> LocalDB
    GitService --> Repository
    YouTubeService --> Network
```

The generic runtime now supports production capabilities backed by local service I/O, local repository/subprocess I/O, and external network I/O without provider-specific branching in the core.

## Phase 47 Runtime Policy, Permissions, and Approval Gates

Phase 47 adds runtime authorization for the generic PlaybookExecutor path. No production mutation capability is enabled.

Inspection findings:

| Security concept | Existing repository shape | Phase 47 use |
| --- | --- | --- |
| Secret references | Channel configs and managed secret services use `*_secret_ref`, `secret_refs`, and redaction helpers. | Runtime policy validates only refs/scopes. Raw values stay at production handler boundaries. |
| Plugin permissions | Plugin manifests already list broad permissions such as `outbound_network`, `secret_storage`, and `media_read`. | Component manifests now expose generic technical `permissions` for runtime execution. |
| Component egress | Phase 46 added `network_policy` to `ComponentManifest`. | `RuntimePolicyEngine` evaluates network required/allowed domains before handler invocation. |
| Install ownership | `Install` already binds capabilities to components and stores secret refs. | `InstallGrants` now explicitly allows/denies capabilities and sensitive privileges. |
| Deployment config | `PlaybookDeployment` already binds portable requirements to installs. | `DeploymentPolicy` can only restrict effective permissions; it cannot grant beyond component/install. |
| WAIT/resume | Phase 43 supports WAITING executions and resume. | Approval gates reuse WAITING semantics before handler execution. |
| Audit/trace | `ExecutionLedger` stores node executions and append-only transitions. | Policy decisions are recorded in node metadata/transition metadata without secrets. |

Effective permission model:

```text
Component Permissions
        ∩
Install Grants
        ∩
Deployment Policy
        ↓
Effective Permission
        ↓
Policy Decision
        ↓
ALLOW / DENY / APPROVAL_REQUIRED
```

Execution policy flow:

```mermaid
flowchart TD
    Plan[ExecutionPlan]
    Executor[PlaybookExecutor]
    Policy[RuntimePolicyEngine]
    Allow[ALLOW]
    Deny[DENY]
    Approval[APPROVAL]
    Handler[CapabilityHandler]
    Waiting[WAITING]
    Decision[approve/reject]

    Plan --> Executor
    Executor --> Policy
    Policy --> Allow
    Policy --> Deny
    Policy --> Approval
    Allow --> Handler
    Approval --> Waiting
    Waiting --> Decision
```

Deterministic evaluation order:

1. Deployment enabled.
2. Install enabled.
3. Component provides the capability.
4. Capability explicitly denied.
5. Capability explicitly granted.
6. Mutation allowed for write capabilities.
7. Network required/allowed.
8. Required egress domains allowed by install and deployment.
9. Filesystem access allowed.
10. Subprocess access allowed.
11. Required secret refs present and granted.
12. Approval requirement.
13. ALLOW.

Sensitive privileges are default-deny in the generic runtime policy layer:

- write/mutation;
- network egress;
- secret usage;
- filesystem access;
- subprocess access.

Approval semantics:

- Policy checks run after deterministic input resolution and before handler lookup/invocation.
- `DENY` returns a structured runtime failure and handler invocation count remains zero.
- `APPROVAL_REQUIRED` creates an `ApprovalRecord`, moves the node and execution to `WAITING`, and stores policy metadata in the ledger.
- `approve_execution_node()` marks the approval approved and resumes the waiting node.
- `reject_execution_node()` marks the approval rejected, fails the waiting node, and fails the execution.
- Approval cannot override hard denies such as `NETWORK_NOT_ALLOWED`, `SECRET_NOT_GRANTED`, or `MUTATION_NOT_ALLOWED`.

Production bridge permissions:

| Bridge | Capability | Component permissions | Install grants used in tests |
| --- | --- | --- | --- |
| Calendar | `calendar.event.read` | no network, no filesystem, no subprocess, no secrets | capability grant only |
| Git | `git.repository.status.read` | filesystem read, read-only Git subprocess, no network | capability + filesystem + subprocess |
| YouTube | `youtube.video.metadata.read` | network to `www.googleapis.com`/`oauth2.googleapis.com`, scoped secret ref, no subprocess/filesystem | capability + network domains + `youtube-access-token-ref` |

The only write capability used in Phase 47 is synthetic and internal:

```text
test.resource.write
```

It mutates only in-memory test state. It is used to prove mutation deny, approval wait, approval resume, rejection, and duplicate approval behavior without enabling a production mutation path.

### Phase 48 approved production mutation

Phase 48 connects exactly one production mutation to the generic runtime:

```text
calendar.event.create
-> publication-calendar-local
-> ScheduleOccurrenceRepository.create
-> local publication calendar JSON storage
```

Mutation inspection:

| Capability candidate | Existing service method | Local/external | Mutation type | Reversible? | Existing identifier? | Transaction/idempotency support | Suitable? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `calendar.event.create` | `ScheduleOccurrenceRepository.create` through the local publication scheduling stack | Local | Create a publication calendar occurrence record | Yes in tests through isolated temp storage; production data remains local JSON | `occurrence_key` and `id` | JSON store lock plus duplicate `occurrence_key` returns the existing occurrence | YES |
| `calendar.event.update` | Occurrence/schedule save/update paths exist | Local | Update existing scheduling state | More invasive because it changes existing records | Existing record IDs | Existing save methods, but broader state semantics | NO for Phase 48 |
| Git/Website write | `GitPublisher.publish` | Local + remote risk | File write/commit/push | Not small enough; may push externally | Commit/hash/path | Git idempotency is publication-specific | NO |
| LinkedIn/YouTube publish/reply/upload | Channel services | External | Platform mutation | Not reversible locally | Provider IDs | Provider-specific | NO |

The chosen mutation is intentionally scoped to the local publication calendar. The capability output uses a stable `resource_ref`:

```text
calendar-occurrence:<occurrence_id>
```

Phase 48 introduces generic mutation contracts:

- `MutationIntent`: exact normalized write input, input fingerprint, capability, component, install, execution, and idempotency key.
- `MutationReceipt`: durable record of the applied mutation, resource reference, applied timestamp, result fingerprint, and safe metadata.
- `MutationJournal`: durable state interface with `prepared`, `approved`, `applying`, `applied`, and `failed` states.
- `JsonMutationJournal`: minimal file-backed journal adapter matching the repository's existing JSON-storage style.

Write lifecycle:

```mermaid
flowchart TD
    Write[Write Node]
    Policy[Policy]
    Intent[MutationIntent]
    Approval[Approval Required]
    Waiting[WAITING]
    Recheck[Policy Recheck]
    Journal[Idempotency / Journal]
    Handler[Production Handler]
    Receipt[MutationReceipt]
    Readback[Readback Verification]

    Write --> Policy
    Policy --> Intent
    Intent --> Approval
    Approval --> Waiting
    Waiting -->|approve| Recheck
    Recheck --> Journal
    Journal --> Handler
    Handler --> Receipt
    Receipt --> Readback
```

Approval authorizes an exact `MutationIntent`, not a generic capability. The runtime binds approval to the intent's `mutation_id` and deterministic input fingerprint. If input changes after approval, the old approval is invalid and the node returns to `WAITING` for a new approval. Policy is also re-evaluated immediately before handler invocation, so approval does not freeze or escalate permissions.

Phase 48 does not claim universal exactly-once delivery. It establishes durable idempotency semantics for the selected local production mutation by combining:

- explicit runtime mutation idempotency keys;
- a durable mutation journal;
- the existing `ScheduleOccurrenceRepository.create` duplicate-`occurrence_key` behavior;
- read-after-write verification through `ExecutionCalendarService.list_calendar_entries`.

The production handler lives outside the generic runtime in `publication_calendar_runtime_handlers.py` as `CalendarEventCreateHandler`. It adapts normalized capability input to the existing scheduling repository and returns a normalized receipt. The generic core contains no `calendar.event.create` branch.

### Phase 49 compensation and journal hardening

Phase 49 does not add a second production mutation capability. `calendar.event.create` remains the only production write capability connected to the generic runtime.

Inspection findings:

| Question | Result |
| --- | --- |
| Can created occurrence be deleted by stable ID? | No existing `ScheduleOccurrenceRepository.delete/remove` method was found. |
| Is delete already implemented? | No. Existing methods are `create`, `save`, `get`, `find_by_key`, `list_all`, and `list_by_schedule`. |
| Is delete local? | Not applicable; no existing delete inverse exists. |
| Is delete transaction-safe? | Not applicable; no existing delete inverse exists. |
| Does `JsonMutationJournal` survive restart? | Yes, it persists records to JSON. |
| Is `JsonMutationJournal` atomic? | It writes via temp-file replace, but it is not a multi-process transaction/claim mechanism. |
| Is it safe across processes/workers? | No. It remains suitable for local/dev and simple tests, not production multi-worker mutation claiming. |
| Is there existing SQLite transactional storage? | Yes. Several repository areas use SQLite with transactions/claims; Phase 49 adds a runtime-local SQLite journal without adding a new DB stack. |

Compensation proof for `calendar.event.create` is therefore:

```text
COMPENSATION PROOF: BLOCKED
```

The blocker is intentional. Phase 49 does not invent calendar delete functionality and does not expose `calendar.event.delete`. A future phase can make calendar create compensatable only after an existing safe inverse operation exists or the domain owner explicitly adds one outside the generic core.

Rollback and compensation are distinct:

```text
ROLLBACK
= undo an uncommitted transaction

COMPENSATION
= logically undo an already applied mutation
  through a new controlled and auditable side effect
```

Compensation is not mathematically equivalent to rollback. Phase 49 introduces generic compensation contracts but blocks production calendar compensation because the inverse operation is missing:

- `CompensatableMutationHandler`
- `CompensationIntent`
- `CompensationReceipt`
- `CompensationJournalRecord`
- `CompensationState`

The runtime still fingerprints node-level compensation policy as part of `MutationIntent`. Approval for:

```text
compensation.mode = none
```

cannot silently become approval for:

```text
compensation.mode = on_downstream_failure
```

Recovery and hardened journal model:

```mermaid
flowchart TD
    Journal[Mutation Journal]
    Prepared[PREPARED]
    Approved[APPROVED]
    Applying[APPLYING]
    Applied[APPLIED]
    Compensating[COMPENSATING]
    Compensated[COMPENSATED]

    Journal --> Prepared
    Journal --> Approved
    Journal --> Applying
    Journal --> Applied
    Journal --> Compensating
    Journal --> Compensated
```

`SqliteMutationJournal` is the production-safe journal adapter for the generic mutation runtime. It uses:

- `UNIQUE idempotency_key`;
- `BEGIN IMMEDIATE` transactions;
- atomic `claim_applying`;
- atomic `claim_compensating`;
- durable mutation and compensation records;
- explicit `recover_mutation(...)` for stale `APPLYING` reconciliation.

A production mutation must be claimed atomically before execution so duplicate workers cannot apply the same intent concurrently.

Recovery is side-effect aware. `recover_mutation(...)` does not blindly retry an `APPLYING` record. It requires a caller-provided readback/verifier:

```text
APPLYING
-> verifier finds resource
-> mark APPLIED

APPLYING
-> verifier does not find resource
-> return to APPROVED for safe retry
```

For the selected local calendar mutation, the verifier can use the stable occurrence key/resource identity and `ExecutionCalendarService.list_calendar_entries`.

Because production compensation is blocked, the Phase 49 reference failure flow is not enabled for calendar create. The generic contracts and journal states are present for future compensatable components, but no internal calendar delete is registered and no public delete capability is added.

## Current Inventory

| Area | Current abstraction | Future abstraction | Compatibility strategy | Migration candidate | Risk |
| --- | --- | --- | --- | --- | --- |
| Plugin base classes/protocols | `PluginLifecycle` protocol and `PluginContext`; async channel runtime base exists in `plugin_sdk`. | Component lifecycle remains technical; business workflows move to future playbooks. | Leave protocols intact. Use `LegacyCapabilityAdapter` to describe capabilities from existing manifests. | Add component manifests beside plugin manifests as plugins opt in. | Medium |
| Plugin loader/registry | `plugin_runtime.bootstrap_plugins` registers built-in manifests; `PluginRegistry` maps capability strings to plugin IDs. | Runtime registry maps component IDs and install IDs; resolution is install-scoped. | Do not alter `bootstrap_plugins`; new `RuntimeRegistry` is separate. | Optional bridge from `ApplicationPluginRuntime` to `RuntimeRegistry`. | Low |
| Config models | `pipeline.AppConfig` and `config.json` contain app/provider settings; channel state lives in `studio_data`. | Install config carries account/workspace config and secret references only. | Keep existing config as source of truth. | Generate installs from channel connections and config later. | Medium |
| Account/channel config | `ChannelConnection` in `channel_models.py`, stored through `channel_store.py`. | `Install` becomes account/workspace runtime identity with component bindings. | No migration now. Installs are in-memory/sample only. | Convert channel connections to install records later. | Medium |
| Secret handling | Managed secret metadata under `src/core/managed_secrets`; config schemas use `secret_ref`. | `Install.secret_refs` and `ComponentManifest.required_secrets` contain references only. | New models reject secret-shaped config keys unless they end in `_ref`. | Persist install secret refs using managed secret references. | Low |
| Scheduler | Legacy `scheduler.py` uses `outbox`; newer `publication_scheduling.py` uses `studio_data`. | Calendar capabilities describe local publication-calendar reads and schedule mutations. | No storage migration. Existing scheduler services keep running. | Add component-backed calendar adapter later. | Low |
| Worker/job models | `worker.py` processes legacy schedule records and channel publish/metric jobs. | Future executions consume events/playbooks and resolve capabilities. | No worker changes. Existing job models remain authoritative. | Execution attempts can later carry event/correlation IDs. | Medium |
| Workflow/playbook models | Business flows are embedded in pipeline, planning, scheduling, execution, and `plugins/playbooks/creator_commerce`. | Playbooks own business logic and request capabilities. | Document only; no migration. | Extract business decisions after capabilities are stable. | High |
| Event/task models | Domain-specific audit/scheduling events exist; no universal event envelope exists. | `EventEnvelope` provides universal event identity, source, tracing, idempotency, payload, and metadata. | New envelope does not replace domain events yet. | Wrap domain events at boundaries later. | Low |
| Database/schema/migrations | Mostly file-backed JSON under `studio_data` and `outbox`; some local DB files exist in other domains. | Components/installs can later persist in config/storage. | No migration now because contracts are sufficient and least invasive. | Add forward-compatible JSON stores later. | Low |
| LinkedIn plugin | `channel.linkedin` mixes browser transport, session actions, publish, metrics, and scraping. | `linkedin-browser-channel` component; `linkedin.post.create/read`, `linkedin.analytics.read`. | Map only existing behavior. No comment reply or DM capability declared. | Split browser transport from channel business flow later. | Medium |
| YouTube plugin | `source.youtube` imports video/transcripts; `channel.youtube` handles OAuth and video/short publish/status. | Separate source/import and upload components under same provider. | Two components prove capability does not equal component. | Convert OAuth/upload transport to component implementation later. | Medium |
| Website/GitHub | Markdown Website channel and `GitPublisher` publish Markdown into controlled Git worktrees. | `github-markdown-website` component. | Map constrained Git worktree behavior only; no broad GitHub API capability. | Persist repository install bindings later. | Medium |
| Calendar/agenda | No external calendar provider. Local execution calendar exists via scheduling services. | `publication-calendar-local` component. | Map local publication-calendar only. | Bind schedules/occurrences to future event envelope. | Low |
| Analytics | `analytics.service`, metric definitions, LinkedIn metrics, website analytics/Plausible read models. | Analytics read capabilities can be component capabilities. | Only existing read/collect behavior is mapped. | Add event emission around metric ingestion later. | Medium |

## Mixed Responsibility Hotspots

| Location | Current mix | Phase 41 note |
| --- | --- | --- |
| `channels/linkedin/runtime.py` | Browser transport selection, account/session state, publish action, metrics scraping, and post scraping. | Mapped as `linkedin-browser-channel`; future split should move transport into component and workflow choices into playbooks. |
| `channels/youtube/channel.py` | OAuth connection, validation, resumable upload, publish confirmation, reconciliation/status. | Mapped as `youtube-upload-channel`; source import remains separate. |
| `plugin_runtime.py` | Plugin discovery, dependency validation, service construction, provider resolution, and shared service registration. | Left unchanged; future runtime can derive component registry from it. |
| `publication_scheduling.py` | Schedule business policy, occurrence materialization, persistence, and calendar read models. | Mapped as local calendar capabilities only; playbook extraction is later. |
| `channels/markdown_website/git_publisher.py` | Technical Git mutation plus publication evidence construction and verification. | Mapped as Git/website component, but no generic GitHub API is claimed. |

## Capability Inventory

| Provider | Capability | Existing implementation | Component mapping | Status |
| --- | --- | --- | --- | --- |
| LinkedIn | `linkedin.connection.start` | `LinkedInChannelRuntime.connect` | `linkedin-browser-channel` | MAPPED |
| LinkedIn | `linkedin.connection.read` | `LinkedInChannelRuntime.connection_status` / `check_session` | `linkedin-browser-channel` | MAPPED |
| LinkedIn | `linkedin.post.create` | `LinkedInChannelRuntime.publish` and legacy `stage_linkedin_post` flow | `linkedin-browser-channel` | MAPPED |
| LinkedIn | `linkedin.post.read` | `LinkedInChannelRuntime.scrape_posts` | `linkedin-browser-channel` | MAPPED |
| LinkedIn | `linkedin.analytics.read` | `LinkedInChannelRuntime.collect_metrics` | `linkedin-browser-channel` | MAPPED |
| LinkedIn | `linkedin.comment.reply` | No implementation found | None | NOT IMPLEMENTED |
| LinkedIn | `linkedin.dm.received` | No implementation found | None | NOT IMPLEMENTED |
| YouTube | `youtube.video.read` | `YouTubeSourcePlugin.validate_video_ref` / import metadata | `youtube-source-import` | PARTIAL |
| YouTube | `youtube.video.metadata.read` | `YouTubeChannelService.read_video_metadata` through `YouTubeTransport.get_video` | `youtube-upload-channel` | MAPPED |
| YouTube | `youtube.transcript.read` | `YouTubeSourcePlugin.parse_timestamped_transcript` for supplied transcript | `youtube-source-import` | PARTIAL |
| YouTube | `youtube.transcript.import` | `YouTubeSourcePlugin.import_source` | `youtube-source-import` | MAPPED |
| YouTube | `youtube.video.publish` | `YouTubeChannelService.publish` | `youtube-upload-channel` | MAPPED |
| YouTube | `youtube.short.publish` | `YouTubeChannelService.publish` with short validation | `youtube-upload-channel` | MAPPED |
| YouTube | `youtube.publication.status.read` | `YouTubeChannelService.reconcile` | `youtube-upload-channel` | MAPPED |
| Website/GitHub | `github.file.read` | No general file-content read capability found; Phase 41 mapping was broader than the current implementation proves | `github-markdown-website` | PARTIAL |
| Website/GitHub | `git.repository.status.read` | `GitPublisher.head_state` and fixed `git status --porcelain` read | `github-markdown-website` | MAPPED |
| Website/GitHub | `github.file.write` | `GitPublisher.publish` writes/stages/commits/pushes allowed paths | `github-markdown-website` | MAPPED |
| Website/GitHub | `website.article.publish` | Markdown Website render/publish flow | `github-markdown-website` | MAPPED |
| Website/GitHub | `website.publication.verify` | Markdown Website verification/evidence flow | `github-markdown-website` | MAPPED |
| Website/GitHub | `website.analytics.read` | Website analytics read models/provider framework | `github-markdown-website` | PARTIAL |
| Calendar | `calendar.event.read` | `ExecutionCalendarService.list_calendar_entries` | `publication-calendar-local` | MAPPED |
| Calendar | `calendar.event.create` | `ScheduleOccurrenceRepository.create` via `CalendarEventCreateHandler` | `publication-calendar-local` | MAPPED |
| Calendar | `calendar.event.update` | Schedule/campaign/occurrence state updates | `publication-calendar-local` | PARTIAL |
| Calendar | External calendar sync | No Google/Microsoft/CalDAV implementation found | None | NOT IMPLEMENTED |

## Persistence Decision

Phase 41 uses an in-memory runtime registry with deterministic serialization for contracts. This is the least invasive option because existing durable state already lives in `config.json`, `studio_data`, `outbox`, and channel-specific stores.

Future persistence can add forward-compatible JSON stores under `studio_data/runtime_components.json` and `studio_data/runtime_installs.json`. Rollback should be deleting those additive files only, leaving existing channel and scheduler data untouched.

Phase 42 follows the same least-invasive persistence decision. `ExecutionLedger` is a protocol and `InMemoryExecutionLedger` is the first implementation. No SQLite migration or new durable store is added yet because the current repository has several file-backed stores and no single generic runtime database boundary. A future durable ledger can be added as an adapter without changing `ExecutionRecord` or `NodeExecutionRecord`.

Phase 43 keeps the same persistence boundary. The executor writes only to the provided `ExecutionLedger` implementation. Tests use `InMemoryExecutionLedger`; no database migration or file-backed execution store is added.

Phase 44 does not add persistence. Calendar reads use existing local calendar storage through `ExecutionCalendarService`; execution state still uses the provided ledger implementation.

Phase 45 does not add persistence. Repository reads use the existing local Git worktree and the provided execution ledger only.

Phase 46 does not add persistence. YouTube metadata reads use the existing YouTube channel service and transport; execution state still uses the provided ledger implementation.

Phase 47 does not add durable policy persistence. `InstallGrants`, `DeploymentPolicy`, policy decisions, and approval records are in-memory/runtime-contract objects for now. Durable policy and approval storage can be added later as an adapter without changing the policy decision contract.

Phase 48 adds a minimal durable mutation journal adapter. Tests use `JsonMutationJournal` against temporary storage; production callers can provide a concrete journal path. Rollback is additive: remove the journal file and unregister the mutation handler. Existing scheduling JSON data and legacy routes are not migrated or rewritten.

## Compatibility Strategy

- Existing `PluginManifest`, `PluginRegistry`, `PluginRuntime`, `ProviderResolver`, channel runtimes, scheduler, and workers are unchanged.
- New contracts are exposed from `src.core.runtime`.
- `LegacyCapabilityAdapter` can describe selected existing plugin capabilities as generic component capabilities.
- PoC manifests live in `runtime_foundation_mappings.py` as `phase41_component_manifests()` and sample installs in `phase41_sample_installs()`.
- Existing plugin capability strings remain valid and are not replaced in this phase.
- Playbook validation and plan compilation do not call channel runtimes, browser providers, HTTP clients, Git, or plugin services.
- Phase 43 execution does not call legacy channel runtimes, browser providers, HTTP clients, Git, subprocesses, or plugin services. Only explicitly registered internal handlers can execute.
- Phase 44 introduces an explicit production handler registration for the local calendar read adapter only. Existing calendar UI/API/scheduler callers still use `ExecutionCalendarService` directly and are not converted to playbook execution.
- Phase 45 introduces an explicit production handler registration for local Git repository status read only. Existing Website/Git production callers are not converted to playbook execution.
- Phase 46 introduces an explicit production handler registration for external YouTube video metadata reads only. Existing YouTube import, OAuth, upload, status reconciliation, UI, and worker flows are not converted to playbook execution.
- Phase 47 policy enforcement applies only to the generic `PlaybookExecutor` when configured with a `RuntimePolicyEngine`. Legacy production routes remain unchanged and are not blocked by missing `InstallGrants`.
- Phase 48 adds an explicit production mutation registration for local publication-calendar occurrence creation only. Existing calendar UI/API/scheduler callers still use the scheduling services directly and are not converted to playbook execution.

## Phase 42 Validation Decisions

- Playbook graphs must be DAGs for now. Bounded loops can be introduced later as explicit schema features.
- Node kinds are limited to known schema kinds or namespaced third-party kinds; unknown plain strings fail with a controlled validation error.
- Capability nodes reference a logical requirement slot and a capability declared by that requirement.
- Deployment validation resolves each required capability through `CapabilityResolver` before any execution can exist.
- Compile-time capability reports use structured entries with requirement, capability, install, component, status, and error code fields.
- The generic execution state machine supports `pending`, `running`, `waiting`, `succeeded`, `failed`, `cancelled`, and `skipped`.
- Ledger transitions are append/audit oriented: records are updated to current state, while transition history is retained separately.

## Security Notes

- `Install` stores `secret_refs` only.
- `ComponentManifest.required_secrets` stores references/requirements only.
- `EventEnvelope` rejects secret-shaped payload or metadata keys.
- No runtime secret values were added to repository files.
- `PlaybookDefinition` rejects environment-specific and secret-shaped fields such as `install_id`, `account_id`, `workspace_id`, `token`, and `secret`.
- `PlaybookDeployment`, `ExecutionRecord`, and `NodeExecutionRecord` reject secret-shaped config/metadata values unless they are explicit references.
- `ExecutionPlan` contains concrete install/component IDs but no component config, secret refs, or secret values.
- `ExecutionContext`, `NodeResult`, and `ExecutionTrace` reject or omit obvious secret-shaped values.
- Arbitrary code evaluation is not used for input mapping, conditions, or transforms.
- External mutations are not possible in the Phase 43 reference flow because only internal/test handlers are registered and side-effect paths are covered by tests.
- Phase 44 `calendar.event.read` rejects secret-shaped handler input, normalizes output, and remains read-only when only read handlers are registered.
- Phase 45 `git.repository.status.read` rejects secret-shaped and arbitrary command/path input, exposes no write handler, uses no caller-controlled shell command, and is covered by Git mutation, remote-network, and repository-integrity tripwire tests.
- Phase 46 `youtube.video.metadata.read` rejects secret-shaped input, accepts only a provider video ID, exposes no caller-controlled URL/endpoint/method, and is covered by upload/OAuth mutation, subprocess, SSRF-style input, credential-leakage, timeout, and structured provider-error tests.
- Phase 47 enforces capability grants, network, secret scope, filesystem, subprocess, mutation, and approval policy before handler invocation. Policy metadata uses neutral keys such as `access_scope` so secret-shaped trace fields are rejected by existing runtime guards.
- Phase 48 requires approval for the first production mutation even when install/deployment policy allows writes. `MutationIntent`, `MutationReceipt`, journal records, approval records, ledger metadata, and trace output contain no raw credentials or secret-shaped fields. Duplicate approval, retry, resume, duplicate trigger delivery, and failure-after-apply paths are covered by idempotency tests for the selected local calendar mutation.
