# Deployment

This is the target deployment runbook for Cloud Firestore, Firebase Authentication,
the daily GitHub Actions scanner, and the React GitHub Pages site. The MVP
workflows and prerequisite hardening stages 0A-0C are implemented; production
launch remains gated on the later repair stages in
`docs/BACKEND_REFACTORING_PROMPTS.md`.

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
- A rotated OMDb API key; a Gemini API key is also required for AI modes.
- An explicitly approved Gemini model ID with the required API capability; see [`docs/GEMINI_MODELS.md`](docs/GEMINI_MODELS.md).
- Configured RSS feeds must use the bounded fetcher's code-owned HTTPS host
  allowlist; local verification uses the explicit `--feed-file` option.
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
`allowlist/{uid}` record with matching email, `enabled: true`, and an explicitly
chosen role (`reader` or `admin`). Do not key the document by mutable display
name. Readers can view scanner settings and mappings but only admins can write
them; the deployed rules and emulator tests enforce this boundary.

### 4. Deploy rules and indexes

Use only the current Firebase CLI deployment command documented for this
repository. Test against the Firebase Emulator before production deployment.
Review the rules diff and selected Firebase project immediately before running
the deploy command; never rely on an implicit project from a developer shell.

Catalog client writes must remain denied. A future owner-scoped feature requires a
specific schema and rules tests before deployment.

## GitHub Configuration

The exact names must match the workflows and `.env.example`.

### Secrets

| Purpose | Expected secret | Format / Usage |
| --- | --- | --- |
| OMDb requests | `OMDB_API_KEY` | String OMDb API key |
| Gemini AI modes | `GEMINI_API_KEY` | String Gemini API key; required for `recheck-existing`, `reparse-unfound`, and `all` |
| Firebase Admin scanner access | `FIREBASE_SERVICE_ACCOUNT` | Base64-encoded Firebase Admin service account JSON (`base64 -w 0 <key.json>`) |

The scanner workflow (`.github/workflows/scanner.yml`) decodes `FIREBASE_SERVICE_ACCOUNT` into a temporary environment file outside the checked out repository and sets `GOOGLE_APPLICATION_CREDENTIALS` for the step. Credentials are never committed, logged, or uploaded as build artifacts.

The scanner validates dispatch inputs in the shell without interpolating them
into executable source. It exits with `0` only for a succeeded run, `2` for a
partial/retryable run, and `1` for a failed run or configuration error. The CLI
preflight checks required credential presence by mode and reports only secret
names. Parse-only is accepted only for RSS mode and performs no OMDb, Gemini,
Firestore, or parse-log write operation.

### Variables for Pages build environment

Store public Firebase web configuration using the `VITE_*` names expected by the
frontend as **Repository Variables** (not Secrets). Do not add `OMDB_API_KEY`, private keys, or Admin project credentials to
the Pages build job.

The Pages build may set public `VITE_GITHUB_OWNER`, `VITE_GITHUB_REPO`, and
`VITE_GITHUB_WORKFLOW` values so the browser can link to GitHub's protected
Actions page. Never add a GitHub PAT or OMDb key to Vite variables, localStorage,
or the Pages job.

`GEMINI_MODEL` is a non-secret repository variable only if model selection is
intentionally controlled there; otherwise keep it in the scanner environment.
Validate it against [`docs/GEMINI_MODELS.md`](docs/GEMINI_MODELS.md) and the
runtime `models.list` capability response. Never expose it together with a
private API key in the frontend bundle.

### Repository settings

1. Enable GitHub Actions required by the committed workflows.
2. Configure Pages source as GitHub Actions.
3. Protect the deployment environment if desired.
4. Keep workflow permissions at their documented minimum (`contents: read` for
   the scanner; Pages deploy additionally needs `pages: write` and `id-token: write`).
5. Restrict who can dispatch the scanner and review changes to workflow files,
	because manual dispatch can access production secrets.

## First Scanner Deployment

Do not wait for the first cron execution.

1. Confirm all canonical checks from `docs/ai/TESTING.md` pass.
2. Confirm production Firestore rules/indexes are deployed.
3. Configure `OMDB_API_KEY` and `FIREBASE_SERVICE_ACCOUNT` in GitHub Repository Secrets.
4. Configure `GEMINI_API_KEY` before using an AI mode, and configure/approve `GEMINI_MODEL` if overriding the default.
5. Trigger `.github/workflows/scanner.yml` manually via `workflow_dispatch` with `dry_run: true` and a bounded input set.
6. Inspect sanitized run counters and confirm no production Firestore write occurred by comparing the datastore before and after. Do not use `titles_created: 0` or `occurrences_created: 0` as the sole proof: the current dry-run counters are simulated and may not reflect existing records.
7. Trigger `workflow_dispatch` without dry-run mode (`dry_run: false`) only after the job's exit-code and partial-run behavior is verified.
8. `mode=all` is non-destructive: it never applies proposals. Production proposal application is temporarily disabled during remediation.
9. In Firebase Console, verify one `scanRuns/{run_id}` record, title documents under `titles/{id}`, occurrence documents under `titles/{id}/occurrences/{occ_id}`, and cached OMDb entries in `omdbCache`.
10. Rerun `workflow_dispatch` once more and verify no duplicate title or occurrence documents are created due to deterministic ID merging.

If OMDb reports a daily limit, stop repeated manual runs and verify cache behavior.

## GitHub Pages Deployment

The committed Pages workflow must:

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
- Scanner failures must produce a non-success process exit code and a bounded,
  sanitized scan-run summary; do not rely on log text alone.
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
bulk migration or production destructive execution (e.g., applying audit proposals). The legacy JSON importer is not a production backup mechanism.

#### Concurrency and Limits

When executing bulk catalog operations (such as applying audit proposals):
- Application operations use a compare-and-set lease on the `AuditProposal` to transition to `applying`.
- Concurrent proposals modifying occurrences for the same source title are prevented by lease checks.
- A stale lease (crashed worker) will be recovered to `failed` on the next attempt; the proposal must be reviewed and restarted rather than blindly applying old evidence.
- Writes (occurrences, titles, logs) perform individual deterministic upserts and deletes. They do NOT execute in a single global batch. If an operation exceeds Firestore batch limits or crashes mid-execution, the failure is localized. The source Title and source Occurrences may be partially moved.
- The operator must ensure a backup/export checkpoint exists before running destructive repairs. In the event of an unrecoverable failure during a multi-write application, the documented operator recovery action is to restore from the latest export or to manually reconstruct the remaining occurrences using the `failed` proposal's planned target.

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
- The backend dependency environment is reproducible and the complete canonical
  suite is green.
- Rules/indexes match `docs/ai/DATA_CONTRACTS.md`.
- Required secrets/variables exist under the exact workflow names.
- The selected Gemini model is active and supports the request contract used by
  `AiMatcher`; AI mode preflight is tested without printing secrets.
- Workflow inputs are validated and cannot inject shell syntax.
- Reader/admin authorization and browser-secret checks pass.
- Manual scanner idempotency check passes.
- Pages smoke checklist passes for denied and allowlisted users.
- No real secret, local catalog data, or service-account file is tracked/artifacted.
- `README.md` and this runbook link to current canonical commands.
