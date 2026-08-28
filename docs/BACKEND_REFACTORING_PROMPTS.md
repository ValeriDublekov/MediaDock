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

## Prompt 5A: Add Explicit Retry State and Paginated Selection

```text
Goal: make reparse-unfound a bounded repository workflow without invoking AI yet.

Scope: backend/src/movies_feed/models.py, repository interfaces, fake and Firestore parse-log repositories, repository contract tests, and docs/ai/DATA_CONTRACTS.md. Add explicit retry metadata: retryState (`retryable`, `terminal`, or `resolved`), attemptCount, lastAttemptAt, and bounded resolution metadata. Add paginated list_retryable methods with a stable cursor/order.

Contract: only genuinely retryable parse/OMDb failures are selectable. Exclusions, parse-only records, confirmed type/year rejection, malformed terminal input, and resolved records are not selectable. Retryable work is not deleted solely because it is older than seven days; retention may prune terminal records only. Preserve old logs by deriving a conservative compatibility state and never treating unknown legacy failures as confirmed success.

Non-goals: do not call Gemini or OMDb, resolve manual mappings, recreate occurrences, or change parser/AI schemas.

Work: replace broad list_unmapped selection behind a compatibility adapter, define cursor semantics and any required Firestore indexes, and document state transitions and retention.

Tests: fake/Firestore selection parity, pagination beyond the first page, terminal versus retryable filtering, retention of old retryable work, attempt/resolution round trips, and deterministic ordering.

Done when: repository tests pass without network services, the scanner can request a bounded retry page, and the full backend suite is green.
```

## Prompt 5B: Rebuild Reparse Around Retained Source Context

```text
Goal: resolve retained source items safely and preserve their identity.

Scope: backend/src/movies_feed/scanner.py, directly affected models/repositories, and scanner tests. Before Gemini, resolve a matching manual mapping against retained SourceContext. On successful manual or AI/OMDb resolution, update the original source log to resolved/terminal state and recreate or upsert the occurrence with its original feed ID, entry ID, URL, feed type, publication/observation timestamps, and v2 deterministic ID. A failed attempt updates the same log's retry state and never creates a duplicate log. Deduplicate by source identity, not case-sensitive raw title.

Contract: use the stored feed type, or `unknown` when absent; never hard-code `movie`. Parse-only is a run-level early exit and incompatible combinations such as `--parse-only --mode all` are rejected before any OMDb/Gemini call. Manual mappings are consumed only after filtering and durable catalog persistence succeeds.

Non-goals: do not redesign AI response validation, proposal storage, or parser heuristics; Prompt 6 owns AI schema validation.

Work: keep the reparse phase bounded by Prompt 5A pagination, route every lookup through the existing resolver, and make success/failure counters reflect resolved, retried, skipped, and failed work.

Tests: manual mapping after RSS disappearance, series retry, success and failure state transitions, provenance preservation, source-identity deduplication, pagination, retention, manual-mapping budget, and parse-only/all API isolation.

Done when: a successful retry resolves its original log exactly once, a failed retry remains retryable without a duplicate, and narrow plus full backend tests pass.
```

## Prompt 6A: Validate Gemini Responses Strictly

```text
Goal: make every AI operation complete, typed, confidence-aware, and fail-closed.

Scope: one shared AI validation module, AiMatcher response handling, prompt/schema tests, and docs/ai/DATA_CONTRACTS.md. Apply one validator to batch_extract_titles, batch_validate_omdb_matches, and batch_recheck_matches. Require exactly one result for every requested ID, no missing/unknown/duplicate IDs, and no permissive `.get(..., True)` defaults. Require a finite numeric confidence in inclusive 0..1; use documented default minimums of 0.70 for extraction/candidate validation and 0.80 for audit unless the contract explicitly changes them.

Contract: required fields have exact types and ranges; media type is `movie` or `series`; empty titles and semantically invalid corrections fail validation. Audit results require an explicit boolean is_valid_match and confidence. Candidate results require an explicit boolean is_match and confidence. Malformed, partial, low-confidence, blocked, or empty responses become typed failure/needs_review outcomes and callers must not mutate catalog data.

Bound raw titles and OMDb text before prompt construction, bound response bodies before JSON parsing, and treat all external text as data. Make either backend/src/movies_feed/prompts/ or inline templates the single documented source of truth; remove divergence without changing unrelated prompts.

Non-goals: do not change HTTP retry/delay mechanics, source context, proposal application, or deterministic match policy.

Tests: missing/duplicate/extra/wrong-type IDs, invalid ranges, low confidence, series season years, semantically invalid but schema-valid output, empty/blocked responses, and caller fail-closed behavior.

Done when: all three operations use the same validator, thresholds and fields are documented, and the full backend suite passes.
```

