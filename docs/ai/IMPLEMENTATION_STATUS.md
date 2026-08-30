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
- Prompt 0A: Scanner workflow inputs, mode-aware CLI preflight, process exit codes, parse-only isolation, explicit emulator project IDs, and locked backend CI dependencies are implemented.
- Prompt 0B: Reader/admin rules, validated scanner settings and manual mappings, authenticated `createdBy`/`updatedBy`, and removal of browser scanner credentials are implemented.
- Prompt 0C: Bounded HTTPS RSS fetching, public DNS and redirect validation, response/entry limits, bozo rejection, and explicit `--feed-file` fixture input are implemented.
- Prompt 1: Existing-title audit is fail-closed and review-only; incomplete AI/OMDb evidence cannot delete or migrate catalog records, and fake repositories are defensive-copy safe for dry-run.
- Prompt 2: Shared typed media/year policy is used by RSS, reparse, and audit candidate checks; source type is stored separately from content kind, and series broadcast ranges preserve later-season semantics.
- Prompt 3: `OmdbResolver` provides typed outcomes, versioned type/semantics-aware cache entries, actual HTTP-attempt accounting, a run-wide quota budget across all modes, and Gemini model capability preflight without model-ID remapping.
- Prompt 4A: Optional typed `SourceContext` and source/audit event kinds round-trip without inventing provenance for legacy documents.
- Prompt 4B: Source-aware v2 occurrence/source-log IDs, isolated audit IDs, canonical fallback title IDs, and explicit v1 natural coexistence are implemented.
- Prompt 4C: RSS and reparse writes retain stable source context, separate publication from observation time, and use matching single/bulk repository merge semantics with defensive copies.
- Prompt 5A: Parse logs have explicit retry lifecycle metadata, conservative legacy-state derivation, deterministic paginated retry selection, and retention that preserves old retryable work.
- Prompt 5B: Reparse traverses all retry pages, resolves retained manual mappings before Gemini, deduplicates by v2 source identity, preserves source provenance, updates the original log lifecycle, and consumes mappings only after durable writes.
- Prompt 6A: Shared validation in `ai_validator.py` strictly validates Gemini responses with bounded payloads, exact types/ranges (`movie`/`series`), and fail-closed confidence thresholds (0.70 extraction/candidate, 0.80 audit).
- Prompt 6B: Injected clock/sleep dependencies, deterministic retry policy (429/5xx/timeout), 403 cooldowns, header-only key transport (`x-goog-api-key`), bounded responses, and secret-safe structured logging in `AiMatcher`.
- Prompt 7A: Defined idempotent `AuditProposal` storage contract, deterministic proposal IDs, status transition validation, evidence size limit (32 KiB), secret redaction, and Fake/Firestore repository parity.

## Next Prompt

Run Prompt 7B in `docs/BACKEND_REFACTORING_PROMPTS.md`.

## Blockers

- Firebase project identifiers and an authorized user account must be configured for production.
- Production launch still requires AI validation, proposal, and application stages.
- The Firestore rules emulator could not run in this local environment because Java is unavailable; CI installs Java 21 and runs the same rules test.


## Residual Risks

- The OMDb rate limit can halt scanner execution for the day. Cache reuse, actual-attempt counters, and partial-run status must be monitored.
- Allowlist addition requires a manual write to the Firestore database using Firebase Console until an admin control plane exists.
- The current `AiMatcher` payload needs compatibility review before changing the model to Gemini 3.6/3.7; full AI hardening remains Prompt 6.
- Unpaginated local filtering currently handles all pages loaded into memory, which may become slow if thousands of entries are retained locally.
- Legacy retry logs without enough retained source context remain retryable but are skipped by automated reparse until an operator supplies recoverable provenance.

## Update Rules

- Keep only current facts, blockers, and one next prompt.
- Replace completed-step detail with milestone summaries.
- Do not duplicate Git history, test output, or architecture decisions.
- Keep this file under 100 lines.


