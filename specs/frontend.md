# Frontend

Vite, React, TypeScript, Tailwind, React Router, TanStack Query.

## Navigation

```text
Dashboard
Sheet
Contacts
Profiles
Resumes
Email Templates
Settings
```

## Screens

**Dashboard.** Six totals from the latest sync: contacts, sent, pending (pending + queued + sending), failed, skipped, needs review. Recent runs with sent, failed, and still not sent. Banners when dry run is on, Google is disconnected, the sheet is not connected, or Gmail must be reconnected.

**Sheet.** The connected spreadsheet: URL, tab, last sync, counts of `SENT` and `NOT_SENT`, and the review flow.

```text
Paste sheet link (once)
  → Sync
  → Validation summary
  → Review table
  → Row preview
  → Confirm
  → Start
  → Progress
```

The review table columns are recipient, company, original role, detected profile, resume, template, and status. Profile, resume, and template are selects. Needs-review rows are visually separated and block confirm until they are fixed or excluded.

Opening a row shows To, Subject, Body, attachment file name, and template warnings.

While a run is `RUNNING` or `PAUSED`, the screen polls campaign detail every few seconds. Progress shows each row’s status and whether the sheet cell has been written.

**Contacts.** Filters from the API, plus a detail view:

```text
Rahul Sharma
rahul@example.com

3 Oct 2026 · Software Engineer · software_engineer.pdf · SENT
14 Sep 2026 · Full Stack Engineer · fullstack_resume.pdf · SENT
```

**Profiles.** Name, keywords, resume, template, priority, active.

**Resumes.** Upload PDF, name, assigned profiles, replace file, download, active, default.

**Templates.** Name, assigned profiles, subject, body, live preview with sample values, duplicate, active, default.

**Settings.** The three send limits, match threshold, max attempts, Google connect and disconnect, the sheet URL and tab, and a read-only `DRY_RUN` indicator.

## Behavior

Visual style is a quiet layout: readable type, clear status color, no decorative motion. A failed action shows the API `detail` string next to that action.

| UI | API |
| --- | --- |
| Collects edits and asks for confirmation | Decides status transitions |
| Renders the message returned by the preview endpoint | Renders templates |
| Polls campaign detail while a run is active | Claims, sends, and writes the sheet row |
| Never calls Google | Owns OAuth, the Gmail client, and the Sheets client |

Header mapping is a step on the Sheet screen, shown only when sync returns `header_mapping_required`. The operator maps email and role, then sync runs again.
