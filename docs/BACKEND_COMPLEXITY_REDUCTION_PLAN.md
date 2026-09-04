# Backend Complexity Reduction Plan

Date: 2026-09-04

## Purpose

Reduce the time, context, and token cost required to change the MediaDock backend without rewriting it in .NET or changing product behavior.

This plan is separate from `docs/backend-refactoring-plan/`. That plan repairs proposal safety and correctness. This plan improves module boundaries, test ergonomics, static feedback, and the backend/frontend Firestore contract. Do not reopen completed proposal work unless a test in this plan exposes a regression.

## Current Evidence

- `backend/src/movies_feed/scanner.py` combines top-level phase orchestration, RSS fetching/parsing, entry decisions, mutable write buffers, parse logging, snapshot collection, and dependency construction.
- `ScannerService.__init__` accepts many repositories and services, so most scanner tests repeat broad setup even when they exercise one behavior.
- `backend/tests/test_scanner.py` is larger than the production scanner and mixes RSS ingestion, ordering, persistence, orchestration, retry, and compatibility behavior.
- `backend/tests/test_existing_title_audit.py` imports `MockOmdbClient` from `test_scanner.py`; test modules are therefore coupled to one another.
- Fake repositories live beside production interfaces in `repository.py`, increasing the amount of code that must be understood for either production or test changes.
- Firestore serialization is spread across model `to_dict()` methods, `firestore_repository.py` readers, and TypeScript mapping functions. There is no executable shared contract fixture.
- CI runs the complete backend suite inside the Firestore emulator even for tests that do not use Firestore.
- Python has type annotations, but no repository-level static type gate comparable to the compile-time feedback available in the .NET project.

## Target State

The plan is complete when:

1. `ScannerService` is a small phase coordinator; RSS ingestion and scan write buffering are independently testable.
2. No test module imports helpers from another `test_*.py` module.
3. Scanner test setup uses one explicit builder with overridable dependencies.
4. No production module contains fake repository implementations.
5. Firestore codecs are separate from Firestore I/O and are covered by shared contract fixtures used by Python and TypeScript tests.
6. Strict static checking covers the extracted core modules and runs in CI.
7. Fast backend unit tests run without Java or the Firestore emulator; emulator tests remain a separate gate.
8. A typical RSS behavior change can be understood and validated by reading one service, one focused test module, and one contract module.

Suggested complexity budgets are directional gates, not reasons to distort code:

- `scanner.py`: at most about 500 lines after extraction.
- Each new production module: normally below 400 lines.
- Each scanner-related test module: normally below 600 lines.
- Focused non-emulator test command: should complete in seconds on a warmed local environment.

## Mandatory Execution Rules

1. Execute exactly one numbered step per worker/session.
2. Preserve behavior unless the step explicitly says otherwise.
3. Do not modify `legacy/`.
4. Do not combine this work with proposal-policy, UI, or product changes.
5. Before moving code, add or identify a characterization test for the behavior being moved.
6. Prefer mechanical extraction first; simplify only in a later step after focused tests pass.
7. Do not introduce a framework, dependency-injection container, Pydantic, or a new persistence abstraction.
8. Do not access live RSS, OMDb, Gemini, or production Firestore from tests.
9. Run only the validation command specified by the current step. A failed command may be rerun after repairing that same step.
10. Do not run broad lint, build, emulator, or full-suite commands between checkpoint gates.
11. Do not use line-count reduction as a substitute for cohesive ownership.
12. Stop and report a blocker if an earlier checkpoint gate is not green.

## Checkpoint A: Establish Fast Test Boundaries

### STEP 1 - Extract Shared Scanner Test Support

Status: complete

Create `backend/tests/scanner_test_support.py` and move reusable test-only objects into it:

- `StaticTestFeedFetcher`
- `MockOmdbClient`
- reusable OMDb result builders
- inline RSS feed builders

Update scanner and existing-title-audit tests to import from the support module. Do not change production code or assertions.

Acceptance criteria:

- No test imports a helper from `test_scanner.py`.
- Test doubles remain deterministic and perform no network access.
- Existing scanner and audit tests retain their behavior.

Validation:

