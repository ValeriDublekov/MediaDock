# Backend Parsing and Matching Pipelines

Reviewed: 2026-08-25

## Scope

This document describes the active Python backend in `backend/src/movies_feed`. The canonical production entry point is:

```bash
python -m movies_feed.cli --mode <rss|recheck-existing|reparse-unfound|all>
```

The files under `legacy/` are a separate, file-based implementation and are not used by the GitHub Actions scanner. The local `scripts/run_scanner.*` wrappers still target that old entry point; see the findings below.

This is a current-state and risk document, not a production-readiness claim.
Workflow hardening, browser trust-boundary work, and the bounded RSS network
boundary from Prompts 0A-0C are implemented. The remaining refactoring stages
are tracked in `docs/BACKEND_REFACTORING_PROMPTS.md`.

## Building Blocks

| Component | Current responsibility |
| --- | --- |
| `cli.py` | Validates bounded CLI inputs and mode-specific configuration, loads JSON/Firestore settings, selects repositories and mode, creates one `ScannerService`, and maps `ScanRun` status to a process exit code. |
| `feed_fetcher.py` | Fetches allowlisted HTTPS RSS/Atom feeds through bounded, redirect-validated transport, and reads explicitly selected local fixture files. |
| `rutracker_parser.py` | Regex/heuristic extraction of title, year, movie/series flag, quality, and rip type. |
| `omdb_client.py` | Exact OMDb lookup, fallback lookup, broadcast-range extraction, and payload normalization. |
| `metadata_resolver.py` | Shared typed OMDb outcomes, versioned cache, timing, direct IMDb resolution, and one run-wide HTTP budget. |
| `match_policy.py` | Shared typed media classification, source-type compatibility, year semantics, broadcast ranges, and exclusions. |
| `ai_matcher.py` | Gemini batch title extraction, OMDb candidate validation, and stored-match audit. The active prompt strings are currently inline; the files under `prompts/` are not loaded by the current implementation. |
| `scanner.py` | Orchestrates feeds, matching, filtering, repair, logging, and persistence. |
| `repository.py` / `firestore_repository.py` | In-memory and Firestore persistence, title/occurrence merge rules, and deterministic retry-page selection. |

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

- **Movie or unspecified type:** try title + year + optional type, then retry without year. The shared policy applies the existing +/-1 release-year tolerance to the resolved movie candidate.
- **Series:** query title + `type=series` without a year and expose the full broadcast range. The parsed year may identify a later season, while `Title.year` is OMDb's first broadcast year; the shared policy checks the season year against the closed/open range and does not reject solely when the range is unavailable.
- **Resolution boundary:** RSS, reparse-unfound, recheck-existing, and direct IMDb mappings use `OmdbResolver`. It owns the versioned cache, typed outcomes, cache/API timings, and one run-wide budget that counts every actual HTTP attempt, including fallbacks. Only `found` and `confirmed_not_found` are cached; quota, transport, credential, malformed-request, and service failures are never cached.
- **Normalization:** OMDb `Type` becomes `sourceType`; `Documentary` and `Short` are content kinds. A result with `sourceType=series` remains `mediaType=series`, even when its content kind is documentary or short; movie documentaries/shorts retain their legacy display values.
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
| `rss` | Configured feeds | Regex | Yes / one run-wide actual-HTTP budget | No | Titles, occurrences, parse logs, cache |
| `reparse-unfound` | Retained retryable source parse logs | AI | Yes / one run-wide actual-HTTP budget | Extract + conditional validate | Titles, occurrences, source-log lifecycle, cache |
| `recheck-existing` | Stored titles not marked `aiValidated` | No new regex parse | Yes / one run-wide actual-HTTP budget | Audit + conditional validate | Explicit valid flag or review parse logs; no catalog repair |
| `all` | All of the above | Mixed | One shared budget across phases | Yes in phases 2-3 | Union of all writes |

Non-parse-only runs first load manual mappings and prune completed parse logs
older than seven days. Retryable work is retained regardless of age. The configured trigger (`schedule`, `manual`, or `local`) is
metadata only and does not change matching behavior. The CLI preflight requires
Firebase credentials for Firestore modes, OMDb credentials for modes that can
query OMDb, and Gemini credentials for AI modes. It returns exit code `0` only
for `succeeded`, `2` for `partial`, and `1` for `failed` or configuration
errors.

### 1. Standard RSS scan (`--mode rss`)

