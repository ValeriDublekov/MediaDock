# Testing Commands

## Status

These are the intended canonical checks used by PR CI. The repository baseline
must be green before a refactoring stage is considered complete; at the
2026-08-25 review, the backend suite still had a local Firestore dependency
import error, so the previous "verified" wording was premature.

## Current Canonical Check

From repository root:

```powershell
python -m pip install --requirement backend/requirements.lock
python -m pip install --no-deps --editable ./backend
npx firebase emulators:exec --project demo-mediadock "python -m unittest discover -s backend/tests -v"
npx tsc --noEmit
npx vitest run src/test
npx firebase emulators:exec --project demo-mediadock "npx vitest run firebase/tests/rules.test.ts"
npm run build
```

This validates backend unit/integration suites, frontend TypeScript typing, component/repository unit tests, Firestore security rules via emulator, and frontend production compilation.

The local commands above use an explicit demo project. The CI workflow passes
that project flag to its emulator commands, so the workflow and this command
contract are identical. The lock file is the reviewed dependency set; install
the editable package with `--no-deps` after installing the lock so dependency
resolution cannot silently drift in CI.

## Scanner Process Contract

The scanner returns exit code `0` only for `succeeded`, `2` for `partial` or
retryable completion, and `1` for `failed` or configuration errors. Parse-only
is a run-level RSS-only mode: `--parse-only --mode all` is rejected before
scanner construction, and parse-only performs no OMDb, Gemini, Firestore, or
parse-log writes. RSS fetching is still required to obtain the feed entries.

The CLI preflight checks mode-specific Firebase, OMDb, and Gemini configuration
by presence only. It reports secret names and never prints their values.

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
- Keep commands identical between this file and workflows once Prompt 0A is
	applied; until then, document any environment-only difference explicitly.
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