```powershell
python -m unittest backend.tests.test_scanner backend.tests.test_existing_title_audit -v
```

### STEP 2 - Add a Scanner Test Builder

Status: complete

Add a `ScannerTestBuilder` to `backend/tests/scanner_test_support.py`. It should create fresh fake repositories by default and allow explicit overrides for config, clock, resolver, fetcher, repositories, and application store.

Replace repeated scanner constructor setup in:

- `backend/tests/test_scanner.py`
- `backend/tests/test_existing_title_audit.py`
- `backend/tests/test_feed_fetcher.py`
- scanner-oriented tests in `backend/tests/test_cli.py`

Keep dependencies visible through named builder methods or keyword arguments. Do not hide meaningful test setup behind magic defaults.

Acceptance criteria:

- A test that changes one dependency configures only that dependency.
- Each build receives fresh mutable repositories unless explicitly shared.
- Production constructor behavior is unchanged.

Validation:

```powershell
python -m unittest backend.tests.test_scanner backend.tests.test_existing_title_audit backend.tests.test_feed_fetcher backend.tests.test_cli -v
```

### STEP 3 - Split Scanner Tests by Behavior

Status: complete

Move tests mechanically from `test_scanner.py` into focused modules. Use names that match the behavior actually present, for example:

- `test_rss_ingestion.py`
- `test_scan_orchestration.py`
- `test_scan_persistence.py`
- keep only compatibility-level `ScannerService` tests in `test_scanner.py`

Do not rewrite assertions while moving them. Shared data creation must come from `scanner_test_support.py`.

Acceptance criteria:

- No scanner-related test module imports another `test_*.py` module.
- Test discovery runs every moved test exactly once.
- Snapshot publication, partial feed failure, parse-only mode, and phase selection have clearly owned test modules.
- No scanner-related test module is a new monolith.

Validation:

```powershell
python -m unittest backend.tests.test_scanner backend.tests.test_rss_ingestion backend.tests.test_scan_orchestration backend.tests.test_scan_persistence -v
```

Checkpoint A gate:

```powershell
python -m unittest discover -s backend/tests -p "test_*.py" -v
```

## Checkpoint B: Isolate Mutable RSS State

### STEP 4 - Introduce Typed Feed Definitions

Status: complete

Create a small immutable `FeedDefinition` in a focused scan-contract module such as `backend/src/movies_feed/scan_contracts.py`. Normalize external settings dictionaries once at the configuration boundary while preserving the existing settings format.

Replace internal `Dict[str, Optional[str]]` feed definitions in scanner/RSS code with `FeedDefinition`. Do not change Firestore settings or CLI input formats.

Acceptance criteria:

- Missing URL for a remote feed fails at one explicit boundary.
- Local feed-file behavior remains supported.
- RSS code no longer repeatedly calls `feed_def.get(...)`.
- Unknown feed types retain current normalization behavior.

Validation:

```powershell
python -m unittest backend.tests.test_rss_ingestion backend.tests.test_feed_fetcher backend.tests.test_cli -v
```

### STEP 5 - Extract the RSS Snapshot Collector

Status: complete

Create `backend/src/movies_feed/rss_snapshot.py` containing a run-scoped collector responsible for:

- accepting candidate title/source/order observations;
- deduplicating title IDs by their earliest effective RSS position;
- grouping movies before series according to current behavior;
- producing immutable, consecutively positioned `RssSnapshotItem` values.

Move `_record_rss_snapshot_candidate` and `_build_rss_snapshot_items` behavior out of `ScannerService`. Publication remains outside the collector.

Acceptance criteria:

- The collector is pure apart from its own in-memory run state.
- Duplicate, mixed movie/series, feed-order, and empty-input cases have direct unit tests.
- Existing snapshot ordering behavior is unchanged.

Validation:

```powershell
python -m unittest backend.tests.test_rss_snapshot backend.tests.test_rss_ingestion -v
```

### STEP 6 - Extract the Scan Write Buffer

Status: complete

Create `backend/src/movies_feed/scan_write_buffer.py`. Move ownership of run-scoped title, occurrence, parse-log, and manual-mapping staging/caches from `ScannerService` into this object, including focused flush operations.