1. Load feeds and filters from JSON, optionally overridden by `titles/settings_config` in Firestore.
2. Fetch each configured feed through `FeedFetcher`, validate HTTPS host/IP/redirect policy, limits, status, and content type, then pass the returned bytes to `feedparser.parse()`. A bozo/partial parse or an entry count over the configured bound rejects the whole feed before cache, catalog, or parse-log work begins.
3. Regex-parse every entry once to prefetch OMDb cache keys.
4. Process each entry and regex-parse it a second time.
5. If `force_days > 0`, silently skip entries older than the cutoff.
6. Reject empty or unparseable titles and create a parse log.
7. In `--parse-only`, each RSS entry stops after parsing. Parse-only is valid only with `--mode rss`; the CLI rejects combinations such as `--parse-only --mode all` and the scanner also exits before any AI phase. No Firestore, OMDb, Gemini, or parse-log write is performed. An explicitly supplied `--feed-file` is read as bytes through the fixture path and is never passed as a URL to `feedparser`.
8. Resolve a manual mapping by log/occurrence ID, raw title, or normalized parsed title. A successful IMDb lookup bypasses automatic type/year validation. Mapping consumption waits for the durable catalog flush.
9. Otherwise resolve through the versioned `(normalized title, year semantics, source type)` cache. Positive entries live for 30 days by default; confirmed-negative entries live for up to two days. Old type-less entries are ignored until natural expiry.
10. On a cache miss, call OMDb through `OmdbResolver` with a series hint when the parser says series, or with the configured feed type. The resolver counts every actual HTTP request, including fallback requests, and stops the run after a quota response or exhausted budget.
11. Evaluate the shared match policy for source type, movie release year or series season year, and country/genre exclusions. Known feed type remains authoritative; manual IMDb mappings bypass only type/year checks.
12. Write a deterministic title, occurrence, and parse-log record. The stable
	configuration key is the source identity; publication time is retained as
	`sourcePublishedAt`, while occurrence first/last-seen fields use scanner
	observation time. Writes are flushed once per feed with the same merge
	semantics as individual upserts.

`--dry-run` still reads Firestore/cache/manual mappings and calls external APIs, but skips writes. Its created counters are simulated and do not check whether records already exist. `--fake-repos` uses in-memory storage but can still call live OMDb/Gemini APIs. The RSS budget counts actual HTTP requests: one movie lookup can perform both a year-constrained request and a fallback request, and manual IMDb lookups use the same run-wide budget and cache boundary.

### 2. Parse-log reprocessing (`--mode reparse-unfound`)

1. Traverse bounded `list_retryable` pages in deterministic newest-first order using the typed exclusive cursor. Continue until the repository reports no next page; terminal, resolved, audit, filtered, parse-only, and unknown legacy records are excluded by the repository contract.
2. Deduplicate by computed v2 source identity, not by raw title. A retry log must retain a source feed ID and either a feed entry ID or torrent URL. Logs without enough retained context are counted as skipped, updated as retryable, and never receive fabricated provenance or an occurrence.
3. Resolve a matching manual mapping against the retained source log ID, v2 source identity, legacy entry/URL identity, normalized raw title, or normalized parsed title before constructing any Gemini batch. The mapping uses `OmdbResolver.resolve_by_imdb_id()` and is consumed only after filtering and durable title, occurrence, and source-log writes succeed.
4. Send unmatched items to Gemini in batches of 15. Use `SourceContext.feed_type`, compatible retained trace metadata, or `unknown`; never label an untyped retry as `movie`.
5. Use Gemini's title, year, and media type for an `OmdbResolver` lookup through the shared cache and run-wide HTTP budget. Apply the shared match policy for configured exclusions, source-type compatibility, movie release years, and series season years. Only when normalized extracted and OMDb titles differ, ask Gemini to validate the candidate.
6. On a successful manual or AI resolution, upsert the canonical title and an occurrence whose ID is the v2 source-item ID. Preserve the retained feed ID, feed name, entry ID, URL, raw title, feed type, source publication time, observation time, and `SourceContext`. Update the original source log under the same ID to `resolved` with matched resolution metadata; do not create a second success log.
7. On a retryable failure, update the same source log with incremented `attemptCount`, `lastAttemptAt`, and `retryState=retryable`, retaining its source context and clearing resolution metadata. Deterministic policy rejection becomes terminal with bounded resolution metadata. Catalog write failures retain the manual mapping and are retried through the same source identity.
8. Return `resolved`, `retried`, `skipped`, and `failed` counters. `reparsed_succeeded` and `reparsed_failed` remain compatibility aliases. Existing inter-batch delay and parse-only/API isolation remain unchanged.

### 3. Existing-database audit (`--mode recheck-existing`)

