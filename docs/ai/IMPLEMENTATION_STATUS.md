# Implementation Status

## Current Milestone

Frontend Repository Boundary & Catalog Data Contracts.

## Completed

- M0: Sanitized legacy implementation, safe configuration, root placeholders, and seed documentation reconciled.
- Backend: Scaffolded installable Python backend in `backend/` with `src` layout and title parser unit tests.
- P09A: Scaffolded Vite React TypeScript frontend with Firebase initialization, Google Sign-In, and focused auth tests mocked at the adapter boundary.
- P09B: Defined typed catalog repository interfaces, Firestore read adapter (`FirestoreCatalogAdapter`), and explicit `UserDataWriteRepository` extension point; tested repository boundary using Vitest mocks.
- P10: Implemented newest-first catalog querying, custom `useCatalog` pagination hook with duplicate suppression, retry state handling, `CatalogView` UI, and comprehensive Vitest tests.
- P12: Added pull-request CI workflow in `.github/workflows/ci.yml` executing backend tests, frontend typecheck, Vitest unit tests, Firestore Emulator security rules tests, and production build without requiring production credentials.
- P13: Added daily scanner workflow `.github/workflows/scanner.yml` with cron schedule, manual `workflow_dispatch` with `dry_run` input, concurrency controls, least permissions, timeout limits, base64 secret decoding, and documented deployment procedures in `DEPLOYMENT.md`.
- P14: Added GitHub Pages deployment workflow `.github/workflows/pages.yml` with configured Vite base path, correct variables mapping, and Pages upload artifact actions.

## Current Repository Reality

- Legacy source is isolated under `legacy/`.
- Installable Python backend exists under `backend/`.
- Frontend exists at root using Vite 6, React 19, TypeScript 5.8, and Tailwind 4.
- Authentication components (`AuthGate`, `AuthProvider`) are implemented and tested.
- Catalog data layer uses repository interface with cursor pagination, duplicate suppression, loading, error, empty, retry, and end-of-results state handling.
- Frontend components do not import Firestore query APIs directly.
- Pull-request CI configured in GitHub Actions for backend/frontend testing, typechecking, and build validation.
- Daily scanner GitHub Actions workflow configured for scheduled and dry-run execution.
- GitHub Pages workflow configured for `main` branch deployment.

## Next Prompt

MVP Complete. Follow DEPLOYMENT.md to launch the system.

## Blockers

- Firebase project identifiers and authorized user account must be configured for production.

## Residual Risks

- The OMDb rate limit will halt scanner execution for the day. Cache reuse must be monitored.
- Allowlist addition requires a manual write to the Firestore database using Firebase Console.
- Unpaginated local filtering currently handles all pages loaded into memory, which may become slow if thousands of entries are retained locally.

## Update Rules

- Keep only current facts, blockers, and one next prompt.
- Replace completed-step detail with milestone summaries.
- Do not duplicate Git history, test output, or architecture decisions.
- Keep this file under 100 lines.


