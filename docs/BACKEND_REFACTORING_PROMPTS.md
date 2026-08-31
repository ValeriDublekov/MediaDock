# Backend Refactoring Prompt Roadmap

Use these prompts in order. Prompts 0A-0C are prerequisite hardening stages; complete them before changing catalog matching or repair behavior. Each prompt or substage should fit one focused coding session. Do not combine adjacent substages in one session. A substage may depend on earlier substages, but must have its own tests, checkpoint, and reviewable diff.

The roadmap is based on `docs/BACKEND_PARSING_PIPELINES.md`. Complete and verify the current stage before starting the next one. A separate commit after each successful stage is useful, but the prompts do not ask the model to commit.

## Shared Preamble

Paste this before each numbered prompt or substage:

```text
You are refactoring the active MediaDock system. First read docs/BACKEND_PARSING_PIPELINES.md, docs/ai/ARCHITECTURE.md, docs/ai/DATA_CONTRACTS.md, docs/ai/TESTING.md, docs/ai/IMPLEMENTATION_STATUS.md, and inspect the current implementation and nearby tests. Work only in the files named by this stage plus directly affected contract documentation. Do not modify the legacy implementation. Prompts 0A and 0B may modify the explicitly named workflow, rules, frontend configuration, or client files.
Before editing, state one falsifiable local hypothesis about the owning code path and one cheap check that could disconfirm it. Implement only the requested stage. Treat the `Non-goals` section as a hard boundary; if the change requires an unlisted stage, stop and report it. Preserve unrelated behavior and existing public APIs where practical. Do not perform a broad refactor merely to reduce file size; split code only when it creates a clear ownership boundary or is required by the stage contract.
Do not use live RSS, OMDb, Gemini, or production Firestore in tests; mocked transports, fakes, and the Firebase emulator are allowed where the stage requires a repository/rules contract test. Treat feed text, OMDb fields, AI output, and workflow inputs as untrusted data. Never put secrets in URLs, prompts, logs, fixtures, or error summaries. Add focused regression tests before or with the implementation, run the narrow tests first, then run the full backend suite from the repository root. Do not hide a failing test or weaken an assertion. At the end, report changed files, behavioral decisions, contract/migration changes, commands run, and remaining risk. If a prerequisite from an earlier stage is missing, stop and explain it instead of silently rebuilding the whole roadmap.
```

Each new stage below is intentionally written as `Scope`, `Non-goals`, `Contract`,
`Work`, `Tests`, and `Done when`. Do not infer work from a later stage while
implementing an earlier one. If an existing implementation already satisfies a
bullet, add or verify the regression test and leave the behavior unchanged.

## Prompt 9B: Refine Parser Heuristics and Confidence

```text
Goal: fix known title-parser failures without mixing parser work with networking.

Scope: backend/src/movies_feed/rutracker_parser.py, parser result types, the smallest affected scanner/retry adapter, corpus tests, and parser documentation. Parse around recognized trailing metadata instead of arbitrary slash splitting/removal. Preserve embedded title slashes such as Face/Off, meaningful parentheses, and valid multi-language titles; require letters for a Latin candidate, validate a realistic year range, and avoid substring-only series detection.

Contract: return parse confidence and stable reason diagnostics. Low-confidence or ambiguous parses go to retry/review rather than silently guessing. Keep configured known feed type authoritative and preserve existing valid fixtures.

Non-goals: do not reimplement FeedFetcher, change OMDb resolver/cache behavior, redesign AI schemas, or change audit/proposal application.

Tests: table-driven corpus for embedded slashes, parentheses, numeric-only candidates, invalid years, series markers in the wrong place, multilingual titles, quality/rip tags, confidence/reasons, and low-confidence routing.

Done when: the parser corpus is green, existing valid fixtures remain green, and no network or catalog-repair code was refactored unnecessarily.
```

## Prompt 10A: Converge Phase Boundaries and Metrics

```text
Goal: finish ScannerService as orchestration over shared components and make run status truthful.

Scope: scanner/CLI run models and orchestration, phase-focused tests, and docs/ai contracts. Remove remaining duplicate matching, validation, lookup, and persistence branches only where the shared policy/resolver/source-context/retry/AI/proposal services already own the behavior. Keep mode handlers small and explicit.

Contract: mode=all snapshots each phase's eligible input at that phase's start, tags writes with the current run ID, and excludes same-run writes from later phases unless an explicit option enables chaining. Phase status and counters expose attempted/completed/skipped/failed work, cache hits, actual HTTP calls, AI calls/items, retries, proposals, and applied repairs. Any stopped/incomplete AI or OMDb phase prevents succeeded. Dry-run counters describe planned creates/updates/moves rather than claiming every item is new.

Non-goals: do not modify shell scripts, deployment documentation, workflow YAML, or frontend approval UI.

Work: add phase boundaries and counters without changing catalog decisions, and preserve the process exit-code contract.

Tests: one end-to-end fake-repository test for rss, recheck-existing, reparse-unfound, apply-proposals, and all; same-run exclusion; stopped-phase status; actual HTTP/cache/AI counters; and truthful dry-run plans. Assert no production test uses live services.

Done when: all modes expose truthful phase results, mode=all is deterministic, and the full backend suite is green.
```

## Prompt 10B: Align Operations, Scripts, and Documentation

```text
Goal: make local/CI operations use the active package backend and match the verified contracts.

Scope: scripts/run_scanner.ps1, scripts/run_scanner.sh, LOCAL_DEVELOPMENT.md, DEPLOYMENT.md, docs/ai/*.md, the active GitHub workflow, and deterministic workflow/command tests. Use the package CLI, valid arguments, explicit emulator project IDs, documented exit codes, current Gemini model catalog, and the completed phase/resolver/retry/proposal contracts. Clearly mark legacy execution unsupported or remove only references proven unused; never silently delete data.

Contract: every documented command must match the active CLI and verified exit-code/configuration contracts; operational examples must not expose secrets or imply that legacy execution is supported.

Non-goals: do not add new scanner business logic, change proposal semantics, or modify unrelated legacy artifacts.

Work: update commands and examples, add static validation for workflow/argument drift, document intentionally deferred migrations/frontend review UI/indexes, and verify that no operational example exposes secrets or uses a live service in tests.

Tests: script argument checks, workflow static checks, package CLI smoke tests with fake/emulator dependencies, full backend suite, and the repository's frontend/rules checks when available. Run git diff --check for this documentation/workflow stage and use actionlint when installed.

Done when: documented commands are executable, CI and local commands agree, all required checks pass, and remaining risks are explicitly recorded.
```

## Suggested Checkpoint After Each Prompt

1. Confirm the prerequisite, scope, and `Non-goals`; state the local hypothesis and cheap discriminating check.
2. Add or update focused tests for the contract before broad implementation where practical.
3. Review the diff for unrelated changes and verify that only the named files plus directly affected contract documentation changed.
4. Run the narrow tests named by the stage first; repair that slice before widening validation.
5. Run `python -m unittest discover -s backend/tests -v` from the repository root after narrow tests pass.
6. Update `docs/BACKEND_PARSING_PIPELINES.md` and the owning `docs/ai` contract for every behavior, field, ID version, status, index, or migration rule.
7. Run `git diff --check`; for workflow stages, run an available YAML/workflow linter or the repository's deterministic static validation script.
8. Mark the stage complete only when its `Done when` criteria pass. Start the next stage only with a green suite or a documented environment-only blocker.
