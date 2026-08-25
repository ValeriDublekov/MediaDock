# Backend Parsing and Matching Pipelines

Reviewed: 2026-08-25

## Scope

This document describes the active Python backend in `backend/src/movies_feed`. The canonical production entry point is:

```bash
python -m movies_feed.cli --mode <rss|recheck-existing|reparse-unfound|all>
```

The files under `legacy/` are a separate, file-based implementation and are not used by the GitHub Actions scanner. The local `scripts/run_scanner.*` wrappers still target that old entry point; see the findings below.

This is a current-state and risk document, not a production-readiness claim.
Workflow hardening, browser trust boundaries, and the bounded RSS network
boundary are prerequisites tracked in `docs/BACKEND_REFACTORING_PROMPTS.md`
(Prompts 0A-0C) and `DEPLOYMENT.md`.

## Building Blocks

| Component | Current responsibility |
| --- | --- |
| `cli.py` | Loads JSON/Firestore settings, selects repositories and mode, creates one `ScannerService`. |
| `rutracker_parser.py` | Regex/heuristic extraction of title, year, movie/series flag, quality, and rip type. |
| `omdb_client.py` | Exact OMDb lookup, fallback lookup, series-period checks, and payload normalization. |
| `ai_matcher.py` | Gemini batch title extraction, OMDb candidate validation, and stored-match audit. The active prompt strings are currently inline; the files under `prompts/` are not loaded by the current implementation. |
| `scanner.py` | Orchestrates feeds, matching, filtering, repair, logging, and persistence. |
| `repository.py` / `firestore_repository.py` | In-memory and Firestore persistence plus title/occurrence merge rules. |

### Regex title parsing

`parse_rutracker_title()` currently applies this sequence:

1. Remove one leading bracketed prefix.
2. Extract the first four digits after `[` or a four-digit value in parentheses.
3. Treat everything before the first `[` as the title section and remove its final parenthesized block.
4. Split the title section on every `/`.
5. Use the configured feed type when present; otherwise infer series markers from keywords/regex.
6. Clean candidates and choose the first "Latin-like" candidate, falling back to the first candidate.
7. Find quality and rip tags by case-insensitive substring search against configuration lists.

The feed type is authoritative: a series-looking title in a `movie` feed is still parsed as a movie.

### OMDb lookup

- **Movie or unspecified type:** try title + year + optional type, then retry without year. A fallback movie is rejected when its year differs by more than one year.
- **Series:** query title + `type=series` without a year, then require the requested season year to fall inside OMDb's full broadcast range. The parsed year and stored `Title.year` therefore have different valid meanings: the parsed year may identify a later season, while `Title.year` is OMDb's first broadcast year.
- **Normalization:** genre classification runs before OMDb type classification. Any result with the `Documentary` or `Short` genre, including an OMDb series, becomes `documentary` or `short`; otherwise an OMDb series stays `series` and everything else becomes `movie`.
- **Direct IMDb mapping:** `get_by_imdb_id()` skips title/year lookup logic.

### AI operations

| AI operation | Used by |
| --- | --- |
| Extract title/year/type from raw torrent text | `reparse-unfound` only |
| Validate a new OMDb candidate | `reparse-unfound` and repair inside `recheck-existing`, only when normalized titles differ |
| Audit a stored title against a raw occurrence | `recheck-existing` only |

The normal RSS path does **not** call Gemini for extraction or candidate validation.

## Execution Modes

| Mode | Input | Parser | OMDb cache/limit | AI | Main writes |
| --- | --- | --- | --- | --- | --- |
| `rss` | Configured feeds | Regex | Yes / 50 counted lookups by default | No | Titles, occurrences, parse logs, cache |
| `reparse-unfound` | Recent unresolved/ignored parse logs | AI | No / no enforced limit | Extract + conditional validate | Titles, synthetic occurrences, new parse logs |
| `recheck-existing` | Stored titles not marked `aiValidated` | No new regex parse | No / no enforced limit | Audit + conditional validate | Validate, migrate, or delete titles/occurrences |
| `all` | All of the above | Mixed | Mixed | Yes in phases 2-3 | Union of all writes |

Every run first loads manual mappings. Non-dry runs also prune parse logs older than seven days. The configured trigger (`schedule`, `manual`, or `local`) is metadata only and does not change matching behavior.

### 1. Standard RSS scan (`--mode rss`)