Keep merge semantics in their existing domain/repository functions. The buffer coordinates when writes occur; it must not redefine how entities merge.

Acceptance criteria:

- Buffer state is created fresh for every scan run.
- Reads observe pending writes before repository state, matching current behavior.
- Flush is deterministic and clears only successfully persisted pending data.
- Dry-run and parse-only behavior remains unchanged.
- Direct unit tests cover pending-read visibility, deduplication, flush, and a repository exception.

Validation:

```powershell
python -m unittest backend.tests.test_scan_write_buffer backend.tests.test_scan_persistence -v
```

### STEP 7 - Extract RSS Ingestion Service

Status: complete

Create `backend/src/movies_feed/rss_ingestion.py` and move the complete RSS phase into `RssIngestionService`:

- feed iteration and bounded fetch;
- feed validation;
- date filtering and parse preparation;
- metadata prefetch;
- per-entry processing and match decisions;
- staged writes and parse logging through `ScanWriteBuffer`;
- candidate recording through `RssSnapshotCollector`;
- RSS phase metrics and outcome.

Return one typed `RssPhaseResult` instead of mutating a generic metrics dictionary across module boundaries. `ScannerService` may still apply the result to `ScanRun` for compatibility.

Avoid a callback-heavy extraction. Pass cohesive dependencies or small existing services, not individual scanner methods.

Acceptance criteria:

- RSS behavior can be tested without constructing `ScannerService`.
- One feed failure does not erase successful feed processing.
- Snapshot candidates contain accepted movie/series titles whether or not the title already existed.
- `ScannerService.run()` delegates the RSS phase and does not parse individual entries.
- Existing RSS, persistence, and snapshot tests pass without weakened assertions.

Validation:

```powershell
python -m unittest backend.tests.test_rss_ingestion backend.tests.test_rss_snapshot backend.tests.test_scan_persistence -v
```

Checkpoint B gate:

```powershell
python -m unittest backend.tests.test_scanner backend.tests.test_scan_orchestration backend.tests.test_rss_ingestion backend.tests.test_rss_snapshot backend.tests.test_scan_write_buffer backend.tests.test_scan_persistence -v
```

## Checkpoint C: Make Scanner a Coordinator

### STEP 8 - Extract Explicit Phase Methods

Status: complete

Reduce `ScannerService.run()` to lifecycle orchestration. Introduce small private methods or phase adapters for:

- RSS ingestion;
- existing-title audit;
- reparse-unfound;
- explicit proposal application;
- final status calculation and run persistence.

Use one typed phase outcome shape for status, timing, counters, and errors. Preserve the serialized `ScanRun.phase_metrics` contract.

Acceptance criteria:

- `run()` reads as an ordered list of phases and finalization.
- Mode selection is defined in one place.
- `mode=all` remains non-destructive and never applies proposals.
- Fatal, partial, skipped, and successful status aggregation has direct tests.

Validation:

```powershell
python -m unittest backend.tests.test_scan_orchestration backend.tests.test_cli -v
```

### STEP 9 - Group Scanner Dependencies at the Composition Boundary

Status: complete

Introduce explicit dataclasses such as `ScannerRepositories` and `ScannerServices`, or one similarly small grouping, and construct them in the CLI composition root. Do not add a DI framework or service locator.

Keep a temporary compatibility constructor only if required to avoid a broad one-step migration; remove it within this step once all callers are migrated.

Acceptance criteria:

- Production wiring exists in one composition location.
- Required and optional dependencies are obvious from types.
- Tests override one dependency without rebuilding unrelated wiring.
- No dependency is retrieved from global mutable state.

Validation:

```powershell
python -m unittest backend.tests.test_cli backend.tests.test_scanner backend.tests.test_scan_orchestration -v
```

### STEP 10 - Remove Scanner Compatibility Wrappers and Dead Paths

Status: complete

Use symbol references and tests to remove wrappers made obsolete by the extracted services, including duplicate private/public forwarding methods and repeated validation paths. Do not remove a public CLI behavior or repository method solely to reduce line count.

Acceptance criteria:

