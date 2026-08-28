# Data Contracts

## Conventions

- Firestore field names use `camelCase`.
- Stored time values use Firestore `Timestamp`, not formatted date strings.
- Queryable ratings and vote counts are numeric.
- Unknown optional values are absent or `null`; do not store numeric `"N/A"`.
- Writers validate and normalize external data before repository calls.
- IDs and upserts are deterministic to make workflow reruns safe.

This document contains the current storage contract. Source context fields are
defined for occurrences and parse logs but are not populated consistently until
Prompt 4C. Retry state and the audit-proposal collection are later-stage changes.
OMDb cache keys are versioned by Prompt 3. A stage that
changes any of these contracts must update this file, add emulator/fake
compatibility tests, and document backward-read and migration behavior in the
same change.

## `titles/{titleId}`

One normalized movie or series record.

Required fields:

| Field | Type | Notes |
| --- | --- | --- |
| `title` | string | Display title |
| `normalizedTitle` | string | Case-folded matching/deduplication value |
| `year` | number or null | Normalized OMDb year: movie release year or series first broadcast year |
| `mediaType` | string | Backward-compatible display value: `movie`, `series`, `documentary`, or `short` |
| `firstSeenAt` | Timestamp | Earliest known occurrence |
| `lastSeenAt` | Timestamp | Most recent occurrence |
| `updatedAt` | Timestamp | Last metadata update |

Optional normalized OMDb fields include `imdbId`, `imdbRating`, `imdbVotes`,
`metascore`, `genres`, `countries`, `director`, `plot`, `posterUrl`, `runtime`,
`awards`, `boxOffice`, and structured external ratings.

Prompt 2 adds optional normalized type fields:

| Field | Type | Notes |
| --- | --- | --- |
| `sourceType` | string | Canonical OMDb source type, `movie` or `series`; drives feed compatibility |
| `contentKind` | string | `standard`, `documentary`, or `short`; a content facet that never changes `sourceType` |
| `broadcastRange` | map or null | For series only: `startYear`, nullable `endYear`, and the raw OMDb `Year` value |

`mediaType` remains the display field for backward compatibility. A series with
the Documentary genre is stored as `mediaType=series`, `sourceType=series`, and
`contentKind=documentary`. A documentary or short movie remains display
`mediaType=documentary` or `short` with `sourceType=movie`. Legacy documents
without the new fields are read by deriving `sourceType` from `mediaType`.

### Match policy compatibility matrix

The shared policy uses the configured feed type as the expected source type when
it is known. Parser or AI series markers are diagnostics only in a known feed;
they cannot change that feed's type. An unknown feed type may be inferred from a
series marker, an extracted type, or the resolved OMDb source type.

| Expected source type | Resolved source type | Result |
| --- | --- | --- |
| `movie` | `movie` | Compatible, including documentary and short content kinds |
| `movie` | `series` | Rejected with `type_mismatch` |
| `series` | `series` | Compatible, including documentary and short content kinds |
| `series` | `movie` | Rejected with `type_mismatch` |
| unknown | known movie/series | Inferred and evaluated |
| known | unknown | Ambiguous; never silently accepted as the known type |

An explicit manual IMDb mapping bypasses source-type and year checks, but still
passes through country and genre exclusions. The same decision is used by RSS,
reparse, and audit candidate checks.

Movie source years are release years and use the existing inclusive +/-1 year
tolerance. A series source year is a season/release year and is not compared to
the series first broadcast year in `Title.year`. If `broadcastRange` is closed,
the season year must be inside it; an open-ended range accepts years from its
start onward. If the range is unavailable, the season year is not rejected only
because it differs from the normalized series start year. Unknown years are
accepted as non-disqualifying with an explicit `*_year_unknown` reason code.

Deterministic decisions have status `accepted`, `rejected`, or `ambiguous` and a
stable `reasonCode`. Current codes include `type_mismatch`,
`movie_release_year_mismatch`, `series_season_year_out_of_range`,
`source_type_unknown`, `excluded_country`, and `excluded_genre`.

