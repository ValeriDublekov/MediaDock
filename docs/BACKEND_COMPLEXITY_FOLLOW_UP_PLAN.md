# Backend Complexity Follow-up Plan

Date: 2026-09-04

## Purpose

This document records the concrete residual issues addressed after completing `BACKEND_COMPLEXITY_REDUCTION_PLAN.md` without reopening the completed refactoring or starting a .NET migration.

The staged/worktree reconciliation described in STEP 6 is complete; the original plan retains its implementation evidence, measurements, Windows-safe emulator command, and final decision.

## Verified Baseline

- Strict Pyright gate: 0 errors.
- Fast backend suite: 302 tests passed, 18 emulator-dependent tests skipped.
- Shared TypeScript Firestore contracts: 5 tests passed.
- Frontend suite: 74 tests passed.
- Firestore Rules suite: 32 tests passed.
- Production frontend build passed.
- Shared Firestore fixtures, strict Pyright configuration, and split CI lanes already exist. They must not be reimplemented.
- Backend emulator integration is blocked locally on Windows because `get_firestore_client()` invokes external `openssl` to generate a dummy service-account key.
- A direct `google.cloud.firestore.Client` using `AnonymousCredentials` was verified against the running emulator and completed a document read successfully.
- `rss_ingestion.py` is 853 lines. It owns both feed-level orchestration and entry-level decision/persistence behavior.

## Target State

The follow-up's completion criteria were:

1. Firestore emulator tests run on Windows without OpenSSL, ADC, or a service-account file.
2. Production Firestore initialization remains unchanged and continues to use Firebase Admin credentials.
3. Feed-level orchestration and entry-level decision processing have separate owning modules and focused tests.
4. `rss_ingestion.py` is normally below 400 lines and no replacement test or production monolith is introduced.
5. Strict Pyright covers every new extracted module.
6. The original plan truthfully records Steps 13-16 as complete, preserves the verified measurements, and no longer tells a new session to restart at STEP 1.

## Mandatory Execution Rules

1. Execute exactly one numbered step per worker/session.
2. Read the current staged and unstaged diff before editing any file that is already modified.
3. Preserve current RSS ordering, matching, logging, retry, metrics, and persistence behavior.
4. Do not modify `legacy/`.
5. Do not add a dependency-injection framework, validation framework, or new persistence abstraction.
6. Do not contact live RSS, OMDb, Gemini, or production Firestore.
7. Emulator commands must use the explicit `demo-mediadock` project.
8. Add or identify a focused characterization test before extracting entry behavior.
9. Run only the validation command listed for the current step. A failed command may be repeated after repairing that step.
10. Do not repeat completed contract-fixture, Pyright, or CI-lane work.
11. Do not mark a step complete until its executable validation passes.
12. At completion report changed files, acceptance criteria, exact command/result, and any deviation.

## Checkpoint A: Portable Firestore Emulator Initialization

### STEP 1 - Replace the OpenSSL Emulator Credential Workaround

Status: complete

Change only the emulator branch of `get_firestore_client()` in `backend/src/movies_feed/firestore_repository.py`.

When `FIRESTORE_EMULATOR_HOST` is set:

- construct a Google Cloud Firestore client with `google.auth.credentials.AnonymousCredentials`;
- pass the explicit project ID and optional database ID;
- do not initialize Firebase Admin solely to obtain an emulator client;
- do not invoke subprocesses, OpenSSL, temporary key files, ADC, or service-account credentials.

When the emulator variable is absent, retain the existing Firebase Admin production path and credential behavior.

Add focused unit tests for both branches without contacting production:

- emulator branch uses anonymous credentials and the requested project/database;
- emulator branch performs no subprocess or certificate initialization;
- production branch still delegates to Firebase Admin initialization/client creation;
- `(default)`, `%28default%29`, and empty database IDs preserve current normalization.

Acceptance criteria:

- `get_firestore_client()` has no OpenSSL or temporary-key logic.
- Emulator setup requires only Python dependencies already present in `backend/requirements.lock`.
- Production credential behavior is unchanged.
- The focused unit tests pass without Java or a running emulator.

Validation:

```powershell
python -m unittest backend.tests.test_unit_firestore_client -v
```

### STEP 2 - Prove Emulator Portability and Repository Behavior

Status: complete

Run the existing backend Firestore integration suite on the explicit demo emulator. Repair only defects caused by the client initialization change. Do not change repository semantics or weaken integration assertions.