- Every remaining scanner method owns orchestration behavior used by at least one production caller.
- Existing-title audit, reparse, and proposal application each have one authoritative implementation path.
- `scanner.py` meets the approximate 500-line budget or documents a concrete reason for exceeding it.

Line-budget note: `scanner.py` remains above the approximate 500-line budget because it is the shared scan lifecycle boundary. It owns run initialization and finalization, phase status and timing aggregation, run persistence, RSS snapshot publication, and the callback adapters connecting the extracted services to the shared write buffer. Moving those responsibilities would either duplicate lifecycle accounting or cross service ownership boundaries.

Validation:

```powershell
python -m unittest backend.tests.test_scanner backend.tests.test_scan_orchestration backend.tests.test_existing_title_audit backend.tests.test_proposal_application -v
```

Checkpoint C gate:

```powershell
python -m unittest discover -s backend/tests -p "test_*.py" -v
```

## Checkpoint D: Separate Persistence Code from Contracts

### STEP 11 - Move Fake Repositories to Test Support

Status: complete

Move fake repository implementations out of `backend/src/movies_feed/repository.py` into `backend/tests/fakes.py`. Keep repository interfaces and pure merge/fingerprint functions in production code.

If production code currently imports a fake as a fallback, replace that usage with explicit composition; do not move a production requirement into tests.

Acceptance criteria:

- Production package contains no `Fake*Repository` classes.
- Fake repositories continue to satisfy the same behavioral contract tests.
- Test imports use `backend.tests.fakes` or a consistent package-relative form.
- Repository interfaces remain capability-focused; do not merge them into a generic repository.

Validation:

```powershell
python -m unittest backend.tests.test_repository backend.tests.test_proposal_application_store backend.tests.test_scanner -v
```

### STEP 12 - Extract Firestore Codecs

Status: not started

Create `backend/src/movies_feed/firestore_codecs.py` and move pure Firestore dictionary conversion into named codecs. Repository classes in `firestore_repository.py` should own queries, batching, and transactions, while codecs own field names, defaults, nullability, and timestamp conversion.

Do not introduce generic reflection-based serialization. Prefer explicit codecs for externally stored documents.

Acceptance criteria:

- Codec tests need no Firestore client or emulator.
- `firestore_repository.py` contains no large inline document parsing functions.
- Round-trip tests cover title, occurrence, scan run, parse log, snapshot, and manual mapping documents where round-trip semantics are supported.
- Backward-compatible defaults are explicit and tested.

Validation:

```powershell
python -m unittest backend.tests.test_firestore_codecs backend.tests.test_firestore_repository -v
```

### STEP 13 - Add Executable Cross-Language Contract Fixtures

Status: not started

Add versioned JSON fixtures under `test-contracts/firestore/` for documents read by both backend and frontend, at minimum:

- title;
- occurrence;
- RSS snapshot state;
- RSS snapshot item.

Add Python codec tests and TypeScript adapter/mapper tests that consume the same fixtures. Export pure TypeScript mapping functions into a focused module if necessary; do not require a Firestore emulator to validate field mapping.

Update `docs/ai/DATA_CONTRACTS.md` to point to the executable fixtures as the source of examples. Documentation is not the executable source of truth.

Acceptance criteria:

- Python serialization output matches the shared fixtures.
- TypeScript decoding of the fixtures produces the expected domain values.
- Missing required snapshot ordering fields fail explicitly.
- Adding or renaming a shared field causes at least one contract test to fail.

Validation:

```powershell
python -m unittest backend.tests.test_firestore_contracts -v
npx vitest run src/test/firestoreContracts.test.ts
```

Checkpoint D gate:

```powershell
npx firebase emulators:exec --project demo-mediadock "python -m unittest discover -s backend/tests -p 'test_firestore*.py' -v"
npx vitest run src/test/catalogRepository.test.ts src/test/firestoreContracts.test.ts
```

## Checkpoint E: Add Fast Static and CI Feedback

### STEP 14 - Introduce Incremental Strict Python Type Checking

Status: not started

Choose one checker and use it consistently. Prefer Pyright because it matches the VS Code/Pylance type model used during development. Add its configuration at the repository root and pin the CLI dependency through the existing Node lockfile, or document and pin an equivalent Python invocation.

