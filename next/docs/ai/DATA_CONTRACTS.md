# Persistence And Data Contracts

This document covers PostgreSQL persistence for the new app under `next/server` only. It does not describe the separate root app, Python backend, Firebase/Firestore app, or legacy data stores. For HTTP projections see [API contracts](API_CONTRACTS.md); for runtime flow see [Architecture](ARCHITECTURE.md).

## Schema And Entities

[`MediaDockDbContext`](../../server/src/MediaDock.Infrastructure/Persistence/MediaDockDbContext.cs) exposes the seven sets below and applies entity configurations from the Infrastructure assembly. Entity property-to-column mappings and constraints live in [CatalogConfigurations.cs](../../server/src/MediaDock.Infrastructure/Persistence/Configurations/CatalogConfigurations.cs), [OperationalConfigurations.cs](../../server/src/MediaDock.Infrastructure/Persistence/Configurations/OperationalConfigurations.cs), [SettingsConfiguration.cs](../../server/src/MediaDock.Infrastructure/Persistence/Configurations/SettingsConfiguration.cs), and [MetadataCacheConfiguration.cs](../../server/src/MediaDock.Infrastructure/Persistence/Configurations/MetadataCacheConfiguration.cs). PostgreSQL schema history is in [20260928000000_InitialRelationalSchema.cs](../../server/src/MediaDock.Infrastructure/Persistence/Migrations/20260928000000_InitialRelationalSchema.cs), with the current EF model in [MediaDockDbContextModelSnapshot.cs](../../server/src/MediaDock.Infrastructure/Persistence/Migrations/MediaDockDbContextModelSnapshot.cs). The API applies migrations and exits when configured with `migrate = true` ([Program.cs](../../server/src/MediaDock.Api/Program.cs)).

All tables use a generated `bigint` `Id` primary key. Entity properties below are the C# model; configuration files define their PostgreSQL column names and types.

| Table | Entity and stored fields |
| --- | --- |
| `titles` | [`Title`](../../server/src/MediaDock.Infrastructure/Persistence/Entities/Title.cs): `Id`, `TitleText`, `NormalizedTitle`, `Year`, `MediaType`, `SourceType`, `ContentKind`, `BroadcastRangeStartYear`, `BroadcastRangeEndYear`, `BroadcastRangeRaw`, `ImdbId`, `ImdbRating`, `ImdbVotes`, `Metascore`, `Genres`, `Countries`, `Director`, `Plot`, `PosterUrl`, `Runtime`, `Awards`, `BoxOffice`, `FirstSeenAt`, `LastSeenAt`, `UpdatedAt`. |
| `sources` | [`Source`](../../server/src/MediaDock.Infrastructure/Persistence/Entities/Source.cs): `Id`, `StableKey`, `Name`, `FeedType`, `Url`, `IsEnabled`. |
| `occurrences` | [`Occurrence`](../../server/src/MediaDock.Infrastructure/Persistence/Entities/Occurrence.cs): `Id`, `TitleId`, `SourceId`, `SourceItemKey`, `FeedEntryId`, `TorrentUrl`, `RawTitle`, `SourceFeedName`, `FeedType`, `SourcePublishedAt`, `ObservedAt`, `Quality`, `RipType`, `FirstSeenAt`, `LastSeenAt`. |
| `scan_runs` | [`ScanRun`](../../server/src/MediaDock.Infrastructure/Persistence/Entities/ScanRun.cs): `Id`, `StartedAt`, `FinishedAt`, `Status`, `Trigger`, `FeedsProcessed`, `EntriesSeen`, `TitlesCreated`, `OccurrencesCreated`, `CacheHits`, `OmdbRequests`, `IgnoredEntries`, `ErrorCount`, `ErrorSummary`. |
| `parse_logs` | [`ParseLog`](../../server/src/MediaDock.Infrastructure/Persistence/Entities/ParseLog.cs): `Id`, `SourceId`, `SourceItemKey`, `RawTitle`, `FeedName`, `ParsedSuccessfully`, `ParsedTitle`, `ParsedYear`, `OmdbStatus`, `Ignored`, `IgnoreReason`, `ErrorMessage`, `Decision`, `ProcessedAt`, `RetryState`, `AttemptCount`, `LastAttemptAt`, `FeedType`, `SourcePublishedAt`, `ObservedAt`, `EventKind`. |
| `settings` | [`AppSetting`](../../server/src/MediaDock.Infrastructure/Persistence/Entities/AppSetting.cs): `Id`, `ExcludedGenres`, `ExcludedCountries`, `MinMovieRating`, `MinSeriesRating`, `MinImdbVotes`, `UpdatedAt`. |
| `metadata_cache` | [`MetadataCacheEntry`](../../server/src/MediaDock.Infrastructure/Persistence/Entities/MetadataCacheEntry.cs): `Id`, `CacheKey`, `LookupTitle`, `LookupYear`, `LookupYearSemantics`, `SourceType`, `LookupIdentity`, `Status`, `PayloadJson`, `FetchedAt`, `ExpiresAt`. `PayloadJson` is PostgreSQL `jsonb`; genre, country, and error-summary collections are PostgreSQL `text[]`. |

## Keys And Constraints

The named primary keys are `pk_titles`, `pk_sources`, `pk_occurrences`, `pk_scan_runs`, `pk_parse_logs`, `pk_settings`, and `pk_metadata_cache`. The only alternate unique keys configured by the EF model are:

| Constraint | Unique columns | Purpose |
| --- | --- | --- |
| `ak_sources_stable_key` | `sources.stable_key` | Stable source identity. |
| `ak_occurrences_source_id_source_item_key` | `occurrences.source_id`, `occurrences.source_item_key` | One occurrence identity per source. |
| `ak_metadata_cache_cache_key` | `metadata_cache.cache_key` | One metadata-cache row per resolver key. |

