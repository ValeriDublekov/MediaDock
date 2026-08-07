# Testing Commands

## Status

Only the legacy parser test command exists today. Commands for target modules are
added here only after their scaffolds have been created and the commands verified.

## Current Canonical Check

From repository root:

```powershell
python -m unittest discover -s backend/tests -v
npx firebase emulators:exec "npx vitest run firebase/tests/rules.test.ts"
npx vitest run src/test/auth.test.tsx
npx vitest run src/test/catalogRepository.test.ts
```

This validates the RuTracker title parser in backend/ and the Firestore security rules via the emulator suite.

## Planned Test Layers

| Layer | Purpose | Network policy |
| --- | --- | --- |
| Backend unit | Parser, normalization, filtering, orchestration | No live network |
| Backend adapter | OMDb response handling through mocked transport | No live network |
| Repository integration | Firestore persistence and idempotency | Emulator only |
| Rules | Authentication and operation permission matrix | Emulator only |
| Frontend unit/component | Repositories, auth states, filters, pagination | SDK boundary mocked |
| Frontend build | Type safety and production asset generation | No live backend |
| Deployment smoke | Auth, catalog read, assets, routing | Deployed services |

## Command Ownership

- This file is the canonical compact command index used by coding agents and CI.
- `LOCAL_DEVELOPMENT.md` explains setup and human workflow, then links here.
- `DEPLOYMENT.md` owns deployed smoke checks and operational verification.
- Add a command only after it succeeds in the actual repository.
- Keep commands identical between this file and workflows.

## Safety

- Unit tests must not read real `.env` or production credentials.
- Emulator tests must use an explicit demo/local project ID.
- Test fixtures must contain synthetic or already-public feed samples only.
- Never snapshot service-account data, API keys, or private catalog records.
