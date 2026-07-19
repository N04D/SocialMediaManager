# Pipeline LinkedIn Flow Classification

Phase 5 scope decision:

| Flow | Uses LinkedIn | Uses channel account | Uses browser profile | Externally publishes | Dashboard/worker reachable | Category | Capability |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `stage_linkedin_post_impl` | yes | no channel-runtime account | yes, legacy Playwright profile | stages a manual draft | CLI and legacy dashboard launch | legacy/manual tooling | not claimed in plugin manifest |
| `stage_linkedin_article_impl` | yes | no channel-runtime account | yes, legacy Playwright profile | stages/schedules article draft | CLI and article launch UI | legacy/manual tooling | not claimed in plugin manifest |
| `open_linkedin_feed` | yes | no channel-runtime account | yes, legacy Playwright profile | no | CLI/dashboard browser helper | legacy/manual tooling | not claimed in plugin manifest |
| `open_linkedin_article_editor` | yes | no channel-runtime account | yes, legacy Playwright profile | no, opens editor | CLI/dashboard browser helper | legacy/manual tooling | not claimed in plugin manifest |
| local RSS/content/AI processing | no channel browser operation | no | no | no | CLI/dashboard | generic staging functionality | outside channel plugin scope |

Boundary enforced in code:

- When the LinkedIn channel account explicitly selects `provider.browser.autobrowser`, legacy/manual pipeline LinkedIn browser entrypoints raise an unsupported legacy-flow error.
- The active `channel.linkedin` runtime remains responsible for provider-managed connect, session check, publish, metrics, and scraping.
- The LinkedIn manifest does not claim article publishing as an active channel capability in phase 5.

Phase 6 should either migrate article publishing into `LinkedInChannelRuntime` or remove/keep it as explicit manual tooling with clearer UI separation.