## Prompt 6B: Isolate Gemini Transport and Rate Control

```text
Goal: make Gemini transport behavior deterministic, secret-safe, and testable.

Scope: backend/src/movies_feed/ai_matcher.py, focused transport tests, and operational/model documentation. Keep the configured model ID unchanged and send the Gemini key through an x-goog-api-key header for both models.list and generateContent. Inject clock/sleep dependencies for inter-request delay, retry backoff, and forbidden cooldown. Cap response-body size before parsing.

Contract: classify 429/5xx/timeouts as retryable according to one documented policy; classify authentication, forbidden, invalid-model, and other terminal errors separately. Enforce the configured delay between requests and expose accurate API-call/item statistics. Do not let a failed capability or transport call silently become a successful empty result.

Non-goals: do not change the Prompt 6A response schema/thresholds, scanner retry selection, or catalog mutation behavior.

Work: preserve the already completed model capability preflight and header boundary, replace direct time.sleep/time sources with injectable dependencies, and keep logs bounded and secret-free.

Tests: timeout-then-success, 429/5xx retry exhaustion, forbidden response, enforced delay/cooldown, response-size limit, header-only key transport, and accurate statistics.

Done when: transport tests run without sleeping or live API calls, retry classes are documented, and narrow plus full backend tests pass.
```

## Prompt 7A: Define AuditProposal Storage

```text
Goal: create an idempotent review-proposal contract before changing audit behavior.

Scope: AuditProposal model, fake and Firestore repositories, serialization/tests, Firestore indexes if required, and docs/ai/DATA_CONTRACTS.md. Document collection path `/auditProposals/{proposalId}`, allowed status transitions, occurrence-level validation metadata location, maximum evidence size of 32 KiB, and secret-redaction rules before implementing persistence.

Contract: a proposal identifies sourceTitleId, exact occurrence IDs/raw-title cluster, current metadata, proposed resolved metadata, deterministic/AI evidence, numeric confidence, policy version, created/updated timestamps, and status. Use deterministic IDs derived from source title, cluster identity, and policy version. Allowed transitions are pending -> approved/rejected, approved -> applying, applying -> applied/failed, and failed -> pending; applied/rejected are terminal unless a documented new policy version creates a new proposal.

Non-goals: do not change recheck-existing, move occurrences, apply proposals, or add frontend approval UI.

Work: validate bounds and redaction at the repository boundary, implement fake/Firestore parity, and add only indexes demanded by actual queries.

Tests: serialization round trips, deterministic reruns, status-transition rejection, evidence bounds/redaction, fake/Firestore repository contract, and required index/query behavior.

Done when: proposal persistence is independently green and the contract is complete enough for Prompt 7B to write proposals without inventing fields.
```

## Prompt 7B: Audit Occurrence Clusters

```text
Goal: replace title-level audit decisions with idempotent occurrence-level review.

Scope: recheck-existing orchestration, occurrence validation metadata, AuditProposal integration, focused scanner tests, and directly affected docs. Group occurrences by a documented meaningful source/raw-title identity and evaluate every cluster independently; never infer all occurrences from the first one. Valid clusters receive validation metadata and policy version. Ambiguous or mismatched clusters create/update pending proposals and never move or delete catalog data.

Contract: a title is aggregate-validated only when every current cluster is valid under the current policy version. Adding or changing an occurrence invalidates that aggregate state. Titles without occurrences follow the explicit orphan `needs_review` policy. `audit_days` uses observation recency, not publication time. Counters distinguish clusters checked, valid clusters, proposals, retryable failures, and orphans.

Non-goals: do not apply approved proposals, delete titles, move occurrences, or redesign proposal state transitions.

Work: keep the phase idempotent, preserve source context in evidence, and ensure a repeated audit updates the same proposal rather than duplicating it.

Tests: mixed-validity clusters, multiple seasons, new-occurrence invalidation, orphan titles, idempotent reruns, policy-version changes, observation-based audit-days, and catalog immutability.

Done when: each occurrence cluster is independently classified, proposals are stable across reruns, and narrow plus full backend tests pass.
```