`titles.normalized_title` has a non-unique index, not a unique key. `settings` has no singleton constraint. The settings API reads and updates the lowest-`Id` row, creating one if none exists; the database itself permits more than one row. These distinctions follow the EF configurations and [initial migration](../../server/src/MediaDock.Infrastructure/Persistence/Migrations/20260928000000_InitialRelationalSchema.cs).

Foreign keys are `occurrences.title_id -> titles.id`, `occurrences.source_id -> sources.id`, and nullable `parse_logs.source_id -> sources.id`; all use `RESTRICT` delete behavior. Other non-unique indexes are `ix_titles_normalized_title`, `ix_occurrences_title_id_last_seen_at`, `ix_scan_runs_started_at`, `ix_parse_logs_processed_at`, `IX_parse_logs_source_id`, and `ix_metadata_cache_expires_at`.

Database check constraints enforce:

- `ck_sources_feed_type` restricts `sources.feed_type` to `movie` or `series`.
- `ck_titles_media_type` restricts `titles.media_type` to `movie`, `series`, `documentary`, or `short`; `ck_titles_source_type` restricts nullable `source_type` to `movie` or `series`; `ck_titles_content_kind` restricts nullable `content_kind` to `standard`, `documentary`, or `short`.
- `ck_scan_runs_status` restricts `scan_runs.status` to `running`, `succeeded`, `partial`, or `failed`; `ck_scan_runs_trigger` restricts `trigger` to `schedule`, `manual`, or `local`.
- `ck_settings_min_movie_rating` and `ck_settings_min_series_rating` restrict ratings to 0 through 10; `ck_settings_min_imdb_votes` restricts votes to 0 through 1,000,000,000.
- `ck_parse_logs_retry_state` restricts `parse_logs.retry_state` to `retryable`, `terminal`, or `resolved`; `ck_parse_logs_attempt_count` requires `attempt_count >= 0`.
- `ck_metadata_cache_status` restricts status to `found` or `confirmed_not_found`; `ck_metadata_cache_expiry` requires `expires_at > fetched_at`.

The EF configuration and migration do not define a uniqueness constraint for title metadata identity or an optimistic concurrency token. Do not treat title matching or the settings API's first-row convention as database-enforced uniqueness.

## Idempotency And Transactions

[`SourceItemIdentity.From`](../../server/src/MediaDock.Application/Ingestion/RssIngestionContracts.cs) builds an occurrence key as `entry:<trimmed feed entry id>` when an entry ID is present; otherwise it uses `url:<trimmed torrent URL>`. It throws if neither value is present. The database enforces uniqueness of `(source_id, source_item_key)`. [`PostgresRssIngestionRepository`](../../server/src/MediaDock.Infrastructure/Ingestion/PostgresRssIngestionRepository.cs) looks up a title by nonblank IMDb ID first, then by normalized title, year, and media type; this title match is application logic, not a unique database key. It finds an existing occurrence by source and item key, updates it (including `LastSeenAt`), and preserves the original `FirstSeenAt`. A repeated-feed integration test confirms that replay does not add duplicate titles or occurrences ([IngestionTests.cs](../../server/tests/MediaDock.IntegrationTests/IngestionTests.cs)); [PersistenceTests.cs](../../server/tests/MediaDock.IntegrationTests/PersistenceTests.cs) verifies the database rejects a duplicate occurrence key.

`PostgresRssIngestionRepository.UpsertCatalogItemAsync` calls `BeginTransactionAsync`, saves and commits the title/occurrence upsert together, and rolls back on failure. A full scan is not one transaction: run creation, parse-log saves, each item upsert, and final run-summary save are separate repository operations. The metadata cache key is a lowercase SHA-256 digest of versioned normalized title, year, source type, and year semantics; the resolver caches confirmed `found` results for 30 days and `confirmed_not_found` results for 2 days, not transient failures ([MetadataResolver.cs](../../server/src/MediaDock.Application/Metadata/MetadataResolver.cs), [PostgresMetadataCacheStore.cs](../../server/src/MediaDock.Infrastructure/Metadata/PostgresMetadataCacheStore.cs)). Cache writes use a read-then-write by key followed by `SaveChanges`; the unique key is enforced by PostgreSQL, but the code does not provide a separate concurrent-upsert retry policy.

The Worker acquires the PostgreSQL session advisory lock with `pg_try_advisory_lock` and releases it with `pg_advisory_unlock` for the duration of a scan invocation; a competing Worker invocation skips the scan while that lock is held. This is not a general lock for API writes. [WorkerConcurrencyTests.cs](../../server/tests/MediaDock.IntegrationTests/WorkerConcurrencyTests.cs) verifies that a second lock acquisition fails until the first lease is released. The lock implementation is in [PostgresAdvisoryScanLock.cs](../../server/src/MediaDock.Worker/Locking/PostgresAdvisoryScanLock.cs), and its scope around `RunAsync` is in [Worker Program.cs](../../server/src/MediaDock.Worker/Program.cs).

## Persistence Evidence

The PostgreSQL integration tests apply the EF migration, verify the seven tables and the current single migration, and assert occurrence-key uniqueness in [PersistenceTests.cs](../../server/tests/MediaDock.IntegrationTests/PersistenceTests.cs). Ingestion replay and cache behavior are exercised with PostgreSQL and stubbed HTTP providers in [IngestionTests.cs](../../server/tests/MediaDock.IntegrationTests/IngestionTests.cs); the API projection and validation coverage is in [CatalogApiTests.cs](../../server/tests/MediaDock.IntegrationTests/CatalogApiTests.cs).