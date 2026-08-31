# Backend Refactoring Prompt Roadmap

Use these prompts in order. Prompts 0A-0C are prerequisite hardening stages; complete them before changing catalog matching or repair behavior. Each stage should fit one focused coding session. Do not ask one session to execute multiple stages.

The roadmap is based on `docs/BACKEND_PARSING_PIPELINES.md`. Complete and verify the current stage before starting the next one. A separate commit after each successful stage is useful, but the prompts do not ask the model to commit.

## Shared Preamble

Paste this before each numbered prompt:

```text
You are refactoring the active MediaDock system. First read docs/BACKEND_PARSING_PIPELINES.md, docs/ai/ARCHITECTURE.md, docs/ai/DATA_CONTRACTS.md, docs/ai/TESTING.md, docs/ai/IMPLEMENTATION_STATUS.md, and inspect the current implementation and nearby tests. Work only in the files named by this stage plus directly affected contract documentation. Do not modify the legacy implementation. Prompts 0A and 0B may modify the explicitly named workflow, rules, frontend configuration, or client files.
Implement only the requested stage. Preserve unrelated behavior and existing public APIs where practical. Do not use live RSS, OMDb, Gemini, or production Firestore in tests; mocked transports, fakes, and the Firebase emulator are allowed where the stage requires a repository/rules contract test. Treat feed text, OMDb fields, AI output, and workflow inputs as untrusted data. Never put secrets in URLs, prompts, logs, fixtures, or error summaries. Add focused regression tests before or with the implementation, run the narrow tests first, then run the full backend suite from the repository root. Do not hide a failing test or weaken an assertion. At the end, report changed files, behavioral decisions, contract/migration changes, commands run, and remaining risk. If a prerequisite from an earlier stage is missing, stop and explain it instead of silently rebuilding the whole roadmap.
```

## Prompt 0A: Harden CI and Scanner Workflow

```text
Goal: make the scanner workflow safe to dispatch and make CI truthfully fail when the scanner is partial or broken.

Scope for this stage: .github/workflows/scanner.yml, .github/workflows/ci.yml, backend/src/movies_feed/cli.py, and directly affected testing/deployment documentation.

Remove shell injection risk from workflow_dispatch inputs. Read inputs through environment variables, validate force_days and audit_days as decimal integers in an explicit bounded range, keep mode on an allowlist, and pass arguments with a shell array. No untrusted GitHub expression may be interpolated into executable shell source.

Add a mode-aware preflight that checks required secrets without printing them: Firebase credentials for Firestore modes, OMDb for modes that can query OMDb, and Gemini for AI modes. Define parse-only combinations explicitly and guarantee that parse-only makes no external API call. Make the CLI return documented non-zero exit codes: 0 only for succeeded, a distinct code for partial/retryable completion, and a distinct code for failed/configuration errors. A stopped or incomplete AI/OMDb phase must reach both ScanRun status and the GitHub job result.

Make emulator commands use an explicit demo project ID. Add a reproducible dependency strategy, pin GitHub Actions to reviewed commit SHAs where practical, and add a static workflow validation check. Add tests or a deterministic script check for injection payloads, missing mode secrets, scanner exit codes, parse-only/all, and secret-free logs. Do not change matching or catalog repair behavior in this stage.
```

## Prompt 0B: Close Configuration and Client Secret Boundaries

```text
Goal: stop browser users and browser JavaScript from controlling privileged scanner behavior or receiving scanner credentials.

Scope for this stage: firestore.rules, the frontend files that read or store OMDb/GitHub credentials, vite.config.ts, backend configuration loading, and directly affected architecture/deployment documentation and tests.

Define an explicit admin/reader authorization policy. Restrict scanner settings writes and any privileged manual-mapping operations to admin users, validate allowed fields/types/lengths, bind createdBy to request.auth where client writes remain supported, and move settings out of titles/settings_config if that is required to make ownership clear. Add rules tests for reader, admin, disabled, unauthenticated, malformed, and extra-field cases.

Remove OMDB_API_KEY, GitHub PATs, and any equivalent scanner credential from Vite env exposure and localStorage. Manual dispatch must use GitHub's protected UI/CLI or an authenticated server-side control plane. Update deployment documentation so the browser-secret invariant is true rather than aspirational. Add a bundle/config regression test that fails if private scanner credential names are exposed.
```

