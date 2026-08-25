# Implementation Status

## Current Milestone

MVP wiring is present; production hardening is not complete.

## Completed

- M0: Sanitized legacy implementation, safe configuration.
- Backend: Scaffolded installable Python backend with title parser unit tests.
- P09A/B: Scaffolded Vite React frontend with Firebase auth and repository boundaries.
- P10: Implemented newest-first catalog querying, custom pagination, and UI.
- P12-P14: Pull-request CI, daily scanner workflow, and GitHub Pages deployment are present; workflow security and failure semantics still require hardening.
- P15: Integration and documentation audit identified open backend, workflow, authorization, and client-secret risks.
- AI matcher: Gemini extraction/validation exists with inline prompts and a current default of `gemini-3.1-flash-lite`; see [`GEMINI_MODELS.md`](../GEMINI_MODELS.md).

## Next Prompt

Run Prompt 0A in `docs/BACKEND_REFACTORING_PROMPTS.md`, then 0B and 0C.

## Blockers

- Firebase project identifiers and an authorized user account must be configured for production.
- The backend suite is not currently green in the reviewed environment: `test_firestore_repository` cannot import `google.cloud.firestore`.
- Workflow input validation, scanner exit codes, browser-secret removal, role enforcement, and bounded RSS fetching are open before production launch.


## Residual Risks

- The OMDb rate limit can halt scanner execution for the day. Cache reuse and partial-run status must be monitored.
- Allowlist addition requires a manual write to the Firestore database using Firebase Console until an admin control plane exists.
- The current `AiMatcher` payload needs compatibility review before changing the model to Gemini 3.6/3.7.
- Unpaginated local filtering currently handles all pages loaded into memory, which may become slow if thousands of entries are retained locally.

## Update Rules

- Keep only current facts, blockers, and one next prompt.
- Replace completed-step detail with milestone summaries.
- Do not duplicate Git history, test output, or architecture decisions.
- Keep this file under 100 lines.