Update `docs/ai/TESTING.md` only if the canonical command or environment prerequisites are inaccurate. The command must work on Windows without OpenSSL.

Acceptance criteria:

- Both Firestore integration test classes initialize successfully on Windows.
- Proposal application transaction/concurrency tests run rather than skip.
- No test can silently connect to production.
- No private key file is created.

Validation:

```powershell
npx firebase emulators:exec --project demo-mediadock "python -m unittest discover -s backend/tests -p test_firestore*.py -v"
```

Checkpoint A gate: STEP 2 validation is the gate.

## Checkpoint B: Isolate RSS Entry Decisions

### STEP 3 - Add Direct Entry-Processing Characterization Tests

Status: complete

Create `backend/tests/test_rss_entry_processor.py` using the existing scanner test support, fake repositories, `ScanWriteBuffer`, and `RssSnapshotCollector`.

Characterize the current entry-level behavior before moving it from `RssIngestionService`. Cover at minimum:

- ignored-by-date and empty-title exits;
- parser failure and low-confidence parsing;
- parse-only logging without metadata or persistence;
- confirmed-not-found, quota-exhausted, and transport-error outcomes;
- rejected media/year/filter match;
- accepted existing title and accepted new title;
- manual mapping lookup/consumption;
- snapshot candidate recording for accepted movie and series entries;
- dry-run counters with no staged catalog writes.

Reuse existing builders and result factories. Move an existing test instead of duplicating it when the test is purely entry-level. Do not change production code in this step.

Acceptance criteria:

- Tests exercise entry behavior directly, not through `ScannerService.run()`.
- No helper is imported from another `test_*.py` module.
- Existing RSS integration tests retain feed-level and multi-entry behavior.
- No live external service is used.

Validation:

```powershell
python -m unittest backend.tests.test_rss_entry_processor backend.tests.test_rss_ingestion -v
```

### STEP 4 - Extract `RssEntryProcessor`

Status: complete

Create `backend/src/movies_feed/rss_entry_processor.py` and move entry-level behavior from `RssIngestionService` into `RssEntryProcessor`.

The processor should own:

- source context creation for one entry;
- parse-result acceptance and parse-only handling;
- manual mapping selection;
- metadata resolution outcome handling;
- match evaluation and rejection logging;
- accepted `Title`/`Occurrence` construction and staging;
- snapshot candidate recording;
- entry-level counters and errors.

Keep `RssIngestionService` responsible for:

- feed definitions;
- fetch and feed validation;
- date cutoff calculation;
- parsing/prefetch preparation across feed entries;
- per-feed exception isolation;
- buffer flush boundaries;
- RSS phase timing and aggregate result.

Avoid one new 400-line method. Split the current decision path into named private operations such as parse rejection, metadata failure, match rejection, and accepted persistence. Keep outcome names and parse-log fields unchanged.

Acceptance criteria:

- `RssIngestionService` delegates individual entry decisions to `RssEntryProcessor`.
- `rss_ingestion.py` is normally below 400 lines.
- Entry processing can be constructed and tested without `ScannerService` or feed fetching.
- Feed-level failure isolation and metadata prefetch remain in `RssIngestionService`.
- Current parse logs, metrics, title IDs, occurrence IDs, and snapshot order are unchanged.
- No callback bundle recreates the old scanner coupling.

Validation:

```powershell
python -m unittest backend.tests.test_rss_entry_processor backend.tests.test_rss_ingestion backend.tests.test_scan_persistence backend.tests.test_rss_snapshot -v
```

### STEP 5 - Add the New Boundary to Strict Type Checking

Status: complete

Add `backend/src/movies_feed/rss_entry_processor.py` to `pyrightconfig.json`. Resolve strict errors at the new module boundary without broad ignores or weakening global settings.

Do not expand strict mode across the entire legacy backend in this step. Record additional candidate modules separately rather than turning this into a typing migration.

Acceptance criteria:

- `rss_entry_processor.py` and `rss_ingestion.py` pass strict Pyright.
- No broad `# type: ignore` or `report*=false` suppression is added.
- Firebase SDK typing remains isolated from RSS domain code.

Validation:

```powershell
npx pyright
```

Checkpoint B gate:

