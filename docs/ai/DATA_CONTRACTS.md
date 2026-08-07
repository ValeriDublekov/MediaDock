# Data Contracts

## Conventions

- Firestore field names use `camelCase`.
- Stored time values use Firestore `Timestamp`, not formatted date strings.
- Queryable ratings and vote counts are numeric.
- Unknown optional values are absent or `null`; do not store numeric `"N/A"`.
- Writers validate and normalize external data before repository calls.
- IDs and upserts are deterministic to make workflow reruns safe.

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
| `lookupTitle` | string | Normalized request title |
| `lookupYear` | number or null | Requested year |
| `status` | string | `found` or an explicitly supported negative status |
| `payload` | map or null | Validated OMDb response needed for normalization |
| `fetchedAt` | Timestamp | Successful/negative lookup time |
| `expiresAt` | Timestamp | Cache validity boundary |

The cache key is deterministic from normalized title and year. Do not cache
transport failures or API-limit responses as successful misses. Cache freshness
uses `expiresAt`, not client clock-formatted strings.

## `scanRuns/{runId}`

| Field | Type | Notes |
| --- | --- | --- |
| `startedAt` | Timestamp | Run start |
| `finishedAt` | Timestamp or null | Run completion |
| `status` | string | `running`, `succeeded`, `partial`, or `failed` |
| `trigger` | string | `schedule`, `manual`, or `local` |
| `feedsProcessed` | number | Counter |
| `entriesSeen` | number | Counter |
| `titlesCreated` | number | Counter |
| `occurrencesCreated` | number | Counter |
| `cacheHits` | number | Counter |
| `omdbRequests` | number | Counter |
| `ignoredEntries` | number | Counter |
| `errorCount` | number | Counter |
| `errorSummary` | array | Bounded sanitized summaries |

Run IDs may be generated per execution; idempotency is required for catalog data,
not for scan-run audit documents.

## `allowlist/{uid}`

| Field | Type | Notes |
| --- | --- | --- |
| `email` | string | Auditable expected email |
| `enabled` | boolean | Access switch |
| `role` | string | Initially `reader`; reserved for explicit future roles |

Rules require authentication, matching UID, `enabled == true`, and an email match
against the authenticated token where available. Allowlist writes are server-only.

## Reserved `users/{uid}` Namespace

This namespace makes future client writes possible without granting catalog writes.
MVP does not implement a product feature in it.

Rules contract:

- Authenticated allowlisted users may access only their own UID path.
- Creates/updates validate an explicit field allowlist, types, size limits, and
  immutable ownership fields for each future subcollection.
- Users cannot list or read another user's root or descendants.
- Adding a concrete subcollection requires emulator rules tests first.
- A generic recursive `allow write` rule is forbidden.

Until a concrete schema exists, rules should deny writes or permit only a tiny
document explicitly defined for rules-test scaffolding. Do not claim support for
favorites, notes, or preferences before their contracts are added here.

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
| `allowlist/**` | Own access check only | Denied | Allowed |
| `users/{uid}/**` | Own validated paths | Future own validated paths | Optional |