## Prompt 0C: Add a Bounded RSS Fetcher

```text
Goal: make the privileged scanner's RSS network boundary explicit before any parser or retry refactor.

Add a FeedFetcher that accepts only HTTPS URLs from a code-owned host allowlist, rejects credentials, local/file schemes, private/loopback/link-local/reserved IPs including IPv4-mapped IPv6, validates every redirect, and uses TLS verification, connect/read timeouts, a decompressed response-size limit, content-type/status checks, and an entry limit. Do not let Firestore configuration expand the allowlist. Fetch bytes through this adapter and pass bytes to feedparser; never pass an untrusted URL or local path directly to feedparser.

Treat bozo and partial feeds according to an explicit policy: do not silently persist an incomplete feed. Keep fixture input behind an explicit test/CLI file option, separate from configured network URLs. Add mocked transport tests for redirects, DNS/IP validation, private addresses, oversized/decompressed responses, timeout, bad status/content type, bozo feeds, entry limits, and fixture mode. Do not refactor title parsing in this stage.
```

## Prompt 1: Make DB Audit Non-Destructive

```text
Goal: remove the immediate data-loss risk from recheck-existing without attempting the final audit architecture yet.

Update ScannerService.recheck_existing_titles so catalog records are never deleted or migrated when AI or OMDb evidence is absent, incomplete, malformed, low-confidence, retryable, or contradictory. Require an explicit AI result for every requested item; never default a missing is_valid_match field to true. A title with no occurrences must become needs_review, not be compared with its own stored title. OMDb no-match, quota exhaustion, transport failure, and a missing corrected title must remain distinguishable enough that retryable failures cannot be treated as confirmed mismatch.

For this stage, keep confirmed mismatches and valid replacement suggestions in place and record a clear needs_review parse-log/audit outcome; do not automatically delete the old title or move all occurrences. Only an explicit complete valid result may set aiValidated=true. Make an AI batch failure visible in run status/error counters instead of ending with succeeded.

Add tests for missing AI item IDs, missing fields, empty batches, orphan titles, OMDb timeout, quota exhaustion, no-match, and dry-run. Assert that title and occurrence repositories remain unchanged in every uncertain/mismatch case. Do not introduce a proposal collection or redesign all matching rules yet; those come later.

Define the temporary `needs_review` decision/status in the persisted parse-log/audit contract instead of relying on a free-form message. Ensure dry-run cannot mutate fake model objects through shared references; do not defer that safety requirement to a later repository stage.
```

## Prompt 2: Centralize Media and Year Semantics

```text
Goal: make deterministic match decisions consistent across RSS, reparse, and audit, especially for later TV seasons.

Create one small typed match-policy module and route the three scanner paths through it. Represent source media type separately from content kind so an OMDb documentary series remains a series with documentary content, rather than becoming movie-like. Preserve backward-compatible fields where needed.

Before implementation, document the compatibility matrix. A configured movie/series feed remains authoritative for the normal RSS path; series markers may be diagnostics, but must not silently change a known feed type. An unknown feed type may be inferred. Define whether a manual IMDb mapping bypasses type/year checks while still applying exclusions, and preserve that decision consistently in all modes.

Give years explicit meanings. A movie release year may use the existing +/-1 tolerance. A raw series year is a season/release year and must not be compared with the show's first broadcast year using +/-1. For a series, accept the season year when it is inside OMDb's closed or open broadcast range; when the range is unavailable, do not reject solely because the start year differs. Parse and expose the OMDb broadcast range without losing the current normalized result.

Return a typed decision with accepted/rejected/ambiguous plus stable reason codes. Apply the same type, year, and exclusion policy in RSS, reparse, and audit candidate checks. Specify which backward-compatible field remains the display `mediaType`, where `sourceType` and `contentKind` are stored, and which field drives feed compatibility. Update the current AI audit wording immediately so it explains season-year versus series-start-year semantics, but leave full AI response hardening for Prompt 6.

Add table-driven tests for movies, series with later seasons, open-ended series, out-of-range seasons, unknown years, documentary series, movie documentaries, shorts, and type mismatches. Remove duplicated deterministic branches only after the shared policy tests pass.
```

