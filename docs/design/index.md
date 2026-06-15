# Design Overview

Activist is designed around one idea: automation may help draft and triage content, but a human should remain responsible for what is actually said and when it is said.

That leads to three operational roles in the design:

- a fetcher that gathers source material and drafts candidate posts
- a local review UI where a human approves, edits, or rejects those drafts
- a poster that handles scheduled publication

In the current code, the first two roles are fully implemented and the third role exists only as a dry-run simulation. That is an important design choice, not just a missing integration: the code deliberately makes accidental live posting difficult.

## Design sources

These docs summarize both the implementation and the design notes in `spec/`:

- `spec/real_overview.md`
- `spec/fetcher_service.md`
- `spec/admin_ui.md`
- `spec/poster_service.md`
- `README.md`

The design pages avoid planning language and instead describe the intended steady-state system, while clearly calling out parts that are not implemented.
