# Backend Parsing and Matching Pipelines

Reviewed: 2026-08-31

## Scope

This document describes the active Python backend in `backend/src/movies_feed`. The canonical production entry point is:

```bash
python -m movies_feed.cli --mode <rss|recheck-existing|reparse-unfound|all>
```

The files under `legacy/` are a separate, file-based implementation and are not used by the GitHub Actions scanner.

This is a current-state and risk document, not a production-readiness claim.
The controlled release gate is tracked in
`docs/backend-refactoring-plan/06_CHECKPOINT_F_RELEASE.md`.

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
| `scanner.py` | Orchestrates feeds, matching, filtering, logging, and persistence; delegates existing-title audit and explicit proposal application to their services. |
| `existing_title_audit.py` | Owns cluster-level existing-title audit, occurrence validation, review logs, and bounded schema-v2/v3 proposal production. It never applies a proposal. |
| `proposal_application.py` / `firestore_proposal_application_store.py` | Plans one explicit repair proposal and applies it under a per-source lease in one Firestore transaction. |
| `repository.py` / `firestore_repository.py` | In-memory and Firestore persistence, title/occurrence merge rules, deterministic retry-page selection, and proposal storage. |

### Regex title parsing

`parse_rutracker_title()` applies this sequence:

1. Remove one leading bracketed prefix.
2. Extract the first four-digit release year within realistic bounds (1888–2035) after `[` or in parentheses (excluding resolution tags such as 1080p/2160p).
3. Treat text before the first `[` as the title section, stripping trailing director/audio metadata parentheses while preserving meaningful subtitle blocks (e.g. `Death and Rebirth`, `Extended Edition`).
4. Split title candidate sections on slashes with surrounding whitespace (` / `), preserving embedded title slashes (e.g. `Face/Off`, `Frost/Nixon`, `50/50`, `F/X`).
5. Use configured feed type when present; otherwise infer series classification from structured series/episode regex markers (avoiding false positives from movie titles containing season/serial words).
6. Clean candidates, strip series markers, and select the first Latin candidate containing letters. If none has Latin letters, fall back to numeric/ASCII candidates, then to the first candidate.
7. Find quality and rip tags by case-insensitive substring search against configured/default tag lists.
8. Calculate parse confidence (0.0 to 1.0) and attach structured diagnostic reason codes (e.g. `valid_year_extracted`, `latin_candidate_selected`, `embedded_slash_preserved`). Low-confidence parses (< 0.70) are routed to retry/review.

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
| `recheck-existing` | Stored titles with unvalidated occurrence clusters | No new regex parse | Yes / one run-wide actual-HTTP budget | Audit + conditional validate | Occurrence validation, review logs, and audit proposals; no catalog repair |
| `all` | RSS, audit, and reparse inputs | Mixed | One shared budget across phases | Yes in phases 2-3 | Union of those three phases; never proposal application |

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
3. If `force_days > 0` and a source publication date exists, filter out entries outside the window before title parsing.
4. Regex-parse each accepted entry exactly once into a typed `ParsedEntryContext`, and reuse this context for both OMDb cache prefetch and subsequent entry processing without duplicate parsing.
5. Reject empty or unparseable titles and create a parse log.
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

1. `ScannerService` delegates the phase to `ExistingTitleAuditService`, which loads titles not already aggregate-valid.
2. Optionally filter occurrence clusters by `audit_days`, then process newest titles first in batches of 15.
3. Group occurrences by `(sourceFeedId, rawTitle)`. Titles without occurrences are recorded as orphan `needs_review` outcomes and are not sent to Gemini.
4. The audit prompt and deterministic policy distinguish a later season year in the raw title from the series' first broadcast year in OMDb; a difference alone is not a mismatch.
5. Require complete response coverage and an explicit boolean `is_valid_match` for every requested cluster ID. Only a cluster accepted by both AI and deterministic policy receives occurrence-level `validationStatus=valid`; the aggregate title flag is set only when every occurrence is current-policy valid.
6. For an explicit mismatch, use Gemini's corrected title/year/type for a diagnostic `OmdbResolver` lookup when a corrected title exists, and run the result through the shared match policy.
7. Classify missing correction, confirmed no-match, quota, transport, malformed, and candidate validation outcomes in the review log.
8. Keep the current title and every occurrence in place for mismatches, suggestions, uncertain evidence, and retryable failures. Persist `decision=needs_review` with structured audit details; this stage does not migrate or delete catalog data.
9. For each mismatch cluster, emit schema-v2 proposals in chunks of at most 200 occurrences. The deterministic v3 ID covers source title, source feed, normalized raw title, sorted occurrence IDs, and policy version.
10. Emit `repair` only when a complete typed target exists; otherwise emit non-actionable `review_only`. Both carry exact source and occurrence fingerprints. Existing legacy/schema-v1 proposals remain readable but cannot be applied and are not automatically migrated.

### 4. Combined run (`--mode all`)

The phases run sequentially: RSS scan, DB audit, then parse-log reprocessing.
RSS writes are flushed before the audit. By default, same-run IDs are excluded
from later phases to avoid chaining newly written data through multiple phases.
The audit may create proposals, but `mode=all` never invokes proposal
application and does not move or delete catalog data through a proposal.

The final run status is `succeeded` when `error_count == 0`. An incomplete AI
phase records a run error and produces `partial`; failed/configuration outcomes
map to a non-zero CLI exit code.

### 5. Explicit proposal application (`--mode apply-proposals`)

Application is separate from audit and `mode=all`. It accepts one explicit
proposal ID; bulk or automatic application is unsupported. Dry-run performs
planning only, acquires no lease, and writes nothing. A live proposal must be
approved, schema v2, `actionKind=repair`, current-policy, fully fingerprinted,
and contain no more than 200 unique named occurrences.

The Firestore store acquires a per-source lease by changing `approved` to
`applying`, with `leaseOwner` and `leasedUntil`. Before commit it rechecks lease
ownership and expiry, proposal fields, exact source and occurrence
fingerprints, and source membership. Target merge, named occurrence writes,
source occurrence deletes, conditional source-title update/deletion, proposal
`applied` status, and lease cleanup occur in one transaction. A transaction
failure leaves no partial catalog move; stale or expired work requires review
rather than reconstruction.

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

## Current Risks and Deferred Work

| Status | Fact | Operational consequence |
| --- | --- | --- |
| Blocked | Production application still requires the Checkpoint F automated and staging gates plus a verified backup/export. | Do not enable production mutation before those gates pass. |
| Deferred | Frontend proposal review and approval UI is not implemented. | Review and approval use the supported operator path outside the frontend. |
| Deferred | Automatic migration of legacy proposals is not implemented. | Schema-v1 records remain readable but non-actionable; rerun the audit to generate current proposals. |
| Deferred | Bulk and automatic proposal application are unsupported. | Apply at most one explicitly selected, reviewed proposal per invocation. |
| Current | Legacy retry logs without sufficient source context cannot reproduce a v2 source identity. | They remain retryable but are skipped until recoverable provenance is supplied. |
| Current | OMDb quota exhaustion stops remaining lookups and makes the run non-successful. | Monitor cache reuse, actual-attempt counters, and `partial`/`failed` outcomes. |

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
10. Make DB audit generate bounded schema-v2/v3 proposals from exact snapshots; apply one explicitly approved repair separately under a lease and one transaction.

Before enabling proposal application in production, complete the Checkpoint F
release gate, verify a backup/export, dry-run one reviewed proposal, and confirm
the automated and staging results are green.

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