## Prompt 3: Add One Budgeted OMDb Resolver

```text
Goal: make every mode use the same cache, error classification, quota stop state, timing, and request accounting.

Introduce a MetadataResolver/OmdbResolver abstraction used by RSS, reparse-unfound, recheck-existing, and direct IMDb mappings. Return typed outcomes for found, confirmed_not_found, quota_exhausted, transport_error, invalid_request, and unexpected_error. Cache only found and confirmed_not_found outcomes; never negative-cache credentials, malformed requests, quota, transport, or service failures.

Use `docs/GEMINI_MODELS.md` as the model-ID reference, but do not silently remap valid model IDs or assume that every listed model supports this text/JSON operation. Validate the configured model and its supported `generateContent` capability during preflight or startup.

Version the cache key and include normalized lookup title, lookup year semantics, and media source type. Do not reinterpret an old type-less cache entry as valid for both movie and series. Keep an explicit compatibility strategy for old entries, such as ignoring them until natural expiry.

Enforce one run-wide HTTP budget across all modes and manual mappings. Count actual OMDb HTTP attempts, including fallback requests, rather than only high-level scanner lookups. A quota response must stop further OMDb work for the whole run and make the run partial/failed as appropriate. Record cache and API timings consistently.

Replace direct omdb_client calls in ScannerService only after resolver tests pass. Add tests for fallback request counting, cache isolation by media type, transient errors not cached, shared budget across phases, manual mapping budget, and quota propagation. Do not change parse-log lifecycle or audit proposal persistence in this stage.
```

## Prompt 4: Preserve Source Context and Stable Identity

```text
Goal: retain enough provenance to reproduce occurrences and make IDs/timestamps consistent across every mode.

Add a typed source context containing feed ID/name/type, feed entry ID, torrent URL, raw title, source publication time, and scanner observation time. Extend ParseLog and Occurrence serialization/deserialization with backward-compatible optional fields. Store sourcePublishedAt separately; firstSeenAt/lastSeenAt must describe when the scanner observed the item, so a rescan advances lastSeenAt even for an old publication.

Use the stable configuration key as `sourceFeedId`, not the mutable display name. Define separately whether a parse-log ID represents a source item, an observation, or a retry attempt; a single hash must not accidentally discard the audit history required by Prompt 5.

Version occurrence and parse-log IDs so feed identity participates in source identity. Prevent equal GUIDs from different feeds from overwriting a global parse log or merging unrelated same-title occurrences. Keep old documents readable and document whether new writes use only v2 IDs or perform lazy migration.

Make fallback title IDs derive from canonical resolved OMDb metadata in every path: normalized resolved title, canonical year semantics, and source media type. RSS and reparse must produce the same fallback ID when IMDb ID is absent.

Align fake and Firestore repository behavior: defensive copies or immutable decisions must prevent dry-run mutation, and bulk upserts must honor the same merge contract as single upserts. Add round-trip serialization, ID collision, cross-mode ID, observation timestamp, merge, and dry-run tests. Do not redesign retry selection yet.
```

## Prompt 5: Repair Parse-Log Reprocessing

```text
Goal: turn reparse-unfound into a bounded retry workflow that preserves provenance and honors manual corrections.

Replace the broad list_unmapped behavior with explicit retryable/terminal state, attempt count, last attempt, resolution metadata, and paginated repository methods. Only genuinely retryable parse/OMDb outcomes may enter reprocessing; exclusions, parse-only records, confirmed type/year rejection, and already resolved records must not. Retention must not delete unresolved retry work merely because it is seven days old.

Before calling Gemini, resolve any manual mapping against the retained source context. A successful manual or AI/OMDb resolution must update the original log to terminal/resolved state and recreate the occurrence with its original feed entry ID, URL, feed type, timestamps, and deterministic ID. A failed attempt must update attempt state without creating a duplicate log. Deduplicate by source identity, not case-sensitive raw title.

Remove the hard-coded feed_type=movie and pass the stored type or unknown. Make --parse-only a run-level early exit and reject/normalize incompatible combinations such as --parse-only --mode all so no OMDb or Gemini call is possible.

Add fake and Firestore repository contract tests plus scanner tests for manual mapping after an RSS item disappears, series retry, success resolution, retry failure, pagination, retention, provenance preservation, and parse-only/all. Keep AI schema validation itself for Prompt 6.
```

