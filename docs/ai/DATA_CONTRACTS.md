# Data Contracts

## Conventions

- Firestore field names use `camelCase`.
- Stored time values use Firestore `Timestamp`, not formatted date strings.
- Queryable ratings and vote counts are numeric.
- Unknown optional values are absent or `null`; do not store numeric `"N/A"`.
- Writers validate and normalize external data before repository calls.
- IDs and upserts are deterministic to make workflow reruns safe.

This document contains the current storage contract. The implementation still
has known legacy gaps that later stages must change explicitly: the cache key is
currently type-less, parse logs do not yet carry complete source/retry context,
and there is no audit-proposal collection. A stage that changes any of these
contracts must update this file, add emulator/fake compatibility tests, and
document backward-read and migration behavior in the same change.

## `titles/{titleId}`

One normalized movie or series record.

Required fields:

| Field | Type | Notes |
| --- | --- | --- |
| `title` | string | Display title |
| `normalizedTitle` | string | Case-folded matching/deduplication value |
| `year` | number or null | Parsed/reported year |
| `mediaType` | string | `movie`, `series`, `documentary`, or `short` |
| `firstSeenAt` | Timestamp | Earliest known occurrence |
| `lastSeenAt` | Timestamp | Most recent occurrence |
| `updatedAt` | Timestamp | Last metadata update |

Optional normalized OMDb fields include `imdbId`, `imdbRating`, `imdbVotes`,
`metascore`, `genres`, `countries`, `director`, `plot`, `posterUrl`, `runtime`,
`awards`, `boxOffice`, and structured external ratings.

ID rule:

1. Use lowercase OMDb `imdbID` when available, such as `tt1234567`.
2. Otherwise use a versioned deterministic SHA-256-derived ID from normalized
   title, numeric year (or empty), and media type.
3. The fallback algorithm/version must have a unit test and must not silently change.

The backend may merge refreshed metadata but must preserve `firstSeenAt`.

## `titles/settings_config`

This backward-compatible document stores scanner settings read by the backend.
It is not a catalog title despite its location under `titles`.

| Field | Type | Notes |
| --- | --- | --- |
| `rssFeeds` | map | At most 20 named entries; each entry has only a string `url` and `type` of `movie` or `series`, with URL length at most 2048. |
| `excludedGenres`, `excludedCountries` | list of strings | At most 100 entries; each non-empty value is at most 500 characters. |
| `minMovieRating`, `minSeriesRating` | number | Inclusive range `0..10`. |
| `minImdbVotes` | integer | Inclusive range `0..1000000000`. |
| `updatedBy` | string | Authenticated UID of the admin who wrote the document, at most 128 characters. |

Allowlisted readers may read this document. Only allowlisted admins may create
or update it, and the rules require `updatedBy == request.auth.uid`. Deletes are
denied. The backend validates the same shape before applying an override; URL
scheme, host, redirect, and IP policy belongs to the bounded fetcher and is not
expanded by this document.

### RSS network boundary

Configured `rssFeeds.*.url` values are network references only. The scanner
passes them to `FeedFetcher`, which accepts HTTPS URLs only when the normalized
host is in the code-owned `feed.rutracker.cc` allowlist. It rejects credentials,
local/file schemes, and DNS results that are private, loopback, link-local,
reserved, unspecified, multicast, or IPv4-mapped private addresses. Every
redirect repeats the same URL and DNS validation; redirects are limited to 3
hops.

The transport verifies TLS, uses a 5-second connect timeout and 20-second read
timeout, requires an RSS/Atom/XML content type and a 2xx status, and limits the
decompressed body to 4 MiB. Parsed feeds are limited to 500 entries. A bozo or
otherwise incomplete parse rejects the entire feed before persistence; entries
are never silently truncated. Local fixtures are separate from configured
network URLs and require the explicit CLI `--feed-file` option.

## `titles/{titleId}/occurrences/{occurrenceId}`

One torrent/feed appearance.

| Field | Type | Notes |
| --- | --- | --- |
| `sourceFeedId` | string | Stable configured feed key |
| `sourceFeedName` | string | Display label |
| `feedEntryId` | string or null | Original stable entry identifier |
| `torrentUrl` | string | External topic/torrent page |
| `rawTitle` | string | Original feed title for diagnostics |
| `quality` | string or null | Parsed quality tag |
| `ripType` | string or null | Parsed rip tag |
| `firstSeenAt` | Timestamp | First scanner observation |
| `lastSeenAt` | Timestamp | Latest scanner observation |

ID rule: deterministic hash of normalized `feedEntryId` when present, otherwise
normalized torrent URL. Repeated sightings update `lastSeenAt` and do not create
a second occurrence.

## `omdbCache/{cacheKey}`

| Field | Type | Notes |
| --- | --- | --- |
| `lookupTitle`, `lookupYear` | string, number/null | Normalized request |
| `status` | string | `found` or supported negative status |
| `payload` | map or null | Validated OMDb response |
| `fetchedAt`, `expiresAt` | Timestamp | Fetch time and validity boundary |

The current cache key is deterministic from title and year only. Prompt 3 must
version it to include lookup semantics and source media type; old type-less
entries must not be treated as valid for every media type. Do not cache
transport, quota, authentication, or malformed-request failures.

## `scanRuns/{runId}`

| Field | Type | Notes |
| --- | --- | --- |
| `startedAt`, `finishedAt` | Timestamp | Run start and completion |
| `status`, `trigger` | string | `running/succeeded/partial/failed`, `schedule/manual/local` |
| `feedsProcessed`, `entriesSeen`, `titlesCreated`, `occurrencesCreated`, `cacheHits`, `omdbRequests`, `ignoredEntries`, `errorCount` | number | Counters |
| `errorSummary` | array | Bounded sanitized summaries |

