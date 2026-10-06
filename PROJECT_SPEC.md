# Automated Job Outreach

Status: **proposal, awaiting approval before Phase 1**

The spec is split by topic under [`specs/`](specs/README.md). That folder is the implementation contract.

| Spec | Contents |
| --- | --- |
| [specs/README.md](specs/README.md) | Scope and the decisions locked for the MVP |
| [specs/architecture.md](specs/architecture.md) | Workflow, processes, layout, future AI hooks |
| [specs/data-model.md](specs/data-model.md) | Tables, relationships, statuses |
| [specs/google-sheet.md](specs/google-sheet.md) | The one shared sheet, sync, and sent / not-sent marks |
| [specs/profile-matching.md](specs/profile-matching.md) | Keyword matching, resume and template selection, preview |
| [specs/email-pipeline.md](specs/email-pipeline.md) | Queue, rate limits, retries, dry run |
| [specs/api.md](specs/api.md) | REST endpoints |
| [specs/frontend.md](specs/frontend.md) | Screens |
| [specs/security-and-operations.md](specs/security-and-operations.md) | Config, security, tests, Docker |
| [specs/implementation-plan.md](specs/implementation-plan.md) | Phases 1–10 |

The app reads one Google Sheet, previews each message, sends through Gmail, and writes `SENT` or `NOT_SENT` back on that sheet. Phase 1 waits for an explicit go-ahead.