1. Load feeds and filters from JSON, optionally overridden by `titles/settings_config` in Firestore.
2. Fetch each feed with `feedparser.parse()`.
3. Regex-parse every entry once to prefetch OMDb cache keys.
4. Process each entry and regex-parse it a second time.
5. If `force_days > 0`, silently skip entries older than the cutoff.
6. Reject empty or unparseable titles and create a parse log.
7. In `--parse-only`, each RSS entry stops after parsing. The CLI uses fake repositories, so these logs are not persisted outside the process. With `--mode all`, however, the same in-memory logs can continue into AI reprocessing later in the run.
8. Resolve a manual mapping by log/occurrence ID, raw title, or normalized parsed title. A successful IMDb lookup bypasses automatic type/year validation.
9. Otherwise read the `(normalized title, year)` cache. Positive entries live for 30 days by default; negative entries live for up to two days.
10. On a cache miss, call OMDb with a series hint when the parser says series, or with the configured feed type.
11. Validate feed type and movie/documentary/short year tolerance, then apply country and genre exclusions.
12. Write a deterministic title, occurrence, and parse-log record. Writes are batched once per feed.

`--dry-run` still reads Firestore/cache/manual mappings and calls external APIs, but skips writes. Its created counters are simulated and do not check whether records already exist. `--fake-repos` uses in-memory storage but can still call live OMDb/Gemini APIs. The RSS limit counts high-level lookups, not HTTP requests: one movie lookup can perform both a year-constrained request and a fallback request, and manual IMDb lookups occur before the soft-limit check.

### 2. Parse-log reprocessing (`--mode reparse-unfound`)

1. Read up to 200 recent logs selected when their OMDb status is unresolved **or when `ignored == true`**.
2. Deduplicate by exact, case-sensitive raw title.
3. Send batches of 15 raw titles to Gemini. Every item is labelled `feed_type=movie`, regardless of its original feed.
4. Use Gemini's title, year, and media type for a direct, uncached OMDb lookup.
5. Reject configured exclusions, strict type mismatch, and movie/documentary year differences over one year.
6. Only when normalized extracted and OMDb titles differ, ask Gemini to validate the candidate.
7. On success, upsert a title and a synthetic occurrence, then create a separate success parse log.
8. On an individual failure, increment an in-memory counter only; the source log is not updated. If an entire AI batch returns no results, stop the phase without counting the unprocessed items or adding a run error.

### 3. Existing-database audit (`--mode recheck-existing`)

1. Load all titles and exclude records already marked `aiValidated`.
2. Optionally filter by `audit_days`, then process newest titles first in batches of 15.
3. Load all occurrences, but send only the first occurrence's raw title to Gemini with the current OMDb metadata.
4. Gemini currently applies a generic one-year difference rule. For a later season, it can compare the season year in the raw title with the series' first broadcast year in OMDb and incorrectly report a mismatch.
5. If Gemini says the match is valid, set `aiValidated=true` and `aiCheckedAt`.
6. For a mismatch, use Gemini's corrected title/year/type for a direct, uncached OMDb lookup.
7. Apply exclusions, strict type/year checks, and conditional Gemini candidate validation.
8. If accepted, create/merge the corrected title, move every old occurrence, then delete the old title and occurrence collection.
9. If no acceptable replacement is found, delete the old title and all occurrences and add a failure parse log.

The repair/delete sequence is not transactional and has no review or rollback state.

### 4. Combined run (`--mode all`)

The phases run sequentially: RSS scan, DB audit, then parse-log reprocessing. RSS writes are flushed before the audit, so newly added titles may be audited immediately. Failures written by either RSS or DB audit may be selected for AI reprocessing in the same run; a title deleted by audit can therefore be recreated immediately by phase 3.

The final run status is `succeeded` when `error_count == 0`, even when an AI phase stops because AI is unavailable or returns no results.

### Legacy execution

`legacy/movie_scanner.py` has its own regex + OMDb + JSON-file cache/database pipeline, plus `--html`, `--test-parser`, and `--parse-only` modes. Its parser is nearly a copy of the active parser. It has no Firestore repositories, parse-log reprocessing, DB audit, manual mappings, or Gemini logic.

## Inconsistencies and Bugs