Start strict coverage with the newly extracted modules:

- `scan_contracts.py`
- `rss_snapshot.py`
- `scan_write_buffer.py`
- `rss_ingestion.py`
- `firestore_codecs.py`

Use narrow adapter suppressions for untyped Firebase SDK surfaces. Do not add broad `type: ignore` comments or lower checking globally to make the command green.

Acceptance criteria:

- The listed modules pass strict checking with zero errors.
- CI and local development use the same command and configuration.
- New extracted core modules are included by default.
- Firebase-specific uncertainty is isolated at adapter boundaries.

Validation:

```powershell
npx pyright
```

### STEP 15 - Split Fast Unit and Emulator CI Lanes

Status: not started

Classify backend tests with filename/location conventions rather than runtime guessing. Update `.github/workflows/ci.yml` so that:

1. static type checking and non-emulator unit tests run first;
2. Firestore emulator tests run in a separate job or later step;
3. frontend unit/type checks remain separate from rules emulator tests;
4. each command is reproducible locally and documented.

Add minimal scripts only where they remove command ambiguity. Do not add a task runner solely for this plan.

Acceptance criteria:

- Most backend failures are reported without installing/starting Java and the emulator.
- Emulator-dependent tests cannot silently run against production.
- CI still runs the complete existing backend, frontend, rules, and build gates.
- `docs/ai/TESTING.md` lists one focused command per test category.

Validation:

```powershell
python -m unittest discover -s backend/tests -p "test_*.py" -v
npx firebase emulators:exec --project demo-mediadock "python -m unittest discover -s backend/tests -p 'test_firestore*.py' -v"
npx vitest run src/test
npx firebase emulators:exec --project demo-mediadock "npx vitest run firebase/tests/rules.test.ts"
npm run build
```

## Final Gate and Evaluation

### STEP 16 - Measure the Result and Decide on .NET

Status: not started

Update this document with before/after measurements from three representative changes:

1. one RSS parsing or ordering change;
2. one persistence contract field change;
3. one scanner phase/orchestration change.

Record for each change:

- production files that had to be read and edited;
- test files that had to be read and edited;
- focused validation duration;
- full-gate duration;
- defects first found only by runtime tests versus static checking;
- approximate AI session/tool-call count if available.

Decision rule:

- Keep Python if typical changes are localized to one owning module plus focused tests and static feedback catches contract mistakes early.
- Consider incremental .NET migration only if, after this plan, representative backend changes still require broad cross-module context or repeatedly fail at runtime for issues C# would catch statically.
- Do not perform a big-bang rewrite. If migration is justified, define a stable boundary and migrate one worker/use case while retaining the same Firestore contract fixtures.

Final validation:

```powershell
npx pyright
python -m unittest discover -s backend/tests -p "test_*.py" -v
npx firebase emulators:exec --project demo-mediadock "python -m unittest discover -s backend/tests -p 'test_firestore*.py' -v"
npx tsc --noEmit
npx vitest run src/test
npx firebase emulators:exec --project demo-mediadock "npx vitest run firebase/tests/rules.test.ts"
npm run build
```

## Non-Goals

- Rewriting the backend in .NET during this plan.
- Changing product behavior, feed ordering, matching policy, or proposal policy.
- Replacing `unittest` with another test framework merely for style.
- Replacing Firestore.
- Sharing Python classes directly with TypeScript.
- Splitting every model or repository into its own file.
- Optimizing line counts at the cost of discoverability.
- Refactoring frontend components unrelated to Firestore contract decoding.

## New Session Prompt

```text
Work through docs/BACKEND_COMPLEXITY_REDUCTION_PLAN.md using the plan-runner-orchestrator agent.

Start with STEP 1 only. Follow the plan's Mandatory Execution Rules exactly. Before editing, verify the current files named by STEP 1 and identify the focused characterization check. Preserve behavior, do not modify legacy/, do not reopen unrelated proposal-safety work, and do not continue to STEP 2 in the same session.

At completion report: changed files, acceptance criteria met, the exact validation command and result, and any blocker or deviation. Update STEP 1 status in the plan only after its validation passes.
```