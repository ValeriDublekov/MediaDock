# Testing Commands

## Status

These are the intended canonical checks used by PR CI. The repository baseline
must be green before a refactoring stage is considered complete; at the
2026-08-25 review, the backend suite still had a local Firestore dependency
import error, so the previous "verified" wording was premature.

## Current Canonical Check

From repository root:

```powershell
pip install -e ./backend
npx firebase emulators:exec --project demo-mediadock "python -m unittest discover -s backend/tests -v"
npx tsc --noEmit
npx vitest run src/test
npx firebase emulators:exec --project demo-mediadock "npx vitest run firebase/tests/rules.test.ts"
npm run build
```

This validates backend unit/integration suites, frontend TypeScript typing, component/repository unit tests, Firestore security rules via emulator, and frontend production compilation.

The local commands above use an explicit demo project. The current CI workflow
does not yet pass that project flag to its emulator commands; Prompt 0A makes
the workflow and this command contract identical.

When workflow files change, also run a YAML/workflow linter such as
`actionlint` when available. If no linter is installed, run the repository's
deterministic workflow static checks and record that limitation; do not claim
workflow validation from `git diff` alone.

## Planned Test Layers

| Layer | Purpose | Network policy |
| --- | --- | --- |
| Backend unit | Parser, normalization, filtering, orchestration | No live network |
| Backend adapter | OMDb response handling through mocked transport | No live network |
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
- Never snapshot service-account data, API keys, or private catalog records.
- Never test by calling live RSS, OMDb, Gemini, or production Firestore.