## Prompt 6: Harden Gemini Contracts and Rate Control

```text
Goal: make all AI outputs explicit, complete, confidence-aware, and fail-closed.

Create one validation layer for batch_extract_titles, batch_validate_omdb_matches, and batch_recheck_matches. For every request, require exactly one response for each requested ID, no unknown/duplicate IDs, all required fields with correct types/ranges, and a supported confidence value. Add numeric confidence to the audit schema. Convert malformed, partial, low-confidence, blocked, or empty responses into typed AI failure/needs_review outcomes; callers must never use permissive .get(..., True) defaults.

Define the exact confidence type and thresholds, for example a finite numeric value in the inclusive 0..1 range, with operation-specific minimums documented in the contract. Treat raw titles and OMDb text as data rather than instructions, bound their size, cap response-body size, and validate schema-compliant but semantically invalid output. Make the standalone files in `backend/src/movies_feed/prompts/` or the inline templates one documented source of truth, not two divergent prompt implementations. Send the Gemini key through a header rather than a URL query parameter.

Revise prompts to state that a series raw year can be a later season year, while OMDb's year is commonly the first broadcast year. The model must not invalidate a series solely for that difference. Let the deterministic match policy decide known type/year cases; call AI only for genuinely ambiguous title identity.

Enforce configured inter-request delay and a clear retry/cooldown policy through injectable clock/sleep dependencies so tests remain fast. Distinguish retryable 429/5xx/timeouts from terminal authentication/model errors, and expose accurate call/item statistics.

Add tests for missing, duplicate, extra, and wrong-type IDs; low confidence; series season years; timeout then success; quota exhaustion; forbidden response; enforced delay; and caller fail-closed behavior. Keep prompts concise and structured to control Flash token usage.
```

## Prompt 7: Audit Occurrence Clusters into Proposals

```text
Goal: replace title-level destructive audit with idempotent, occurrence-level review proposals.

Introduce an AuditProposal model and repository implementations for fake and Firestore storage. A proposal should identify the source title, exact occurrence IDs/raw-title cluster, current metadata, proposed resolved metadata, deterministic/AI evidence, confidence, policy version, timestamps, and status such as pending, approved, rejected, applying, applied, or failed. Use deterministic IDs so reruns update the same proposal instead of duplicating it.

Document the proposal collection path, allowed status transitions, indexes, maximum evidence size, secret-redaction rules, and the exact location of occurrence-level validation metadata in `docs/ai/DATA_CONTRACTS.md` before writing the repository.

Change recheck-existing to group a title's occurrences by meaningful source/raw-title identity and evaluate each cluster independently. Never infer the validity of all occurrences from the first one. Valid clusters receive occurrence-level validation metadata and policy version. Ambiguous or mismatched clusters create/update pending proposals without moving or deleting catalog records. A title is aggregate-validated only when every current cluster is valid under the current policy version; adding/changing an occurrence invalidates that aggregate state.

Titles without occurrences must follow an explicit orphan needs_review policy. The audit_days filter must use observation recency, not publication time. Ensure the phase is idempotent and its counters distinguish checked clusters, valid clusters, proposals, retryable failures, and orphans.

Add mixed-validity, multiple-season, new-occurrence invalidation, orphan, idempotent rerun, policy-version, and audit-days tests. Do not implement application of approved proposals yet.
```

## Prompt 8: Apply Approved Repairs Safely

