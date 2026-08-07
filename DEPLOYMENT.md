# Deployment

This is the target deployment runbook for Cloud Firestore, Firebase Authentication,
the daily GitHub Actions scanner, and the React GitHub Pages site. It becomes fully
executable as prompts P08 and P12-P14 are completed.

## Deployment Model

| Component | Platform | Credentials |
| --- | --- | --- |
| React static assets | GitHub Pages | Public `VITE_*` Firebase web config at build time |
| User authentication | Firebase Authentication | Google provider; no Admin key in browser |
| Catalog database | Cloud Firestore | Access controlled by deployed rules |
| Daily scanner | GitHub Actions | OMDb and Firebase Admin GitHub Secrets |

GitHub Pages cannot run the Python scanner.

## Prerequisites

- A Firebase project on an appropriate billing/free-tier plan for expected usage.
- A registered Firebase web app.
- Firestore database created in the selected region.
- Google Sign-In provider enabled.
- GitHub repository with Actions and Pages enabled.
- A rotated OMDb API key.
- At least one Google account selected for the access allowlist.

Record project names and regions outside source code where appropriate. Never put
real credential values in this document.

## Firebase Setup

### 1. Register the web app

Create a Firebase web app and map its public configuration to the `VITE_*` variable
names committed in `.env.example`. These values identify the project but do not
grant Admin access.

### 2. Configure Authentication

Enable Google as a sign-in provider. Add the GitHub Pages host to Firebase
Authentication Authorized Domains. For a project site, the host is typically
`<owner>.github.io`; the repository name remains part of the application path.

### 3. Create the first allowlist entry

After the user has signed in once and the UID is known, create the documented
`allowlist/{uid}` record with matching email, `enabled: true`, and `role: reader`.
Do not key the document by mutable display name.

### 4. Deploy rules and indexes

Use only the project command added and verified during P08. Test against the
Firebase Emulator before production deployment. Review the rules diff and selected
Firebase project immediately before running the deploy command.

Catalog client writes must remain denied. A future owner-scoped feature requires a
specific schema and rules tests before deployment.

## GitHub Configuration

The exact names must match workflows and `.env.example`. P13/P14 update this table
when workflows are implemented.

### Secrets

| Purpose | Expected secret |
| --- | --- |
| OMDb requests | `OMDB_API_KEY` |
| Firebase Admin scanner access | Name selected and documented by P13 |

Prefer credentials that are short-lived or narrowly scoped when the selected
Firebase/GitHub integration supports them. If a service-account JSON key is used,
store an encoded representation as one GitHub Secret and decode it only inside the
scanner job's temporary environment. Do not echo or upload it as an artifact.

### Variables or Pages build environment

Store public Firebase web configuration using the `VITE_*` names expected by the
frontend. Do not add `OMDB_API_KEY`, private keys, or Admin project credentials to
the Pages build job.

### Repository settings

1. Enable GitHub Actions required by the committed workflows.
2. Configure Pages source as GitHub Actions.
3. Protect the deployment environment if desired.
4. Keep workflow permissions at their documented minimum.

## First Scanner Deployment

Do not wait for the first cron execution.

1. Confirm backend CI and emulator integration tests pass.
2. Confirm production Firestore rules/indexes are deployed.
3. Configure secrets without printing them.
4. Run `workflow_dispatch` in dry-run mode if available.
5. Inspect sanitized counters and confirm no production write occurred.
6. Run one manual normal scan.
7. Verify one `scanRuns` record, title IDs, occurrence IDs, and cache timestamps.
8. Rerun once and confirm no duplicate title/occurrence documents are created.

If OMDb reports a daily limit, stop repeated manual runs and verify cache behavior.

## GitHub Pages Deployment

P14 owns the executable workflow. The deployment must:

- Build `frontend/` with the correct Vite base for `/<repository>/`.
- Include only public Firebase web variables.
- Upload the built output directory, not the repository or source root.
- Use official Pages artifact/deployment actions and least permissions.
- Use a routing strategy that survives direct refresh at the project path.

## Post-Deployment Verification

Open the deployed project URL in a private browser session and verify:

1. Static assets load without root-path 404 errors.
2. An anonymous user sees sign-in, not catalog data.
3. A non-allowlisted account is denied.
4. The allowlisted account can load the newest catalog page.
5. Load more returns older entries without duplicates.
6. Search/filter behavior clearly applies to loaded pages.
7. Torrent and IMDb links open safely in a new tab.
8. Refreshing the deployed URL does not show a Pages 404.
9. Browser bundles/network requests expose no OMDb or Admin credential.

Record pass/fail and deployment URL in the release/checkpoint, not in compact AI
context unless it changes a stable command or status.

## Scheduled Operation

- The scanner workflow supports both daily `schedule` and manual dispatch.
- GitHub cron uses UTC and may start later than the exact scheduled minute.
- Concurrency prevents overlapping scanner writes.
- A timeout prevents abandoned jobs.
- Failures retain sanitized logs and a bounded scan-run summary.
- Re-running a failed/partial workflow is safe because catalog IDs are deterministic.

Review Actions history periodically for disabled schedules, expired credentials,
OMDb limits, and sustained partial runs.

## Rollback and Recovery

### Frontend

Re-run the last known-good Pages workflow/ref after confirming its Firebase query
contract remains compatible. Do not roll back rules independently if that would
grant broader access or break the deployed client.

### Scanner

Disable the schedule or workflow while investigating repeated destructive failures.
Because writes are upserts, prefer fixing and rerunning over deleting catalog data.

### Rules

Keep known-good rules in Git. Deploy a reviewed prior version only after emulator
tests confirm it still matches current paths. Never temporarily allow public access.

### Firestore data

Use provider-supported backup/export appropriate to the selected plan before any
bulk migration. The legacy JSON importer is not a production backup mechanism.

## Secret Rotation

1. Create/obtain the replacement credential.
2. Update the GitHub Secret or local ignored credential store.
3. Manually run the smallest safe verification workflow.
4. Revoke the old credential.
5. Confirm logs/artifacts contain no credential material.

Rotate immediately after suspected exposure. Removing a value from Git does not
invalidate the credential.

## Release Gate

- Backend, rules, and frontend CI pass.
- Rules/indexes match `docs/ai/DATA_CONTRACTS.md`.
- Required secrets/variables exist under the exact workflow names.
- Manual scanner idempotency check passes.
- Pages smoke checklist passes for denied and allowlisted users.
- No real secret, local catalog data, or service-account file is tracked/artifacted.
- `README.md` and this runbook link to current canonical commands.
