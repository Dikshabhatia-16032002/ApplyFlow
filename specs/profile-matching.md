# Profile matching and preview

## Matcher

`KeywordProfileMatcher` implements `ProfileMatcher`.

```text
match(role, job_description) -> MatchResult
```

`job_description` is accepted and ignored. Matching uses the role cell only.

Normalization: lowercase, strip punctuation to spaces, collapse whitespace. Keywords are stored in that form. The profile name is inserted as a keyword automatically.

### Scoring

| Situation | Confidence |
| --- | --- |
| A keyword equals the whole role | 1.000 |
| A keyword is a whole-phrase substring of the role | 0.900, plus `min(keyword_length, 40) / 1000` |
| No keyword hits | no score |

The length bonus orders specificity. “Machine learning engineer” beats a shorter keyword. The bonus cannot lift a weak hit over the review threshold by itself.

### Selection

1. Consider only active profiles.
2. Take the best confidence per profile.
3. If the best confidence is below `match_confidence_threshold` (default 0.800), the result is `NEEDS_REVIEW`.
4. If two profiles share the best confidence and the same priority, the result is `NEEDS_REVIEW` with reason `ambiguous`.
5. If priorities differ, the higher `profiles.priority` wins and `method` stays `keyword`.
6. Otherwise assign that profile.

“Engineer” alone is not a keyword. A bare title stays `NEEDS_REVIEW`.

### Resume and template

After a profile is chosen:

1. Resume = `profile.resume_id` if that resume is active, else the default active resume, else missing.
2. Template follows the same rule.
3. If resume or template is missing, status stays `NEEDS_REVIEW` even though a profile was found. The preview shows the profile and a blank resume or template.

Manual assignment sets `match_method = manual`, `match_confidence = 1`, and then runs the same resolution. Changing the profile re-resolves resume and template unless the operator has already overridden that field.

## Seed profiles

The operator can edit these after seed.

| Profile | Keywords |
| --- | --- |
| Software Engineer | software engineer, swe |
| Full Stack Engineer | full stack, fullstack, full-stack, mern |
| Frontend Engineer | frontend, front end, front-end, react, react developer, ui engineer |
| Backend Engineer | backend, back end, back-end, node, nodejs, django, api engineer |
| AI/ML Engineer | ai/ml, ai engineer, ml engineer, machine learning, machine learning engineer, deep learning |
| Applied AI Engineer | applied ai, genai, gen ai, generative ai, llm, llm engineer |
| Data Scientist | data scientist, data science |

Examples:

| Role cell | Result |
| --- | --- |
| GenAI Engineer | Applied AI Engineer, because it contains `genai` |
| Machine Learning Engineer | AI/ML Engineer |
| React Developer | Frontend Engineer |
| Engineer | `NEEDS_REVIEW` |

## Preview

The review table:

```text
Recipient | Company | Original role | Detected profile | Resume | Template | Status
```

Editable on a row: profile, resume, template, name, company, role, and “allow resend” when history already has a send for that address.

Exclude sets `SKIPPED` / `excluded_by_user` and writes `NOT_SENT` with that reason. Include is offered only when the row is valid and resolved.

Opening a row shows:

```text
TO
SUBJECT
BODY
ATTACHMENT filename
warnings: empty variables, unknown tokens
```

Confirm (`DRAFT → READY`) requires zero included rows in `NEEDS_REVIEW`. Skipped rows do not block confirm.

Start (`READY → RUNNING`) creates one `email_jobs` row per `PENDING` contact in a single transaction:

- status `QUEUED`
- `scheduled_at` staggered by `delay_between_emails_seconds` from now
- `dry_run` copied from the process environment
- contact status set to `QUEUED`

A second Start does not create a second job, because `campaign_contact_id` is unique.

`NEEDS_REVIEW` and `SKIPPED` rows are not queued.
