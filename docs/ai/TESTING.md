# Testing Commands

## Status

These are the canonical checks used by PR CI and the Checkpoint F release gate.
A release is blocked unless every required automated and staging check passes.

## Focused Commands

Run these commands from the repository root after installing the reviewed
dependencies:

```powershell
python -m pip install --requirement backend/requirements.lock
python -m pip install --no-deps --editable ./backend
npm ci
```

Each CI lane uses the corresponding focused command below. The backend fast
lane does not start Java or an emulator. Backend files beginning with
`test_firestore` are reserved for Firestore emulator integration tests; the
emulator-free codec and contract modules use the `test_unit_` prefix. The
fast discovery command includes every `test_*.py` module, while the explicit
Firestore command selects only the emulator convention.

| Category | Command |
| --- | --- |
| Backend static typecheck | `npx pyright` |
| Backend fast unit tests | `python -m unittest discover -s backend/tests -p "test_*.py" -v` |
| Backend Firestore emulator tests | `npx firebase emulators:exec --project demo-mediadock "python -m unittest discover -s backend/tests -p test_firestore*.py -v"` |
| Frontend typecheck | `npx tsc --noEmit` |
| Frontend unit tests | `npx vitest run src/test` |
| Firestore rules emulator tests | `npx firebase emulators:exec --project demo-mediadock "npx vitest run firebase/tests/rules.test.ts"` |
| Frontend build | `npm run build` |

The emulator commands always use the explicit `demo-mediadock` project and
`firebase emulators:exec`, so they cannot silently fall back to production.
The lock file is the reviewed dependency set; install the editable package
with `--no-deps` after installing the lock so dependency resolution cannot
silently drift in CI.

## Scanner Process Contract

The scanner returns exit code `0` only for `succeeded`, `2` for `partial` or
retryable completion, and `1` for `failed` or configuration errors. Parse-only
is a run-level RSS-only mode: `--parse-only --mode all` is rejected before
scanner construction, and parse-only performs no OMDb, Gemini, Firestore, or
parse-log writes. RSS fetching is still required to obtain the feed entries.

The CLI preflight checks mode-specific Firebase, OMDb, and Gemini configuration
by presence only. It reports secret names and never prints their values.

`recheck-existing` delegates cluster auditing and proposal production to
`ExistingTitleAuditService`. Tests cover schema-v2 proposals, deterministic v3
IDs, `review_only` versus `repair`, and 200-occurrence chunking. Proposal
application tests must prove that legacy/schema-v1 and `review_only` proposals
are ineligible, dry-run performs no writes or lease acquisition, a live attempt
holds the per-source lease, and the catalog move plus final `applied` status
commit in one Firestore transaction or not at all.

`--mode all` covers RSS, existing-title audit, and parse-log reprocessing. It
must not enter proposal application. There is no supported test or production
path for bulk or automatic proposal application; application tests select one
explicit proposal ID.

When workflow files change, also run a YAML/workflow linter such as
`actionlint` when available. If no linter is installed, run the repository's
deterministic workflow static checks and record that limitation; do not claim
workflow validation from `git diff` alone.

## Planned Test Layers

| Layer | Purpose | Network policy |
| --- | --- | --- |
| Backend unit | Parser, normalization, filtering, orchestration | No live network |
| Backend adapter | Bounded RSS and OMDb response handling through mocked transports | No live network |
| Repository integration | Firestore persistence and idempotency | Emulator only |
| Rules | Authentication and operation permission matrix | Emulator only |
| Workflow/security static checks | Input injection, secret exposure, exit codes, and action configuration | No production services |
| Frontend unit/component | Repositories, auth states, filters, pagination | SDK boundary mocked |
| Frontend build | Type safety and production asset generation | No live backend |
| Deployment smoke | Auth, catalog read, assets, routing | Deployed services |

## Command Ownership

- This file is the canonical compact command index used by coding agents and CI.
- `LOCAL_DEVELOPMENT.md` explains setup and human workflow, then links here.
- `DEPLOYMENT.md` owns deployed smoke checks and operational verification.
- Add a command only after it succeeds in the actual repository.
- Keep commands identical between this file and workflows; document any
	environment-only difference explicitly.
- Use [`GEMINI_MODELS.md`](../GEMINI_MODELS.md) when testing model configuration;
	a catalog entry is not a substitute for a runtime capability check.

## Safety

- Unit tests must not read real `.env` or production credentials.
- Emulator tests must use an explicit demo/local project ID.
- Test fixtures must contain synthetic or already-public feed samples only.
- RSS tests must inject a mocked transport or use the explicit fixture-file
	path; no test may pass a local path or fixture text as a configured network URL
	to the production `FeedFetcher`.
- Never snapshot service-account data, API keys, or private catalog records.
- Never test by calling live RSS, OMDb, Gemini, or production Firestore.
- Existing-title audit tests must assert stable schema-v2/v3 proposals per
	source/raw-title cluster and splitting at 200 occurrences.
- Application tests must assert that legacy and `review_only` proposals cannot
	acquire a lease or mutate catalog data.
- Firestore application tests must assert lease-owner revalidation and atomic
	movement of only the named occurrences with the final proposal status.
- `mode=all` and proposal dry-run tests must assert zero proposal-driven catalog
	mutation.