ID rule:

1. Use lowercase OMDb `imdbID` when available, such as `tt1234567`.
2. Otherwise new writes use the lowercase hexadecimal SHA-256 digest of the
   UTF-8 tuple
   `v2:title:<normalized-resolved-title>:<year-semantics>:<canonical-year-or-empty>:<source-type>`.
3. `normalized-resolved-title` is the resolved display title after trimming,
   lowercasing, and collapsing whitespace. `source-type` is `movie`, `series`,
   or `unknown`; documentary and short movies canonicalize to `movie`.
4. `year-semantics` is `movie_release_year` for movies,
   `series_start_year` for series, or `unknown_year`. The canonical year is the
   resolved movie release year or resolved series first-broadcast year, never
   an RSS season year.

The legacy fallback tuple `v1:<caller-title>:<year-or-empty>:<media-type>`
remains available only through an explicit compatibility helper. Existing v1
title documents are readable and coexist naturally with v2 documents; readers
do not reinterpret a stored document ID, and Prompt 4B performs no bulk
migration.

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

Prompt 4A adds an optional typed source context represented by flat fields on
the occurrence document. The five pre-existing occurrence source fields remain
required by the occurrence contract above; their context defaults below apply
to partial compatibility reads and to parse logs:

| Field | Type | Missing-field default | Notes |
| --- | --- | --- | --- |
| `sourceFeedId` | string or null | null | Stable configured feed identity; required on occurrence documents |
| `sourceFeedName` | string or null | null | Mutable source display label; required on occurrence documents |
| `feedType` | string or null | null | `movie`, `series`, or `unknown` when retained by a later writer |
| `feedEntryId` | string or null | null | Original source entry identifier; required but nullable on occurrence documents |
| `torrentUrl` | string or null | null | Original topic/torrent URL; required as a string on occurrence documents |
| `rawTitle` | string or null | null | Unmodified source title; required as a string on occurrence documents |
| `sourcePublishedAt` | Timestamp or null | null | Publication time supplied by the feed; explicit null is preserved |
| `observedAt` | Timestamp or null | null | Scanner observation time for this source context |

The context is considered present only when at least one Prompt 4A marker field
(`feedType`, `sourcePublishedAt`, or `observedAt`) exists. Legacy occurrence
documents already contain several identically named source fields; those fields
alone do not create an inferred `SourceContext`. Missing values are not derived
from publication, observation, or legacy occurrence timestamps.

`sourcePublishedAt` and `observedAt` are independent. Publication time is never
used as an observation time. `firstSeenAt` and `lastSeenAt` continue to describe
scanner observations and retain their existing behavior until Prompt 4C wires
and merges source context consistently.

New occurrence writes use the lowercase hexadecimal SHA-256 digest of the UTF-8
tuple `v2:source:<source-feed-id>:entry:<feed-entry-id>` when a non-empty entry
ID is present. Otherwise they use
`v2:source:<source-feed-id>:url:<torrent-url>`. Each component is trimmed;
entry IDs and URLs remain otherwise opaque and case-sensitive. The stable
`rssFeeds` configuration map key is `source-feed-id`; the mutable display name
never participates in the ID. A missing feed ID, or a missing entry ID and URL,
is rejected rather than hashed as an ambiguous identity. Entry identity takes
precedence over URL, so URL changes do not duplicate an item with a stable GUID.

The legacy tuple `v1:<feed-entry-id-or-torrent-url>` remains available through
an explicit compatibility helper. Existing v1 occurrence documents remain
readable and coexist naturally with v2 documents. They are not reinterpreted,
renamed, or bulk migrated by Prompt 4B. Repeated v2 sightings produce the same
document ID; timestamp merge behavior remains owned by Prompt 4C.

## `omdbCache/{cacheKey}`