## Prompt 8A: Implement the Proposal Application Service

```text
Goal: add a backend-only, recoverable executor using repository interfaces and fake repositories first.

Scope: application service, proposal state machine abstractions, fake-repository tests, and directly affected contract documentation. Re-read and verify source title, named occurrence IDs, policy version, and approved target before writing. Move only named occurrences, preserve source identity/timestamps, merge into an existing target using repository semantics, and remove the old title only when it has no remaining occurrences.

Contract: approved -> applying -> applied or failed is idempotent; stale source data returns to review/failed without applying old evidence. Dry-run produces a plan with zero repository mutation. Confirmed rejection changes only proposal state. Same source/target is a no-op with an explicit result. A repeated or interrupted application must be recoverable.

Non-goals: do not add frontend UI, Firestore-specific leases, or destructive production enablement in this stage.

Work: make the service return explicit planned/applied/skipped/failed outcomes and keep failure details bounded and secret-free.

Tests: partial cluster moves, target already exists, same source/target, stale proposal, repeated/interrupted execution, last-occurrence cleanup, batch-like failure, confirmed rejection, and dry-run.

Done when: fake-repository application behavior is complete and deterministic, with no Firestore or live-service dependency in the tests.
```

## Prompt 8B: Add Firestore Concurrency and Operator Controls

```text
Goal: make approved-repair execution safe under concurrency and platform limits.

Scope: Firestore proposal repository/application adapter, CLI command or mode, emulator tests, operational documentation, and no frontend files. Use a compare-and-set/lease transition for applying, define stale-lease recovery, and prevent two proposals from moving the same occurrence concurrently. Document exact failure-point behavior for writes crossing Firestore batch limits.

Contract: require an operator-visible backup/export or equivalent recovery checkpoint before production destructive execution. The CLI must expose dry-run, confirmed rejection, bounded error reporting, and the documented exit status. A stale proposal must return to review/failed rather than apply old evidence.

Non-goals: do not change proposal meaning, occurrence-cluster audit logic, or add browser approval UI.

Tests: emulator CAS/lease races, stale recovery, concurrent occurrence protection, batch-limit failure/retry, CLI dry-run, stale proposal, target merge, last-occurrence cleanup, and no-secret failure details.

Done when: fake and emulator behavior agree, operator recovery is documented, and the complete backend suite plus emulator contract tests pass.
```

## Prompt 9A: Make RSS Ingestion Single-Pass

```text
Goal: use FeedFetcher and parse each accepted RSS entry once.

Scope: scanner RSS ingestion, a typed parsed-entry context, focused fetcher/scanner tests, and directly affected docs. Do not reimplement networking; configured URLs must continue through the code-owned FeedFetcher. Apply force_days before title parsing when a source date exists, create one parsed context per source item, and reuse it for cache prefetch and processing. Remove the duplicate prefetch parse path.

Contract: each accepted entry is parsed exactly once; the same parsed context drives cache prefetch and processing, and force_days can prevent parsing when the source date is outside the window.

Non-goals: do not change parser heuristics, resolver behavior, retry selection, or the FeedFetcher security policy.

Work: make parse errors and source metadata travel with the single context, while preserving current valid fixture behavior and parse-only isolation.

Tests: force_days before parse, one parse call per entry, same parsed result used for prefetch/processing, source publication handling, redirects/private IP/size/timeout/status/content-type/bozo/entry-limit fixtures, and parse-only no-API behavior.

Done when: each accepted entry has one parse result, no untrusted URL bypasses FeedFetcher, and narrow plus full backend tests pass.
```

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