```powershell
python -m unittest backend.tests.test_rss_entry_processor backend.tests.test_rss_ingestion backend.tests.test_scan_orchestration backend.tests.test_scan_persistence backend.tests.test_rss_snapshot -v
```

## Checkpoint C: Reconcile Documentation and Close the Work

### STEP 6 - Reconcile the Original Plan Without Losing History

Status: complete

As part of STEP 6, the staged and worktree versions of `docs/BACKEND_COMPLEXITY_REDUCTION_PLAN.md` were inspected:

```powershell
git diff -- docs/BACKEND_COMPLEXITY_REDUCTION_PLAN.md
git diff --cached -- docs/BACKEND_COMPLEXITY_REDUCTION_PLAN.md
```

The document was reconciled from implementation evidence, not from whichever index/worktree copy was newer:

- Steps 13, 14, 15, and 16 were marked complete;
- the representative measurements and Python/.NET decision already present in the staged version were preserved;
- the Windows-safe emulator command syntax proven by Checkpoint A was retained;
- the stale STEP 1 session prompt was replaced with a completion note;
- a short link to this follow-up plan and its outcome was retained;
- unrelated staged and unstaged edits were preserved.

Also mark completed steps in this follow-up plan only after their validations have passed.

Acceptance criteria:

- Plan statuses agree with files, tests, CI, and completed measurements.
- No prompt instructs an agent to repeat STEP 1 of the completed plan.
- Staged historical measurements remain present.
- The emulator command matches the command that passed on Windows.
- `git diff` shows no accidental loss of unrelated documentation content.

Validation: documentation/evidence review only; do not run Markdown or whitespace validation.

### STEP 7 - Run the Final Regression Gate and Record the Decision

Status: complete

The final-gate commands were run once in order:

```powershell
npx pyright
python -m unittest discover -s backend/tests -p "test_*.py" -v
npx firebase emulators:exec --project demo-mediadock "python -m unittest discover -s backend/tests -p test_firestore*.py -v"
npx tsc --noEmit
npx vitest run src/test
npx firebase emulators:exec --project demo-mediadock "npx vitest run firebase/tests/rules.test.ts"
npm run build
```

Final counts and warnings are recorded below. Unrelated failures were not fixed as part of this plan.

Final gate result (2026-09-04):

1. `npx pyright`: PASS, 0 errors, 0 warnings, 0 informations.
2. `python -m unittest discover -s backend/tests -p "test_*.py" -v`: PASS, 320 tests, 18 skipped, no warnings.
3. Firestore emulator backend tests: PASS, 28 tests. Warnings: positional-argument `where` filter warnings at `google/cloud/firestore_v1/base_collection.py:317` and `backend/src/movies_feed/firestore_repository.py:594`.
4. `npx tsc --noEmit`: PASS, no output or warnings.
5. `npx vitest run src/test`: PASS, 11 files and 74 tests, no warnings.
6. Firestore rules emulator tests: PASS, 1 file and 32 tests. Warning: Node `ExperimentalWarning` because `localStorage` was used without `--localstorage-file`.
7. `npm run build`: PASS, 1,713 modules transformed. Warning: the generated JavaScript chunk is 966.93 kB after minification, above the 500 kB threshold.

Decision: Stop backend structural refactoring. All seven gates pass, and a typical RSS entry decision now belongs to `rss_entry_processor.py` plus its focused tests. Keep Python; no .NET migration is authorized solely from module line counts. Treat frontend chunking as a separate performance task.

Decision rule:

- Stop backend structural refactoring if all gates pass and a typical RSS entry decision now belongs to `rss_entry_processor.py` plus its focused tests.
- Keep Python unless three subsequent representative changes still require broad cross-module context or repeatedly expose runtime contract errors that strict typing would catch in .NET.
- Treat frontend bundle chunking as a separate performance task, not a blocker for this backend plan.

Acceptance criteria:

- All seven commands pass, or one concrete external blocker is recorded.
- The final document explicitly says whether structural refactoring should stop.
- No .NET migration is authorized solely from module line counts.

## Non-Goals

- Rewriting any backend component in .NET.
- Changing feed ordering, match policy, proposal policy, or Firestore schema.
- Reworking completed contract fixtures or CI lane separation.
- Expanding strict Pyright to the entire backend.
- Replacing Firebase Admin in production.
- Refactoring unrelated frontend components or addressing the Vite bundle warning.
- Reducing line counts through generic helpers, callback bundles, or hidden control flow.