| Field | Type | Notes |
| --- | --- | --- |
| `lookupTitle`, `lookupYear` | string, number/null | Normalized request |
| `lookupYearSemantics` | string | `movie_release_year`, `series_season_year`, or `unknown_year` |
| `sourceType` | string | `movie`, `series`, or `unknown`; the requested OMDb source type |
| `lookupIdentity` | string or null | Optional identity scope, used for direct IMDb mappings |
| `status` | string | `found` or `confirmed_not_found` |
| `payload` | map or null | Validated OMDb response |
| `fetchedAt`, `expiresAt` | Timestamp | Fetch time and validity boundary |

The cache key is a SHA-256 digest of the versioned tuple
`v2:cache:<normalized-title>:<lookup-year>:<lookup-year-semantics>:<source-type>:<lookup-identity>`.
Automatic title lookups use an empty identity; direct IMDb mappings use an
`imdb:<id>` identity so a manual override cannot be confused with a title-only
lookup. Old type-less entries and new entries missing the context fields are
ignored by the resolver and are left to natural expiry; no lazy reinterpretation
as movie and series is performed. Only `found` and `confirmed_not_found`
outcomes are persisted. Transport, quota, authentication, malformed-request,
and other service failures are never cached. `cacheHits` includes positive and
confirmed-negative hits.

## `scanRuns/{runId}`

| Field | Type | Notes |
| --- | --- | --- |
| `startedAt`, `finishedAt` | Timestamp | Run start and completion |
| `status`, `trigger` | string | `running/succeeded/partial/failed`, `schedule/manual/local` |
| `feedsProcessed`, `entriesSeen`, `titlesCreated`, `occurrencesCreated`, `cacheHits`, `omdbRequests`, `ignoredEntries`, `errorCount` | number | Counters; `omdbRequests` is the number of actual OMDb HTTP attempts, including fallbacks |
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
| `ignoreReason` | string or null | `no_title`, `parse_error`, `entry_error`, `omdb_not_found`, `excluded_country_or_genre`, `media_type_mismatch`, `year_mismatch`, `match_ambiguous`, `omdb_limit_reached`, `omdb_error`, `audit_needs_review`, `empty_title`, `parse_only`, or null |
| `errorMessage` | string or null | Error or exception details if an error occurred |
| `decision` | string or null | Stable audit decision; the temporary recheck contract uses `needs_review` and never infers it from `errorMessage` |
| `traceDetails` | map or null | Bounded diagnostics. Match checks may include `expectedSourceType`, `matchDecision`, `matchReasonCode`, `omdbSourceType`, `omdbContentKind`, and `omdbBroadcastRange`. Recheck review logs use `auditOutcome` (`orphan`, `ai_batch_incomplete`, `mismatch_retained`), `omdbOutcome` (`missing_corrected_title`, `confirmed_not_found`, `quota_exhausted`, `transport_error`, `invalid_request`, `unexpected_error`, or `malformed_result`), and `candidateOutcome` where applicable |
| `processedAt` | Timestamp | Time when entry was processed |

Parse logs may carry the same optional flat source-context fields documented for
occurrences. Their types and missing-field defaults are identical. A legacy log
without `feedType`, `sourcePublishedAt`, and `observedAt` has no source context;
the reader does not synthesize one from `feedName`, `rawTitle`, or `processedAt`.

| Field | Type | Missing-field default | Notes |
| --- | --- | --- | --- |
| `eventKind` | string or null | null | `source` for one normal source item, or `audit_review` for a separate audit/review event |

Missing `eventKind` means legacy or unknown and is not interpreted as `source`.
A normal `source` parse log represents exactly one source item. Retry attempts
are metadata updates to that source log and must not silently create new IDs.
Audit and review records use `audit_review`, with their own event identity, and
must not overwrite source logs. A source ParseLog uses exactly the same v2
source-item tuple and digest as its occurrence, allowing retries to update the
same log. Audit/review logs instead use the SHA-256 digest of the UTF-8 tuple
`v2:audit:<event-identity>`. The explicit namespace prevents an audit event from
overwriting a source log even when their descriptive identity text matches.
Legacy v1 ParseLogs remain readable and may be updated under their existing ID;
they are never treated as if their digest encoded v2 source identity.

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