1. Load all titles and exclude records already marked `aiValidated`.
2. Optionally filter by `audit_days`, then process newest titles first in batches of 15.
3. Load all occurrences. Titles without occurrences are recorded as orphan `needs_review` outcomes and are not sent to Gemini; titles with occurrences currently use the first raw title as the audit input until occurrence-level audit is introduced.
4. The audit prompt and deterministic policy distinguish a later season year in the raw title from the series' first broadcast year in OMDb; a difference alone is not a mismatch.
5. Require complete response coverage and an explicit boolean `is_valid_match` for every requested ID. Only an explicit valid result sets `aiValidated=true` and `aiCheckedAt`.
6. For an explicit mismatch, use Gemini's corrected title/year/type for a diagnostic `OmdbResolver` lookup when a corrected title exists, and run the result through the shared match policy.
7. Classify missing correction, confirmed no-match, quota, transport, malformed, and candidate validation outcomes in the review log.
8. Keep the current title and every occurrence in place for mismatches, suggestions, uncertain evidence, and retryable failures. Persist `decision=needs_review` with structured audit details; this stage does not migrate or delete catalog data.

The later proposal/application stages will define review and rollback workflows; this temporary stage intentionally stops at a persisted review outcome.

### 4. Combined run (`--mode all`)

The phases run sequentially: RSS scan, DB audit, then parse-log reprocessing. RSS writes are flushed before the audit, so newly added titles may be audited immediately. Review logs written by the DB audit may be selected for AI reprocessing in the same run; the audit itself does not delete catalog data.

The final run status is `succeeded` when `error_count == 0`. An incomplete AI
phase records a run error and produces `partial`; failed/configuration outcomes
map to a non-zero CLI exit code.

### Legacy execution

`legacy/movie_scanner.py` has its own regex + OMDb + JSON-file cache/database pipeline, plus `--html`, `--test-parser`, and `--parse-only` modes. Its parser is nearly a copy of the active parser. It has no Firestore repositories, parse-log reprocessing, DB audit, manual mappings, or Gemini logic.

## Resolved in Prompt 0A

- Workflow dispatch values are read through environment variables, validated as
	bounded decimal values/allowlisted modes, and passed with a shell argument
	array. A static regression test protects this boundary.
- CLI configuration preflight checks mode-specific secrets without logging
	values, and scan status now controls the process exit code.
- Parse-only is an RSS-only early-exit mode with no OMDb, Gemini, Firestore, or
	parse-log writes; CI uses the explicit `demo-mediadock` emulator project.
- RSS input uses a code-owned `feed.rutracker.cc` HTTPS allowlist, validates
	public DNS results and every redirect, verifies TLS, bounds connect/read time,
	decompressed bytes and entries, checks status/content type, and rejects bozo
	feeds before any persistence. Local fixtures require the explicit
	`--feed-file` RSS option.
- CI and local backend checks install the reviewed `backend/requirements.lock`
	set before the editable package.
- Allowlisted readers are read-only for scanner settings and manual mappings;
	only explicit allowlisted admins can write validated documents, with actor
	UIDs bound in both rules and adapters. Browser builds contain no scanner
	credentials or dispatch token.

## Inconsistencies and Bugs