| Priority | Finding | Impact | Recommended fix |
| --- | --- | --- | --- |
| Critical | `workflow_dispatch` accepts free-form `force_days`/`audit_days` strings and interpolates them into the scanner shell command. | A user able to dispatch the workflow can inject shell syntax into a job that has Firebase, OMDb, and Gemini secrets. | Pass inputs through environment variables, validate a bounded numeric range, use a shell argument array, and add a workflow regression check. |
| Critical | The CLI logs a non-success `ScanRun` status but does not return a non-zero process exit code. | GitHub Actions can report a green job after a partial/failed scanner run. | Define exit-code semantics and make incomplete AI/OMDb phases affect both `ScanRun` and the process result. |
| High | Allowlist membership currently grants access to settings and manual-mapping writes without enforcing the documented `role`. | A reader account can alter privileged scanner inputs or mappings. | Add an explicit admin policy, validate fields and lengths in rules/backend, and test reader/admin/disabled cases. |
| High | Client configuration exposes a path for scanner credentials/control through browser storage and Vite env configuration. | XSS or a compromised dependency can steal a PAT or OMDb key and trigger privileged operations. | Remove private scanner credentials from the browser and use GitHub's protected dispatch or a server-side control plane. |
| High | The implementation and status documents disagree about Gemini model handling: the code defaults to `gemini-3.1-flash-lite`, remaps valid `gemini-2.5-flash*` IDs, and the status mentions Gemini 3.7. | A model setting can be silently changed or use a generation payload incompatible with the selected model. | Use `docs/GEMINI_MODELS.md`, stop silently remapping valid IDs, validate `generateContent` capability, and test model-specific generation settings. |
| Critical | AI audit is fail-open: a missing item/result defaults to `is_valid_match=True`; candidate validation also accepts missing/failed AI responses. | Partial or malformed AI output can validate wrong data, followed by destructive moves/deletes. | Validate complete response ID coverage and required fields; fail closed; require a confidence threshold; quarantine proposals instead of deleting immediately. |
| Critical | DB audit judges a title from only its first occurrence, then moves or deletes every occurrence. | One unrepresentative occurrence can corrupt the entire title aggregate. | Audit each distinct raw-title cluster, split incorrect occurrences, and keep the existing title while any occurrence still validates. |
| Critical | Audit treats OMDb no-match, quota exhaustion, and transport failure as the same missing replacement, then deletes the title and all occurrences. A missing corrected title has the same outcome. | A timeout, exhausted quota, bad credential, or incomplete AI result can erase valid catalog data. | Model `matched`, `not_found`, `quota_exhausted`, `transport_error`, and `invalid_request` separately; never mutate catalog data for retryable/incomplete outcomes; create a review proposal instead. |
| High | AI audit applies a generic ±1 year rule to series. A raw title can contain a later season's year, while OMDb and `Title.year` contain the show's first broadcast year. | Correct matches such as a 2012 season of a series that started in 2007 can be marked invalid and enter the destructive repair/delete path. | Give years explicit semantics (`movieReleaseYear`, `seasonYear`, `seriesStartYear`, and broadcast range); apply ±1 only to movies; for series, validate that the season year is inside the broadcast range or treat it as non-disqualifying when the range is unavailable. Update both AI prompts and deterministic tests. |
| High | `aiValidated` is stored on the aggregate title and preserved by later RSS merges. New occurrences attached to an already validated title do not invalidate the flag and will never be audited. | A later false-positive occurrence can hide permanently behind an earlier title-level validation. | Track validation per occurrence/raw-title cluster and include a validation policy version; invalidate aggregate status whenever a new or changed occurrence is attached. |
| High | `--parse-only --mode all` does not remain parse-only: its ignored in-memory logs are selected by phase 3 and can reach Gemini and OMDb. | A supposedly offline/no-API mode can perform external requests when Gemini is configured. | Make parse-only an early run-level exit after RSS parsing, reject incompatible mode combinations, and add a no-external-call regression test. |
| High | Successful log reprocessing does not resolve/update the source log. | The same unresolved item can be selected on every run until pruning. | Add repository `mark_resolved(log_id, decision)` or overwrite the original deterministic log with resolution metadata. |
| High | Reprocessed occurrences lose `feedEntryId` and `torrentUrl`; their ID is derived from raw title while the stored fields cannot reproduce it. | Provenance is lost and later migration can change/collide occurrence IDs. | Persist source IDs/URL/feed type in `ParseLog` and reuse the original occurrence ID and fields. |
| High | Matching/validation code is copied between RSS, reparse, and audit but has different rules. | The same candidate can be accepted in one mode and rejected in another. | Introduce one `MetadataResolver` and one typed `validate_match()` decision pipeline used by all modes. |
| High | RSS accepts documentary/short as movie-like, while AI flows use strict `movie == media_type`; AI year checks omit `short`. | Mode-dependent type decisions and missed validation. | Define one compatibility matrix (`movie` may or may not include documentary/short) and use it everywhere. |
| High | Genre-first OMDb normalization can convert a documentary or short **series** into `documentary` or `short`, after which a series feed rejects it. | Correct documentary series can be classified as movie-like and dropped. | Preserve source kind separately from content genre, for example `sourceType=series` plus `contentKind=documentary`; base feed compatibility on source kind. |
| High | Audit/reparse subtract OMDb year from AI year without checking whether OMDb year is `None`. | Valid OMDb payloads with `N/A` year can raise `TypeError`. | Guard both values before arithmetic and return an explicit `year_unknown` decision. |
| High | Audit/reparse bypass OMDb cache, soft request limit, request counters, and OMDb timing. Quota errors are swallowed as ordinary no-match results. | Excess API traffic, misleading run metrics, and repeated calls after quota exhaustion. | Route every lookup through one cached, budget-aware resolver and propagate global quota exhaustion. |
| High | Most OMDb `Response=False` errors other than text containing `limit reached` become `OmdbNoMatchError`. RSS then stores a negative title cache entry. | Authentication, malformed-request, or service errors can suppress a valid title for two days; audit may turn the same classification into deletion. | Parse OMDb error categories explicitly and cache only confirmed title-not-found outcomes. |
| High | Cache key omits media type. | Same-title, same-year movie and series requests can share an invalid positive/negative cache entry. | Version the key and include normalized media type; migrate or naturally expire old keys. |
| High | Feed URLs are passed directly to `feedparser` with no scheme/host validation, timeout, size limit, entry cap, or `bozo`/HTTP check. | SSRF/local-file reads, hangs, amplification, and silent partial feeds are possible. | Add a bounded HTTPS `FeedFetcher`, host allowlist, redirect/IP checks, response limits, and explicit parse-error handling. |
| High | RSS writes the source publication timestamp into both `firstSeenAt` and `lastSeenAt`. Audit filtering prefers this old `lastSeenAt` over the newer `updatedAt`. | A release rescanned today can be excluded by `audit_days` because it was published months ago. | Store `sourcePublishedAt` separately; set observed `firstSeenAt`/`lastSeenAt` from scanner time and define audit recency against an explicit field. |
| High | Manual mappings are used only while processing a live RSS entry, not while reprocessing parse logs. | A correction remains unused when the source entry has left the feed, while Gemini keeps retrying it. | Resolve manual mappings before AI in the shared retry pipeline and persist enough source context to complete the occurrence. |
| High | A title without occurrences is audited by using its own stored title as the raw source text. | Orphaned or partially written titles can self-validate without any source evidence. | Treat missing provenance as `needs_review` or remove it through a separate orphan-reconciliation policy; never AI-validate a self-comparison. |
| Medium | RSS regex parsing runs twice per entry, including entries later removed by `force_days`. | Duplicate CPU work and possible future divergence between prefetch and processing. | Parse once into an entry context, filter by date first, then use the same parsed result for prefetch and processing. |
| Medium | Reparse labels every AI item as a movie and does not preserve feed type in parse logs. | Series extraction is biased and differs from normal RSS behavior. | Store `feedType` in `ParseLog` and pass it to AI; use `unknown` rather than a false movie default. |
| Medium | `list_unmapped()` includes every ignored log, including exclusions, parse-only, quota skips, and already-found type/year rejects. Firestore only examines the newest `limit * 2` logs. | Wasted AI calls and missed older eligible failures. | Query explicit retryable states with a resolution/retry status and paginate until the requested count is reached. |
| Medium | Unresolved logs are pruned after seven days before reprocessing starts. | A week-long AI outage or retry backlog permanently discards pending work. | Apply retention only to terminal logs; retain or archive retryable work according to explicit attempt/age policy. |
| Medium | Manual mappings are deleted immediately after IMDb retrieval, before filtering and durable catalog writes. | A later rejection/write failure loses the user's correction. | Delete or mark a mapping consumed only after an atomic successful persistence step. |
| Medium | Reparse successes are not marked `aiValidated`; repair counters also count upserts as creations. | Repaired data is re-audited and run metrics are inaccurate. | Persist validation provenance and return explicit created/updated/moved/deleted outcomes from repositories. |
| Medium | Firestore `upsert_many()` overwrites instead of applying the merge contract and is non-transactional with prior reads. | Concurrent runs can lose earliest/latest timestamps or metadata. | Use transactional/bulk-writer merge semantics or server-side monotonic timestamp updates. |
| Medium | Extraction/validation confidence and AI delay/cooldown settings are not enforced; the audit response schema does not expose confidence at all. | Low-confidence output is accepted and configured rate-control behavior is misleading. | Add confidence to the audit contract, enforce thresholds and one centralized retry/rate limiter, and remove unsupported settings. |
| Medium | Occurrence/log IDs omit feed identity, and fallback title IDs are built from different title/year semantics in RSS versus reparse. | Equal GUIDs across feeds can overwrite a global parse log or merge same-title occurrences; IMDb-less matches can produce duplicate titles. | Version IDs around canonical source identity and canonical resolved metadata; add an explicit migration/compatibility plan. |
| Medium | Regex heuristics split valid titles such as `Face/Off`, remove arbitrary trailing parentheses, accept numeric-only candidates, and do not bound years. | Incorrect title/year extraction produces false OMDb matches or unnecessary AI retries. | Parse recognized trailing metadata blocks, protect title slashes, require letters, validate year range, and return parse confidence/reasons. |
| Medium | Fake repositories expose mutable model objects, so audit can change seeded state even in dry-run before the write guard. Empty CLI fakes also make standalone recheck/reparse runs non-representative. | Dry-run tests can lie about mutation safety and fake-mode audit/reparse silently do no useful work. | Return copies from fakes, make dry-run decisions immutable, and seed explicit fixtures for these modes. |
| Low | Local run scripts call a missing root `movie_scanner.py`; local docs also pass an unsupported positional feed path to the new CLI. | Documented local execution fails or accidentally encourages the legacy path. | Point wrappers/docs to `python -m movies_feed.cli` and expose an explicit `--feed-file` option if fixture parsing is required. |