Run IDs may be generated per execution; idempotency is required for catalog data.

## `parseLogs/{logId}`

One RSS parse result log entry. The current implementation retains logs for one
week (7 days), but retryable work must not be deleted solely because it is old.
Prompt 5 introduces explicit terminal/retryable retention semantics.

| Field | Type | Notes |
| --- | --- | --- |
| `rawTitle` | string | Original feed entry name processed |
| `feedName` | string | Source feed label |
| `parsedSuccessfully` | boolean | True if title and metadata were parsed from rawTitle |
| `parsedTitle` | string or null | Extracted title if successful |
| `parsedYear` | number or null | Extracted year if present |
| `omdbStatus` | string | `found`, `not_found`, `skipped`, `error`, `not_parsed` |
| `ignored` | boolean | True if entry was filtered/skipped |
| `ignoreReason` | string or null | `no_title`, `parse_error`, `entry_error`, `omdb_not_found`, `excluded_country_or_genre`, `omdb_limit_reached`, `omdb_error`, `audit_needs_review`, `empty_title`, `parse_only`, or null |
| `errorMessage` | string or null | Error or exception details if an error occurred |
| `decision` | string or null | Stable audit decision; the temporary recheck contract uses `needs_review` and never infers it from `errorMessage` |
| `traceDetails` | map or null | Bounded diagnostics. Recheck review logs use `auditOutcome` (`orphan`, `ai_batch_incomplete`, `mismatch_retained`), `omdbOutcome` (`missing_corrected_title`, `confirmed_not_found`, `quota_exhausted`, `transport_error`, `invalid_request`, `unexpected_error`, or `malformed_result`), and `candidateOutcome` where applicable |
| `processedAt` | Timestamp | Time when entry was processed |

The existing-title audit is review-only in the current stage. A complete batch
must contain exactly one result for every requested ID, and each result must
contain an explicit boolean `is_valid_match`. Only an explicit valid result may
set `titles/{titleId}.aiValidated=true`; missing, malformed, incomplete, or
low-confidence results leave the title unchanged. Mismatch suggestions are
retained in the review log and never move occurrences or delete a title.
Titles with no occurrences are persisted as `decision=needs_review` with
`auditOutcome=orphan` and are never compared with their stored title.

## `manualMappings/{mappingId}`

Manual IMDb ID override mappings provided by admins for unfound titles.
The current implementation deletes a mapping after a successful IMDb query; the
target workflow consumes it only after filtering and durable catalog persistence
succeed.

| Field | Type | Notes |
| --- | --- | --- |
| `rawTitle` | string | Original feed entry name |
| `imdbId` | string | Valid IMDb ID (e.g., `tt0133093`) |
| `createdAt` | Timestamp | Creation timestamp |
| `parsedTitle` | string or null | Parsed title if available |
| `parsedYear` | number or null | Parsed year if available |
| `createdBy` | string | Authenticated UID of the admin who created the mapping |

Allowlisted readers may read mappings. Only allowlisted admins may create,
update, or delete them. New writes require the exact field allowlist, an IMDb ID
matching `^tt[0-9]{7,10}$`, bounded text fields, and `createdBy` bound to the
authenticated UID. Existing documents remain readable for compatibility.

## `allowlist/{uid}`

| Field | Type | Notes |
| --- | --- | --- |
| `email` | string | Auditable expected email |
| `enabled` | boolean | Access switch |
| `role` | string | `reader` or `admin`; a missing role is treated as a backward-compatible `reader` |

Rules require authentication, matching UID, `enabled == true`, and an email match
against the authenticated token where available. Allowlist writes are server-only.

## `users/{userId}/userTitles/{titleId}`

Owner-scoped title preferences (favorites and ignored titles). Keyed by document ID = `titleId`.

| Field | Type | Notes |
| --- | --- | --- |
| `status` | string | `'favorite'` or `'ignored'` |
| `userId` | string | Owner UID matching path |
| `updatedAt` | Timestamp | Timestamp of state update |

Rules contract:
- Authenticated allowlisted users may access only their own UID path.
- Creates/updates validate explicit field allowlist (`status`, `updatedAt`, `userId`), status enum values (`'favorite'`, `'ignored'`), and immutable `userId`.
- Users cannot list or read another user's root or descendants.

## Catalog Query Contract

Initial catalog query:

1. Order by `lastSeenAt` descending.
2. Add document ID descending as a deterministic tie-breaker.
3. Apply a bounded page size.
4. Continue with `startAfter(lastSeenAt, documentId)`.

The frontend suppresses duplicate IDs when pages are merged. It never uses offset
pagination or fetches the full catalog.

MVP filters/search run over loaded pages. UI copy must not imply that unloaded
history has been searched. Server-side filter combinations may be introduced only
with matching documented queries, indexes, repository tests, and UI semantics.

## Expected Indexes

Create only indexes demanded by implemented Firestore errors/queries. The base
newest-first query may rely on built-in indexes. Any compound media type, country,
rating, votes, or date query must be reflected in `firestore.indexes.json` and in
this contract when introduced.

## Write Ownership Summary

| Path | Browser read | Browser write | Admin scanner write |
| --- | --- | --- | --- |
| `titles/**` | Allowlisted | Denied | Allowed |
| `omdbCache/**` | Denied | Denied | Allowed |
| `scanRuns/**` | Denied by default | Denied | Allowed |
| `parseLogs/**` | Allowlisted | Denied | Allowed |
| `manualMappings/**` | Allowlisted | Admin only | Allowed |
| `allowlist/**` | Own access check only | Denied | Allowed |
| `users/{uid}/**` | Own validated paths | Future own validated paths | Optional |