| Priority | Finding | Impact | Recommended fix |
| --- | --- | --- | --- |
| Resolved | Workflow dispatch input handling and scanner process exit semantics. | Prompt 0A validates inputs outside shell source, uses an argument array, and maps `succeeded/partial/failed` to `0/2/1`. | Keep the workflow static regression test and documented exit-code contract green. |
| Resolved | Allowlist membership previously granted settings and manual-mapping writes without enforcing the documented `role`. | Prompt 0B restricts those writes to explicit admins and validates document shape/ownership. | Keep the rules emulator suite green. |
| Resolved | Client configuration previously exposed scanner credentials/control through browser storage and Vite env configuration. | Prompt 0B removes PAT/OMDb credentials and uses GitHub's protected Actions UI. | Keep the bundle/config regression test green. |
| Resolved for Prompt 3 | The implementation and status documents disagreed about Gemini model handling and valid `gemini-2.5-flash*` IDs. | A model setting could be silently changed or use a generation payload incompatible with the selected model. | The configured ID is preserved and AI-mode startup validates the active `models.list` entry supports `generateContent`; generation-setting migration remains Prompt 6. |
| Resolved for Prompt 1 | AI audit is fail-open: a missing item/result defaults to `is_valid_match=True`; candidate validation also accepts missing/failed AI responses. | Partial or malformed AI output can validate wrong data, followed by destructive moves/deletes. | Recheck batches now require complete IDs and explicit booleans, candidate validation fails closed, and uncertain results become review-only outcomes. Full confidence/proposal architecture remains deferred. |
| Critical | DB audit judges a title from only its first occurrence, then moves or deletes every occurrence. | One unrepresentative occurrence can corrupt the entire title aggregate. | Audit each distinct raw-title cluster, split incorrect occurrences, and keep the existing title while any occurrence still validates. |
| Resolved for Prompt 1 | Audit treated OMDb no-match, quota exhaustion, and transport failure as the same missing replacement, then deleted the title and all occurrences. A missing corrected title had the same outcome. | A timeout, exhausted quota, bad credential, or incomplete AI result could erase valid catalog data. | Recheck now preserves catalog data and stores distinct temporary `omdbOutcome` values in `decision=needs_review` logs; resolver/proposal architecture remains deferred. |
| High | AI audit applies a generic ±1 year rule to series. A raw title can contain a later season's year, while OMDb and `Title.year` contain the show's first broadcast year. | Correct matches such as a 2012 season of a series that started in 2007 can be marked invalid and enter the destructive repair/delete path. | Give years explicit semantics (`movieReleaseYear`, `seasonYear`, `seriesStartYear`, and broadcast range); apply ±1 only to movies; for series, validate that the season year is inside the broadcast range or treat it as non-disqualifying when the range is unavailable. Update both AI prompts and deterministic tests. |
| High | `aiValidated` is stored on the aggregate title and preserved by later RSS merges. New occurrences attached to an already validated title do not invalidate the flag and will never be audited. | A later false-positive occurrence can hide permanently behind an earlier title-level validation. | Track validation per occurrence/raw-title cluster and include a validation policy version; invalidate aggregate status whenever a new or changed occurrence is attached. |
| Resolved | `--parse-only --mode all` is rejected and parse-only exits before AI/persistence phases. | Parse-only cannot reach OMDb, Gemini, Firestore, or parse-log writes. | Keep the CLI and scanner regression tests green. |
| Resolved for Prompt 5B | Successful log reprocessing did not resolve/update the source log. | The same unresolved item could be selected on every run until pruning. | Reparse now updates the original source log with same-ID resolution metadata. |
| Resolved for Prompt 5B | Reprocessed occurrences lost `feedEntryId` and `torrentUrl`; their ID was derived from raw title while the stored fields could not reproduce it. | Provenance was lost and later migration could change/collide occurrence IDs. | Reparse now requires retained context and reuses the v2 source-item ID and fields. |
| Resolved for Prompt 3 | Matching/validation code was copied between RSS, reparse, and audit lookup paths. | The same candidate could be resolved with different cache, error, or budget behavior in different modes. | All OMDb lookups now use `OmdbResolver`; deterministic matching remains in `match_policy.py`. |
| High | RSS accepts documentary/short as movie-like, while AI flows use strict `movie == media_type`; AI year checks omit `short`. | Mode-dependent type decisions and missed validation. | Define one compatibility matrix (`movie` may or may not include documentary/short) and use it everywhere. |
| High | Genre-first OMDb normalization can convert a documentary or short **series** into `documentary` or `short`, after which a series feed rejects it. | Correct documentary series can be classified as movie-like and dropped. | Preserve source kind separately from content genre, for example `sourceType=series` plus `contentKind=documentary`; base feed compatibility on source kind. |
| High | Audit/reparse subtract OMDb year from AI year without checking whether OMDb year is `None`. | Valid OMDb payloads with `N/A` year can raise `TypeError`. | Guard both values before arithmetic and return an explicit `year_unknown` decision. |
| Resolved for Prompt 3 | Audit/reparse previously bypassed OMDb cache, request limits, counters, and timing; quota errors were swallowed as ordinary no-match results. | Excess API traffic, misleading run metrics, and repeated calls after quota exhaustion. | `OmdbResolver` now owns cache/API timing, counts actual HTTP attempts including fallbacks, and stops later phases after quota exhaustion. |
| Resolved for Prompt 3 | Most OMDb `Response=False` errors other than text containing `limit reached` were previously treated as `OmdbNoMatchError`. | Authentication, malformed-request, or service errors could suppress a valid title for two days. | OMDb response categories are explicit; only confirmed not-found responses are negative-cached, while credential and service failures become typed non-cacheable outcomes. |
| Resolved for Prompt 3 | Cache key omitted media type and year semantics. | Same-title, same-year movie and series requests could share an invalid positive/negative cache entry. | The v2 key includes normalized title, year semantics, source type, and optional lookup identity; old type-less entries are ignored until natural expiry. |
| Resolved | Feed URLs are passed directly to `feedparser` with no scheme/host validation, timeout, size limit, entry cap, or `bozo`/HTTP check. | SSRF/local-file reads, hangs, amplification, and silent partial feeds were possible. | `FeedFetcher` now owns the allowlist, redirect/IP checks, response limits, and explicit parse-error handling; fixture reads require `--feed-file`. |
| Resolved for Prompt 4C | RSS wrote the source publication timestamp into both `firstSeenAt` and `lastSeenAt`. | New source writes preserve publication separately and merge earliest/latest scanner observation times. Audit recency policy remains owned by Prompt 7B. | Keep rescan timestamp and source-context regression tests green. |
| Resolved for Prompt 5B | Manual mappings were used only while processing a live RSS entry, not while reprocessing parse logs. | A correction remained unused when the source entry left the feed, while Gemini kept retrying it. | Reparse resolves retained manual mappings before AI and preserves enough source context to complete the occurrence. |
| Resolved for Prompt 1 | A title without occurrences was audited by using its own stored title as the raw source text. | Orphaned or partially written titles could self-validate without any source evidence. | Orphans now persist as `decision=needs_review` and are never sent to the AI audit. |
| Medium | RSS regex parsing runs twice per entry, including entries later removed by `force_days`. | Duplicate CPU work and possible future divergence between prefetch and processing. | Parse once into an entry context, filter by date first, then use the same parsed result for prefetch and processing. |
| Resolved for Prompt 5B | Reparse labeled every AI item as a movie and did not preserve feed type in parse logs. | Series extraction was biased and differed from normal RSS behavior. | Reparse uses retained feed type and sends `unknown` when it is absent. |
| Resolved for Prompt 5B | Retry selection previously included every ignored log and could miss eligible work beyond the newest records. | Fake and Firestore repositories now expose bounded deterministic retry pages and derive conservative compatibility state for legacy logs. Reparse now owns cursor continuation and source-identity deduplication. | Keep repository parity, cursor, lifecycle, and provenance tests green. |
| Resolved for Prompt 5A | Unresolved logs were pruned after seven days before reprocessing started. | Age-based retention now removes only terminal/resolved records and preserves retryable work. | Keep old-retryable retention tests green. |
| Resolved for Prompt 5B | Manual mappings were deleted immediately after IMDb retrieval, before filtering and durable catalog writes. | A later rejection/write failure lost the user's correction. | RSS and reparse consume a mapping only after filtering and durable catalog/source-log persistence. |
| Medium | Reparse successes are not marked `aiValidated`; repair counters previously counted upserts as creations. | Repaired data can be re-audited, while later repair metrics may still need richer outcomes. | Prompt 5B fixes reparse created counters by checking existing records; validation provenance remains for the later audit contract. |
| Resolved for Prompt 4C | Firestore `upsert_many()` overwrote instead of applying the merge contract. | Bulk title, occurrence, and source-log writes now delegate to the same transactional merge path as single writes. | Keep fake/Firestore single-versus-bulk contract tests green. |
| Medium | Extraction/validation confidence and AI delay/cooldown settings are not enforced; the audit response schema does not expose confidence at all. | Low-confidence output is accepted and configured rate-control behavior is misleading. | Add confidence to the audit contract, enforce thresholds and one centralized retry/rate limiter, and remove unsupported settings. |
| Resolved for Prompt 4B | Occurrence/log IDs omitted feed identity, and fallback title IDs were built from different title/year semantics in RSS versus reparse. | Equal GUIDs across feeds could overwrite a global parse log or merge same-title occurrences; IMDb-less matches could produce duplicate titles. | New writes use source-aware v2 IDs and canonical resolved title IDs; explicit v1 helpers support natural coexistence without reinterpretation or bulk migration. |
| Medium | Regex heuristics split valid titles such as `Face/Off`, remove arbitrary trailing parentheses, accept numeric-only candidates, and do not bound years. | Incorrect title/year extraction produces false OMDb matches or unnecessary AI retries. | Parse recognized trailing metadata blocks, protect title slashes, require letters, validate year range, and return parse confidence/reasons. |
| Resolved for Prompt 1 | Fake repositories exposed mutable model objects, so audit could change seeded state even in dry-run before the write guard. Empty CLI fakes also make standalone recheck/reparse runs non-representative. | Dry-run tests could lie about mutation safety and fake-mode audit/reparse silently do no useful work. | Fake repositories now return/store defensive copies, and recheck uses a copied title before any validation flag update. |
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