```text
Goal: add a recoverable executor for explicitly approved audit proposals.

Implement a backend-only application service and CLI mode/command that processes approved AuditProposal records. It must re-read and verify the proposal's source title, occurrence IDs, policy version, and approved target before writing. Use an idempotent state transition (approved -> applying -> applied or failed), and make rerunning after interruption safe.

Use a compare-and-set/lease transition for `applying`, define recovery for stale applications, and prevent two proposals from moving the same occurrence concurrently. Document the exact failure point behavior for writes that span Firestore batch limits. Require an operator-visible backup/export or equivalent recovery checkpoint before enabling destructive application in production.

Move only the occurrences named by the proposal. Preserve their source identity and timestamps. Merge into the canonical target title using repository merge semantics. Remove the old title only when it has no remaining occurrences; otherwise retain and recompute its aggregate validation state. Use Firestore batches/transactions within platform limits and record enough failure detail for retry without exposing secrets. A stale proposal whose source changed must return to pending/failed review rather than applying old evidence.

Dry-run must produce a plan with zero repository mutation. Confirmed rejection must leave catalog data untouched and only change proposal state. Add tests for partial cluster moves, target already exists, same source/target, stale proposal, interrupted/repeated application, last-occurrence cleanup, batch failure, and dry-run. Do not add frontend approval UI in this stage.
```

## Prompt 9: Refine Parser and Single-Pass Ingestion

```text
Goal: use the bounded fetcher from Prompt 0C, parse each accepted RSS entry exactly once, and improve the known regex failures.

Do not reimplement networking here. Integrate the FeedFetcher from Prompt 0C and ensure configured Firestore URLs cannot bypass its code-owned policy.

Create one parsed entry context per source item. Apply force_days before title parsing when a source date exists, then parse once and reuse the same result for cache prefetch and processing. Remove the duplicate prefetch parse path.

Refine the parser around recognized trailing metadata instead of splitting/removing arbitrary text: preserve embedded title slashes such as Face/Off, preserve meaningful parentheses, require letters for a Latin candidate, validate a realistic year range, and avoid substring-only series detection. Return confidence/reason diagnostics and send low-confidence cases to retry/review rather than guessing.

Add table-driven parser corpus tests and fetcher tests for redirects, private IPs, oversized responses, timeout, bad status/content type, bozo feeds, entry limits, local fixtures, force_days, and one parse call per entry. Keep the existing valid fixtures passing.
```

## Prompt 10: Converge Modes, Metrics, and Operations

```text
Goal: finish with ScannerService as orchestration over the shared components and make operational behavior truthful.

Remove remaining duplicate matching, validation, lookup, and persistence branches now that the shared policy, resolver, source context, retry workflow, AI contracts, and audit services exist. Keep mode handlers small and explicit. For mode=all, snapshot each phase's eligible input at run start or define another deterministic boundary so RSS/audit failures created during the run are not immediately reprocessed or recreated by a later phase unless explicitly requested.

Add phase-level status and counters for attempted/completed/skipped/failed work, cache hits, actual HTTP calls, AI calls/items, retries, proposals, and applied repairs. Any stopped AI/OMDb phase or incomplete batch must prevent a succeeded status. Ensure dry-run and fake-repo counters describe planned creates/updates/moves rather than claiming every item is new.

Update scripts/run_scanner.ps1, scripts/run_scanner.sh, LOCAL_DEVELOPMENT.md, DEPLOYMENT.md, docs/ai/*.md, and the active GitHub workflow to use the package CLI, valid arguments, explicit emulator project IDs, documented exit codes, and current model catalog. Clearly mark legacy execution unsupported or remove only references proven unused; do not silently delete user data or unrelated legacy artifacts.

Define the phase boundary for mode=all concretely: snapshot audit/reparse eligibility at the beginning of each phase, tag writes with the current run ID, and exclude logs/titles created by the same run unless an explicit option requests same-run chaining. A phase that is skipped, stopped, incomplete, or blocked must be visible in counters, ScanRun status, and the process exit code.

Run the complete backend suite and add one end-to-end fake-repository test for each mode plus all. Check that no production test performs live network calls. Summarize any intentionally deferred migration, frontend review UI, or Firestore index/rules work.
```

## Suggested Checkpoint After Each Prompt

1. Review the diff for unrelated changes.
2. Run the narrow tests named by the stage.
3. Run `python -m unittest discover -s backend/tests -v`.
4. Update `docs/BACKEND_PARSING_PIPELINES.md` when behavior changes.
5. Run `git diff --check`; when workflow files change, run an available YAML/workflow linter or a deterministic static validation script.
6. Update the owning `docs/ai` contract in the same stage for every new field, ID version, status, index, or migration rule.
7. Start the next prompt only with a green suite or a documented environment-only blocker.