## Recommended Target Flow

1. Fetch each feed through a validated, bounded HTTP adapter.
2. Parse each entry once into a typed `ParsedCandidate` containing source IDs, feed type, year semantics, confidence, and diagnostics.
3. Resolve an optional manual IMDb override without consuming it yet.
4. Resolve OMDb through one type-aware cache and one run-wide request budget.
5. Apply one deterministic compatibility policy for title, year, media type, and exclusions.
6. Request AI validation only for ambiguous candidates; require complete, high-confidence output and fail closed.
7. Produce a typed decision such as `matched`, `retryable`, `rejected`, or `needs_review`.
8. Persist source publication time separately from scanner observation time.
9. Persist the title, occurrence, source-log resolution, cache, and mapping consumption atomically where possible.
10. Make DB audit generate review proposals from a stable phase input snapshot; apply approved occurrence-level migrations separately.

Before enabling the target flow in production, complete the workflow/control
plane and fetch-boundary prerequisites in Prompts 0A-0C. In particular, a green
GitHub job must mean that the scanner returned a successful exit code, and a
configured feed URL must never bypass the code-owned fetch policy.

## Minimum Regression Coverage

- Partial/missing/duplicate AI response IDs and low-confidence responses.
- A later series season year remains valid against an earlier OMDb series start year, while a year outside a closed broadcast range is rejected.
- Adding a new occurrence to an AI-validated title invalidates or independently validates only that occurrence.
- OMDb timeout, quota, auth error, missing correction, and orphan title never trigger catalog deletion.
- `--parse-only --mode all` makes no OMDb or Gemini calls.
- OMDb results with unknown years and movie/documentary/short compatibility.
- Documentary series preserve their series source type.
- Same title/year with different media types in cache.
- Reprocess success marks the original log resolved and preserves source occurrence fields.
- Manual mappings can resolve retained parse logs after their RSS entries disappear.
- A title containing both valid and invalid occurrences is split without deleting valid data.
- OMDb quota exhaustion stops all remaining lookup modes and produces `partial`/`failed` status.
- Observation timestamps advance on rescans independently from source publication dates.
- Source-aware IDs do not collide across feeds and all modes derive the same fallback title ID.
- Parser corpus for embedded `/`, meaningful parentheses, numeric candidates, invalid years, and misplaced series entries.
- Firestore and fake repositories return the same paginated retry set and merge behavior.
- Workflow inputs cannot inject shell syntax; missing secrets and partial scanner outcomes fail the job without leaking secret values.
- Reader accounts cannot write scanner settings or privileged mappings, while admin behavior is covered by emulator rules tests.
- Configured Gemini IDs are checked against the active API capability and the generation payload used by `AiMatcher`.
