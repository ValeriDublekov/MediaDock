import datetime
import unittest
from dataclasses import replace
from typing import Optional

try:
    from . import _test_stubs
    from .scanner_test_support import (
        MockOmdbClient,
        ScannerTestBuilder,
        make_inline_feed,
        make_multi_entry_feed,
        make_series_result,
    )
except ImportError:
    import _test_stubs
    from scanner_test_support import (
        MockOmdbClient,
        ScannerTestBuilder,
        make_inline_feed,
        make_multi_entry_feed,
        make_series_result,
    )

from movies_feed.models import (
    ManualMapping,
    OmdbCacheEntry,
    ParseLog,
    RssSnapshot,
    RssSnapshotItem,
    SourceContext,
    Title,
    Occurrence,
    ScanRun,
)
from movies_feed.omdb_client import OmdbMovieResult, OmdbTransportError, OmdbClient
from movies_feed.repository import (
    FakeAuditProposalRepository,
    FakeTitleRepository,
    FakeOccurrenceRepository,
    FakeOmdbCacheRepository,
    FakeScanRunRepository,
    FakeParseLogRepository,
    FakeRssSnapshotRepository,
    FakeManualMappingRepository,
)
from movies_feed.scanner import ScannerConfig, ScannerService
from movies_feed.ids import get_occurrence_id_v1, get_source_item_id, get_title_id_v2

class TestScanner(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime.now(datetime.timezone.utc)
        self.title_repo = FakeTitleRepository()
        self.occ_repo = FakeOccurrenceRepository()
        self.cache_repo = FakeOmdbCacheRepository()
        self.run_repo = FakeScanRunRepository()
        self.parse_log_repo = FakeParseLogRepository()
        self.manual_mapping_repo = FakeManualMappingRepository()
        self.audit_proposal_repo = FakeAuditProposalRepository()
        self.scanner_builder = ScannerTestBuilder(
            now=self.now,
            title_repo=self.title_repo,
            occurrence_repo=self.occ_repo,
            cache_repo=self.cache_repo,
            run_repo=self.run_repo,
            parse_log_repo=self.parse_log_repo,
            manual_mapping_repo=self.manual_mapping_repo,
            audit_proposal_repo=self.audit_proposal_repo,
        )

        self.valid_movie = OmdbMovieResult(
            title="The Matrix", year=1999, imdb_id="tt0133093",
            media_type="movie", rating=8.7, votes=1000000, metascore=92,
            genres=["Action", "Sci-Fi"], countries=["USA"], director="Wachowski", plot="Matrix", poster_url=None,
            runtime="136 min", awards="Oscars", box_office=None, ratings=[], 
            raw_payload={
                "Response": "True", "Title": "The Matrix", "Year": "1999", "imdbID": "tt0133093",
                "Genre": "Action, Sci-Fi", "Country": "USA", "Type": "movie"
            }
        )

        self.filtered_movie = OmdbMovieResult(
            title="Filtered Movie", year=2000, imdb_id="tt9999999",
            media_type="movie", rating=1.0, votes=100, metascore=10,
            genres=["Action", "Horror"], countries=["Russia"], director="Someone", plot="Plot", poster_url=None,
            runtime="90 min", awards=None, box_office=None, ratings=[], 
            raw_payload={
                "Response": "True", "Title": "Filtered Movie", "Year": "2000", "imdbID": "tt9999999",
                "Genre": "Action, Horror", "Country": "Russia", "Type": "movie"
            }
        )

    def create_scanner(self, config: ScannerConfig, omdb_client: OmdbClient) -> ScannerService:
        return self.scanner_builder.build(
            config=config,
            omdb_client=omdb_client,
            now=self.now,
        )

    def make_retry_log(
        self,
        log_id: str,
        raw_title: str,
        *,
        source_feed_id: str,
        feed_entry_id: str,
        feed_type: str = "movie",
        processed_at: Optional[datetime.datetime] = None,
    ) -> ParseLog:
        return ParseLog(
            id=log_id,
            raw_title=raw_title,
            feed_name=source_feed_id,
            parsed_successfully=True,
            parsed_title=None,
            parsed_year=None,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=processed_at or self.now,
            source_context=SourceContext(
                source_feed_id=source_feed_id,
                source_feed_name=source_feed_id,
                feed_type=feed_type,
                feed_entry_id=feed_entry_id,
                torrent_url=f"https://example.test/{source_feed_id}/{feed_entry_id}",
                raw_title=raw_title,
                source_published_at=self.now - datetime.timedelta(days=2),
                observed_at=self.now - datetime.timedelta(days=1),
            ),
            event_kind="source",
        )

    def test_successful_rss_run_publishes_movie_first_snapshot_order(self):
        snapshot_repo = FakeRssSnapshotRepository()
        config = ScannerConfig(
            rss_feeds={
                "series-feed": {
                    "name": "Series Feed",
                    "url": make_multi_entry_feed([
                        ("series-1", "Seasoned Show / Сезон 5 [2012]"),
                    ]),
                    "type": "series",
                },
                "movie-feed-1": {
                    "name": "Movie Feed 1",
                    "url": make_multi_entry_feed([
                        ("movie-1", "The Matrix (1999) [1080p]"),
                        ("movie-1-duplicate", "The Matrix (1999) [2160p]"),
                    ]),
                    "type": "movie",
                },
                "movie-feed-2": {
                    "name": "Movie Feed 2",
                    "url": make_multi_entry_feed([
                        ("movie-2", "Filtered Movie (2000) [720p]"),
                    ]),
                    "type": "movie",
                },
            },
            omdb_limit=10,
        )
        scanner = self.scanner_builder.build(
            config=config,
            omdb_client=MockOmdbClient({
                "the matrix": self.valid_movie,
                "filtered movie": self.filtered_movie,
                "seasoned show": make_series_result(),
            }),
            rss_snapshot_repo=snapshot_repo,
        )

        run = scanner.run("snapshot-order")

        self.assertEqual(run.status, "succeeded")
        latest = snapshot_repo.get_latest()
        self.assertIsNotNone(latest)
        snapshot, items = latest
        self.assertEqual(snapshot.run_id, "snapshot-order")
        self.assertEqual([item.title_id for item in items], [
            self.valid_movie.imdb_id,
            self.filtered_movie.imdb_id,
            make_series_result().imdb_id,
        ])
        self.assertEqual([item.source_type for item in items], ["movie", "movie", "series"])
        self.assertEqual([item.rss_position for item in items], [0, 1, 2])
        self.assertEqual(len(self.title_repo.list_all()), 3)

    def test_partial_rss_run_keeps_previous_snapshot_published(self):
        snapshot_repo = FakeRssSnapshotRepository()
        previous_snapshot = RssSnapshot(
            id="previous-snapshot",
            run_id="previous-run",
            created_at=self.now,
            item_count=1,
        )
        previous_item = RssSnapshotItem(
            title_id=self.valid_movie.imdb_id,
            source_type="movie",
            group_order=0,
            feed_order=0,
            entry_order=0,
            rss_position=0,
        )
        snapshot_repo.publish("previous-snapshot", previous_snapshot, [previous_item])
        config = ScannerConfig(
            rss_feeds={
                "working-feed": {
                    "name": "Working Feed",
                    "url": make_inline_feed("The Matrix (1999) [1080p]"),
                    "type": "movie",
                },
                "broken-feed": {
                    "name": "Broken Feed",
                    "url": "tests/fixtures/missing-feed.xml",
                    "type": "movie",
                },
            },
            omdb_limit=10,
        )
        scanner = self.scanner_builder.build(
            config=config,
            omdb_client=MockOmdbClient({"the matrix": self.valid_movie}),
            rss_snapshot_repo=snapshot_repo,
        )

        run = scanner.run("partial-snapshot-run")

        self.assertEqual(run.status, "partial")
        latest = snapshot_repo.get_latest()
        self.assertIsNotNone(latest)
        self.assertEqual(latest[0].id, "previous-snapshot")

    def test_parse_logs_creation_and_pruning(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "tests/fixtures/movies_feed.atom",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({"four rooms": self.valid_movie})
        scanner = self.create_scanner(config, omdb)
        scanner.run("run_logs")

        logs = self.parse_log_repo.list_recent()
        self.assertGreater(len(logs), 0)
        sample_log = logs[0]
        self.assertTrue(sample_log.parsed_successfully)
        self.assertIsNotNone(sample_log.raw_title)

    def test_source_ids_use_stable_feed_key_not_display_name(self):
        raw_title = "Матрица / The Matrix (Вачовски) [1999, США, фантастика, BDRip 1080p]"
        published_at = datetime.datetime(2020, 1, 2, 12, 0, tzinfo=datetime.timezone.utc)
        first_observed_at = self.now
        config = ScannerConfig(
            rss_feeds={
                "stable-feed": {
                    "name": "Original Display Name",
                    "url": make_inline_feed(raw_title, "Thu, 02 Jan 2020 12:00:00 GMT"),
                    "type": "movie",
                }
            },
            omdb_limit=10,
        )
        self.create_scanner(config, MockOmdbClient({"the matrix": self.valid_movie})).run("stable_feed_first")
        config.rss_feeds["stable-feed"]["name"] = "Renamed Display Label"
        self.now = first_observed_at + datetime.timedelta(days=1)
        self.create_scanner(config, MockOmdbClient({"the matrix": self.valid_movie})).run("stable_feed_second")

        expected_id = get_source_item_id("stable-feed", "series-guid-1", None)
        occurrences = self.occ_repo.list_by_title(self.valid_movie.imdb_id)
        source_logs = [log for log in self.parse_log_repo.get_all() if log.event_kind == "source"]
        self.assertEqual(len(occurrences), 1)
        occurrence = self.occ_repo.get(self.valid_movie.imdb_id, expected_id)
        self.assertEqual(occurrence.source_feed_id, "stable-feed")
        self.assertEqual(occurrence.source_feed_name, "Renamed Display Label")
        self.assertEqual(occurrence.first_seen_at, first_observed_at)
        self.assertEqual(occurrence.last_seen_at, self.now)
        self.assertEqual(occurrence.source_context.source_published_at, published_at)
        self.assertEqual(occurrence.source_context.observed_at, self.now)
        self.assertEqual([log.id for log in source_logs], [expected_id])
        self.assertEqual(source_logs[0].source_context.source_feed_id, "stable-feed")
        self.assertEqual(source_logs[0].source_context.source_published_at, published_at)
        self.assertEqual(source_logs[0].source_context.observed_at, self.now)

    def test_equal_guids_from_different_feed_keys_create_distinct_source_items(self):
        raw_title = "Матрица / The Matrix (Вачовски) [1999, США, фантастика, BDRip 1080p]"
        config = ScannerConfig(
            rss_feeds={
                "movies-primary": {
                    "name": "Shared Display Name",
                    "url": make_inline_feed(raw_title),
                    "type": "movie",
                },
                "movies-secondary": {
                    "name": "Shared Display Name",
                    "url": make_inline_feed(raw_title),
                    "type": "movie",
                },
            },
            omdb_limit=10,
        )

        self.create_scanner(config, MockOmdbClient({"the matrix": self.valid_movie})).run("two_feeds")

        occurrence_ids = {
            get_source_item_id("movies-primary", "series-guid-1", None),
            get_source_item_id("movies-secondary", "series-guid-1", None),
        }
        self.assertEqual(len(self.occ_repo.list_by_title(self.valid_movie.imdb_id)), 2)
        self.assertEqual({log.id for log in self.parse_log_repo.get_all()}, occurrence_ids)

    def test_legacy_v1_manual_mapping_id_remains_usable(self):
        legacy_id = get_occurrence_id_v1(
            "series-guid-1",
            "https://example.com/torrent/series-1",
        )
        mapping = ManualMapping(
            id=legacy_id,
            raw_title="No raw-title match",
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
        )
        self.manual_mapping_repo.set(mapping)
        config = ScannerConfig(
            rss_feeds={
                "stable-feed": {
                    "name": "Movies",
                    "url": make_inline_feed(
                        "Матрица / The Matrix (Вачовски) [1999, США, фантастика, BDRip 1080p]"
                    ),
                    "type": "movie",
                }
            },
            omdb_limit=10,
        )

        run = self.create_scanner(config, MockOmdbClient({self.valid_movie.imdb_id: self.valid_movie})).run(
            "legacy_mapping"
        )

        self.assertEqual(run.titles_created, 1)
        self.assertEqual(self.manual_mapping_repo.get_all(), [])

    def test_rss_and_reparse_share_fallback_title_id(self):
        result_without_imdb = replace(
            self.valid_movie,
            imdb_id=None,
            raw_payload={**self.valid_movie.raw_payload, "imdbID": ""},
        )
        raw_title = "Матрица / The Matrix (Вачовски) [1999, США, фантастика, BDRip 1080p]"
        rss_config = ScannerConfig(
            rss_feeds={
                "movies": {
                    "name": "Movies",
                    "url": make_inline_feed(raw_title),
                    "type": "movie",
                }
            },
            omdb_limit=10,
        )
        self.create_scanner(rss_config, MockOmdbClient({"the matrix": result_without_imdb})).run(
            "fallback_rss"
        )
        expected_title_id = get_title_id_v2(None, "The Matrix", 1999, "movie")
        self.assertIsNotNone(self.title_repo.get(expected_title_id))

        retry_log = ParseLog(
            id=get_source_item_id("archive", "archived-entry", None),
            raw_title="Archived Matrix Release",
            feed_name="Archive",
            parsed_successfully=True,
            parsed_title="Archived Matrix",
            parsed_year=2000,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
            trace_details={"feedType": "movie"},
            source_context=SourceContext(
                source_feed_id="archive",
                source_feed_name="Archive Display",
                feed_type="movie",
                feed_entry_id="archived-entry",
                torrent_url="https://example.test/archive/1",
                raw_title="Archived Matrix Release",
                source_published_at=self.now - datetime.timedelta(days=10),
                observed_at=self.now - datetime.timedelta(days=2),
            ),
            event_kind="source",
        )
        self.parse_log_repo.add(retry_log)
        reparse_scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({"the matrix": result_without_imdb}),
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.return_value = {
            0: {"title": "The Matrix", "year": 1999, "media_type": "movie"}
        }
        reparse_scanner.ai_matcher = mock_ai

        reparse_scanner.reparse_unfound_entries(
            section_timings={"omdb_api": 0.0, "parse_log_write": 0.0}
        )

        self.assertEqual(
            [title_id for title_id, _ in self.title_repo.list_all_ids_and_titles()],
            [expected_title_id],
        )
        self.assertIsNotNone(self.occ_repo.get(expected_title_id, retry_log.id))
        reparsed_occurrence = self.occ_repo.get(expected_title_id, retry_log.id)
        self.assertEqual(reparsed_occurrence.source_feed_id, "archive")
        self.assertEqual(reparsed_occurrence.feed_entry_id, "archived-entry")
        self.assertEqual(reparsed_occurrence.torrent_url, "https://example.test/archive/1")
        self.assertEqual(reparsed_occurrence.source_context, retry_log.source_context)
        reparsed_log = next(log for log in self.parse_log_repo.get_all() if log.id == retry_log.id)
        self.assertEqual(reparsed_log.source_context, retry_log.source_context)

    def test_section_timings_recorded(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "tests/fixtures/movies_feed.atom",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({"four rooms": self.valid_movie})
        scanner = self.create_scanner(config, omdb)
        run = scanner.run("run_timing")

        self.assertIn("feed_fetch", run.section_timings)
        self.assertIn("title_parse", run.section_timings)
        self.assertIn("cache_lookup", run.section_timings)
        self.assertIn("omdb_api", run.section_timings)
        self.assertIn("db_upsert", run.section_timings)
        self.assertIn("parse_log_write", run.section_timings)
        self.assertIn("prune_logs", run.section_timings)

        # Test log pruning
        old_time = self.now - datetime.timedelta(days=10)
        from movies_feed.models import ParseLog
        old_log = ParseLog(
            id="old_log_1",
            raw_title="Old Movie",
            feed_name="test_feed",
            parsed_successfully=True,
            parsed_title="Old Movie",
            parsed_year=2010,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=old_time
        )
        self.parse_log_repo.add(old_log)
        self.assertIsNotNone(self.parse_log_repo._store.get("old_log_1"))

        # Running scanner again should prune the 10-day-old log
        scanner.run("run_logs_2")
        self.assertIsNone(self.parse_log_repo._store.get("old_log_1"))


    def test_omdb_limit_and_caching(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "tests/fixtures/movies_feed.atom",
                "type": "movie"
            }
        }
        # First test hard limit
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({"four rooms": self.valid_movie})
        omdb.limit_reached_on = 2

        scanner = self.create_scanner(config, omdb)
        run = scanner.run("run1")
        
        self.assertEqual(run.omdb_requests, 2)
        self.assertIn("OMDb API limit reached", run.error_summary)

        # Now test caching and soft limit
        config.omdb_limit = 0 # No new requests allowed!
        omdb.limit_reached_on = -1
        scanner = self.create_scanner(config, omdb)
        run2 = scanner.run("run2")
        self.assertEqual(run2.omdb_requests, 0) # Should be 0 since limit is 0
        self.assertTrue(run2.cache_hits > 0) # First request should hit cache
        
    def test_filtering_and_partial_failures(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "tests/fixtures/movies_feed.atom",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=["Russia"],
            excluded_genres=["Horror"],
            omdb_limit=100
        )
        omdb = MockOmdbClient({
            "four rooms": self.filtered_movie,
            "neige": OmdbTransportError("timeout")
        })

        scanner = self.create_scanner(config, omdb)
        run = scanner.run("run1")
        
        self.assertEqual(run.titles_created, 0)
        self.assertEqual(run.status, "partial")
        self.assertTrue(any("OMDb Transport Error" in err for err in run.error_summary))

    def test_rss_documentary_series_preserves_source_type_and_range(self):
        raw_title = "Документални / Nature Watch / Сезон 2 [2022, США, WEB-DL 1080p]"
        result = make_series_result(
            title="Nature Watch",
            year=2018,
            broadcast_year="2018-",
            genres=["Documentary", "History"],
        )
        config = ScannerConfig(
            rss_feeds={
                "series_feed": {
                    "name": "series_feed",
                    "url": make_inline_feed(raw_title),
                    "type": "series",
                }
            },
            omdb_limit=10,
        )

        run = self.create_scanner(config, MockOmdbClient({"nature watch": result})).run("series_documentary")

        self.assertEqual(run.status, "succeeded")
        stored = self.title_repo.get(result.imdb_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.media_type, "series")
        self.assertEqual(stored.source_type, "series")
        self.assertEqual(stored.content_kind, "documentary")
        self.assertEqual(stored.broadcast_range.raw, "2018-")

    def test_rss_known_movie_feed_does_not_follow_series_result(self):
        raw_title = "Документални / Nature Watch / Сезон 2 [2022, США, WEB-DL 1080p]"
        result = make_series_result(title="Nature Watch", year=2018)
        config = ScannerConfig(
            rss_feeds={
                "movie_feed": {
                    "name": "movie_feed",
                    "url": make_inline_feed(raw_title),
                    "type": "movie",
                }
            },
            omdb_limit=10,
        )

        run = self.create_scanner(config, MockOmdbClient({"nature watch": result})).run("movie_type_authority")

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(self.title_repo.list_all(), [])
        mismatch = next(log for log in self.parse_log_repo.get_all() if log.ignore_reason == "media_type_mismatch")
        self.assertEqual(mismatch.trace_details["matchReasonCode"], "type_mismatch")
        self.assertEqual(mismatch.trace_details["expectedSourceType"], "movie")

    def test_rss_unknown_feed_infers_series_from_marker(self):
        raw_title = "Документални / Nature Watch / Сезон 2 [2022, США, WEB-DL 1080p]"
        result = make_series_result(title="Nature Watch", year=2018, broadcast_year="2018-")
        config = ScannerConfig(
            rss_feeds={
                "untyped_feed": {
                    "name": "untyped_feed",
                    "url": make_inline_feed(raw_title),
                    "type": None,
                }
            },
            omdb_limit=10,
        )

        run = self.create_scanner(config, MockOmdbClient({"nature watch": result})).run("unknown_feed_type")

        self.assertEqual(run.status, "succeeded")
        stored = self.title_repo.get(result.imdb_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.source_type, "series")

    def test_reparse_uses_stored_series_feed_type_and_accepts_later_season(self):
        result = make_series_result()
        source_log = ParseLog(
            id="unmapped-series",
            raw_title="Seasoned Show / Сезон 5 [2012]",
            feed_name="series_feed",
            parsed_successfully=True,
            parsed_title="Seasoned Show",
            parsed_year=2012,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
            trace_details={"feedType": "series"},
            source_context=SourceContext(
                source_feed_id="series-feed",
                source_feed_name="Series Feed",
                feed_type="series",
                feed_entry_id="unmapped-series-entry",
                torrent_url="https://example.test/series/unmapped",
                raw_title="Seasoned Show / Сезон 5 [2012]",
                source_published_at=self.now - datetime.timedelta(days=2),
                observed_at=self.now - datetime.timedelta(days=1),
            ),
            event_kind="source",
        )
        self.parse_log_repo.add(source_log)
        config = ScannerConfig(mode="reparse-unfound")
        scanner = self.create_scanner(config, MockOmdbClient({"seasoned show": result}))
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.return_value = {
            0: {"title": "Seasoned Show", "year": 2012, "media_type": "series"}
        }
        scanner.ai_matcher = mock_ai
        run = ScanRun(started_at=self.now, finished_at=None, status="running", trigger="local")
        timings = {"omdb_api": 0.0, "parse_log_write": 0.0}

        stats = scanner.reparse_unfound_entries(run=run, section_timings=timings)

        self.assertEqual(stats["reparsed_succeeded"], 1)
        extract_items = mock_ai.batch_extract_titles.call_args.args[0]
        self.assertEqual(extract_items[0]["feed_type"], "series")
        self.assertIsNotNone(self.title_repo.get(result.imdb_id))

    def test_reparse_resolves_retained_manual_mapping_before_gemini(self):
        source_context = SourceContext(
            source_feed_id="archive",
            source_feed_name="Archive Display",
            feed_type="movie",
            feed_entry_id="archived-entry",
            torrent_url="https://example.test/archive/1",
            raw_title="Archived Matrix Release",
            source_published_at=self.now - datetime.timedelta(days=10),
            observed_at=self.now - datetime.timedelta(days=2),
        )
        source_log = ParseLog(
            id=get_source_item_id("archive", "archived-entry", source_context.torrent_url),
            raw_title="Archived Matrix Release",
            feed_name="Archive",
            parsed_successfully=True,
            parsed_title="Archived Matrix",
            parsed_year=1999,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
            source_context=source_context,
            event_kind="source",
        )
        self.parse_log_repo.add(source_log)
        mapping = ManualMapping(
            id=source_log.id,
            raw_title="Unrelated mapping label",
            parsed_title="Archived Matrix",
            parsed_year=1999,
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
        )
        self.manual_mapping_repo.set(mapping)

        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({self.valid_movie.imdb_id: self.valid_movie}),
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.side_effect = AssertionError(
            "retained manual mappings must be resolved before Gemini"
        )
        scanner.ai_matcher = mock_ai

        run = scanner.run("retained_manual_mapping")

        title_id = get_title_id_v2(
            self.valid_movie.imdb_id,
            self.valid_movie.title,
            self.valid_movie.year,
            self.valid_movie.media_type,
        )
        occurrence_id = get_source_item_id(
            source_context.source_feed_id,
            source_context.feed_entry_id,
            source_context.torrent_url,
        )
        self.assertEqual(run.status, "succeeded")
        self.assertIsNotNone(self.title_repo.get(title_id))
        occurrence = self.occ_repo.get(title_id, occurrence_id)
        self.assertIsNotNone(occurrence)
        self.assertEqual(occurrence.source_context, source_context)
        self.assertEqual(occurrence.feed_entry_id, source_context.feed_entry_id)
        self.assertEqual(occurrence.torrent_url, source_context.torrent_url)
        resolved_log = next(
            log for log in self.parse_log_repo.get_all() if log.id == source_log.id
        )
        self.assertEqual(resolved_log.retry_state, "resolved")
        self.assertIsNotNone(resolved_log.resolution)
        self.assertEqual(resolved_log.resolution.title_id, title_id)
        self.assertEqual(resolved_log.resolution.occurrence_id, occurrence_id)
        self.assertEqual(resolved_log.attempt_count, 1)
        self.assertEqual(self.manual_mapping_repo.get_all(), [])

    def test_reparse_failure_updates_same_log_and_remains_retryable(self):
        source_log = self.make_retry_log(
            "retry-failure",
            "Missing Film (2020)",
            source_feed_id="archive",
            feed_entry_id="missing-film",
        )
        self.parse_log_repo.add(source_log)
        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({}),
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.return_value = {
            0: {"title": "Missing Film", "year": 2020, "media_type": "movie"}
        }
        scanner.ai_matcher = mock_ai
        run = ScanRun(started_at=self.now, finished_at=None, status="running", trigger="local")

        stats = scanner.reparse_unfound_entries(
            run=run,
            section_timings={"omdb_api": 0.0, "parse_log_write": 0.0},
        )

        logs = self.parse_log_repo.get_all()
        self.assertEqual([log.id for log in logs], [source_log.id])
        self.assertEqual(logs[0].retry_state, "retryable")
        self.assertEqual(logs[0].attempt_count, 1)
        self.assertIsNone(logs[0].resolution)
        self.assertEqual(stats["retried"], 1)
        self.assertEqual(stats["reparsed_succeeded"], 0)
        self.assertEqual(stats["reparsed_failed"], 1)
        self.assertEqual(self.title_repo.list_all(), [])

    def test_reparse_paginates_and_deduplicates_by_source_identity(self):
        for index in range(201):
            raw_title = "same title" if index % 2 else "Same Title"
            self.parse_log_repo.add(
                self.make_retry_log(
                    f"retry-page-{index}",
                    raw_title,
                    source_feed_id=f"feed-{index}",
                    feed_entry_id=f"entry-{index}",
                    processed_at=self.now - datetime.timedelta(minutes=index),
                )
            )

        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound", omdb_limit=10),
            MockOmdbClient({"the matrix": self.valid_movie}),
        )
        from unittest.mock import MagicMock, patch
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.side_effect = lambda items: {
            item["id"]: {
                "title": "The Matrix",
                "year": 1999,
                "media_type": "movie",
            }
            for item in items
        }
        scanner.ai_matcher = mock_ai
        run = ScanRun(started_at=self.now, finished_at=None, status="running", trigger="local")

        with patch("movies_feed.reparse_service.time.sleep") as sleep:
            stats = scanner.reparse_unfound_entries(
                run=run,
                section_timings={"omdb_api": 0.0, "parse_log_write": 0.0},
            )

        self.assertEqual(stats["unmapped_seen"], 201)
        self.assertEqual(stats["resolved"], 201)
        self.assertEqual(stats["reparsed_succeeded"], 201)
        self.assertEqual(stats["reparsed_failed"], 0)
        self.assertEqual(mock_ai.batch_extract_titles.call_count, 15)
        self.assertEqual(sleep.call_count, 14)
        occurrences = self.occ_repo.list_by_title(self.valid_movie.imdb_id)
        self.assertEqual(len(occurrences), 201)
        self.assertEqual(len(self.parse_log_repo.get_all()), 201)

    def test_reparse_skips_duplicate_logs_for_one_source_identity(self):
        source_log = self.make_retry_log(
            "primary-source-log",
            "Same Title",
            source_feed_id="archive",
            feed_entry_id="same-entry",
        )
        duplicate_log = replace(
            source_log,
            id="duplicate-source-log",
            raw_title="same title",
        )
        self.parse_log_repo.add(source_log)
        self.parse_log_repo.add(duplicate_log)
        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({"the matrix": self.valid_movie}),
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.return_value = {
            0: {"title": "The Matrix", "year": 1999, "media_type": "movie"}
        }
        scanner.ai_matcher = mock_ai

        stats = scanner.reparse_unfound_entries(
            section_timings={"omdb_api": 0.0, "parse_log_write": 0.0},
        )

        self.assertEqual(stats["resolved"], 1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(mock_ai.batch_extract_titles.call_count, 1)
        occurrences = self.occ_repo.list_by_title(self.valid_movie.imdb_id)
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(len(self.parse_log_repo.get_all()), 2)

    def test_reparse_catalog_write_failure_retries_original_log_and_keeps_mapping(self):
        source_log = self.make_retry_log(
            "write-failure",
            "Write Failure Film (2020)",
            source_feed_id="archive",
            feed_entry_id="write-failure-film",
        )
        self.parse_log_repo.add(source_log)
        mapping = ManualMapping(
            id=get_source_item_id(
                "archive",
                "write-failure-film",
                "https://example.test/archive/write-failure-film",
            ),
            raw_title="Write Failure Film",
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
        )
        self.manual_mapping_repo.set(mapping)

        def failing_upsert(title_id, occurrence_id, occurrence):
            raise RuntimeError("simulated occurrence write failure")

        self.occ_repo.upsert = failing_upsert
        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({self.valid_movie.imdb_id: self.valid_movie}),
        )

        stats = scanner.reparse_unfound_entries(
            section_timings={"omdb_api": 0.0, "parse_log_write": 0.0},
        )

        logs = self.parse_log_repo.get_all()
        self.assertEqual([log.id for log in logs], [source_log.id])
        self.assertEqual(logs[0].retry_state, "retryable")
        self.assertEqual(logs[0].attempt_count, 1)
        self.assertEqual(stats["retried"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual([item.id for item in self.manual_mapping_repo.get_all()], [mapping.id])

    def test_reparse_skips_legacy_retry_without_source_context(self):
        legacy_log = ParseLog(
            id="legacy-retry",
            raw_title="Legacy Film (2020)",
            feed_name="legacy-feed",
            parsed_successfully=True,
            parsed_title="Legacy Film",
            parsed_year=2020,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
            trace_details={"feedType": "movie"},
        )
        self.parse_log_repo.add(legacy_log)
        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({"legacy film": self.valid_movie}),
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.side_effect = AssertionError(
            "legacy logs without retained source context must not reach Gemini"
        )
        scanner.ai_matcher = mock_ai

        stats = scanner.reparse_unfound_entries(
            section_timings={"parse_log_write": 0.0},
        )

        stored_log = self.parse_log_repo.get_all()[0]
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["retried"], 0)
        self.assertEqual(stored_log.id, legacy_log.id)
        self.assertEqual(stored_log.retry_state, "retryable")
        self.assertEqual(stored_log.attempt_count, 1)
        self.assertIsNone(stored_log.source_context)
        self.assertEqual(self.title_repo.list_all(), [])

    def test_reparse_manual_mapping_respects_shared_budget(self):
        source_log = self.make_retry_log(
            "manual-budget-retry",
            "Budgeted Film (2020)",
            source_feed_id="archive",
            feed_entry_id="budgeted-film",
        )
        self.parse_log_repo.add(source_log)
        mapping = ManualMapping(
            id=get_source_item_id(
                "archive",
                "budgeted-film",
                "https://example.test/archive/budgeted-film",
            ),
            raw_title="Budgeted Film",
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
        )
        self.manual_mapping_repo.set(mapping)
        omdb = MockOmdbClient({self.valid_movie.imdb_id: self.valid_movie})
        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound", omdb_limit=0),
            omdb,
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.side_effect = AssertionError(
            "manual mapping should be attempted before Gemini even when the budget is exhausted"
        )
        scanner.ai_matcher = mock_ai

        stats = scanner.reparse_unfound_entries(
            section_timings={"parse_log_write": 0.0},
        )

        self.assertEqual(omdb.request_count, 0)
        self.assertEqual(stats["retried"], 1)
        self.assertEqual([item.id for item in self.manual_mapping_repo.get_all()], [mapping.id])
        stored_log = self.parse_log_repo.get_all()[0]
        self.assertEqual(stored_log.retry_state, "retryable")
        self.assertEqual(stored_log.attempt_count, 1)

    def test_reparse_terminal_filter_does_not_consume_manual_mapping(self):
        source_log = self.make_retry_log(
            "terminal-filter",
            "Filtered Film (1999)",
            source_feed_id="archive",
            feed_entry_id="filtered-film",
        )
        self.parse_log_repo.add(source_log)
        mapping = ManualMapping(
            id=get_source_item_id(
                "archive",
                "filtered-film",
                "https://example.test/archive/filtered-film",
            ),
            raw_title="Filtered Film",
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
        )
        self.manual_mapping_repo.set(mapping)
        scanner = self.create_scanner(
            ScannerConfig(
                mode="reparse-unfound",
                excluded_countries=["USA"],
            ),
            MockOmdbClient({self.valid_movie.imdb_id: self.valid_movie}),
        )

        stats = scanner.reparse_unfound_entries(
            section_timings={"omdb_api": 0.0, "parse_log_write": 0.0},
        )

        stored_log = self.parse_log_repo.get_all()[0]
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stored_log.retry_state, "terminal")
        self.assertIsNotNone(stored_log.resolution)
        self.assertEqual(stored_log.resolution.outcome, "terminal")
        self.assertEqual([item.id for item in self.manual_mapping_repo.get_all()], [mapping.id])
        self.assertEqual(self.title_repo.list_all(), [])

    def test_duplicate_entries_idempotent(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "tests/fixtures/movies_feed.atom",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({"four rooms": self.valid_movie})

        
        scanner = self.create_scanner(config, omdb)
        run1 = scanner.run("run1")
        titles1 = len(self.title_repo.list_all())
        occ1 = sum(len(self.occ_repo.list_by_title(t.imdb_id or "tt0133093")) for t in self.title_repo.list_all())
        
        run2 = scanner.run("run2")
        titles2 = len(self.title_repo.list_all())
        occ2 = sum(len(self.occ_repo.list_by_title(t.imdb_id or "tt0133093")) for t in self.title_repo.list_all())
        
        self.assertEqual(titles1, titles2)
        self.assertEqual(occ1, occ2)
        self.assertEqual(run2.titles_created, 0)
        self.assertEqual(run2.occurrences_created, 0)

    def test_session_caching_reduces_repository_get_calls(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "tests/fixtures/movies_feed.atom",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({"four rooms": self.valid_movie})

        # Track get calls
        cache_get_count = 0
        original_cache_get = self.cache_repo.get

        def counting_cache_get(key: str):
            nonlocal cache_get_count
            cache_get_count += 1
            return original_cache_get(key)

        self.cache_repo.get = counting_cache_get

        scanner = self.create_scanner(config, omdb)
        run1 = scanner.run("run1")

        entries_count = run1.entries_seen
        self.assertGreater(entries_count, 1)

        # Without session caching, cache_repo.get would be called once per entry.
        # With session caching, unique keys are cached in memory during run, so calls to repository are <= unique keys.
        self.assertLess(cache_get_count, entries_count)

    def test_manual_mapping_processed_and_deleted(self):
        # Pre-seed manual mapping
        mapping = ManualMapping(
            id="manual_1",
            raw_title="Unfound Title (2020)",
            imdb_id="tt0133093",
            created_at=self.now,
            parsed_title="Unfound Title",
            parsed_year=2020
        )
        self.manual_mapping_repo.set(mapping)

        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                    <channel>
                        <item>
                            <title>Unfound Title (2020) [1080p]</title>
                            <link>https://example.com/torrent/1</link>
                            <guid>guid1</guid>
                        </item>
                    </channel>
                </rss>""",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            trigger="manual",
            is_dry_run=False,
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({"tt0133093": self.valid_movie})
        scanner = self.create_scanner(config, omdb)
        
        run = scanner.run("run_manual_mapping")

        self.assertEqual(run.entries_seen, 1)
        self.assertEqual(run.titles_created, 1)
        # Verify manual mapping was deleted from repository after processing
        remaining_mappings = self.manual_mapping_repo.get_all()
        self.assertEqual(len(remaining_mappings), 0)

    def test_manual_mapping_does_not_call_or_delete_when_budget_is_exhausted(self):
        mapping = ManualMapping(
            id="manual_budget",
            raw_title="Budgeted Title (2020)",
            imdb_id="tt0133093",
            created_at=self.now,
            parsed_title="Budgeted Title",
            parsed_year=2020,
        )
        self.manual_mapping_repo.set(mapping)
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0"><channel><item>
                    <title>Budgeted Title (2020) [1080p]</title>
                    <link>https://example.com/torrent/budget</link>
                    <guid>budget-guid</guid>
                </item></channel></rss>""",
                "type": "movie",
            }
        }
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            mode="rss",
            omdb_limit=0,
        )
        omdb = MockOmdbClient({"tt0133093": self.valid_movie})

        run = self.create_scanner(config, omdb).run("manual_budget")

        self.assertEqual(run.status, "partial")
        self.assertEqual(run.omdb_requests, 0)
        self.assertEqual(omdb.request_count, 0)
        self.assertEqual([item.id for item in self.manual_mapping_repo.get_all()], [mapping.id])

    def test_run_budget_is_shared_from_rss_to_reparse_phase(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": make_inline_feed("The Matrix (1999) [1080p]"),
                "type": "movie",
            }
        }
        self.parse_log_repo.add(ParseLog(
            id="unmapped-after-rss",
            raw_title="Unmapped Film (2020)",
            feed_name="test_feed",
            parsed_successfully=True,
            parsed_title="Unmapped Film",
            parsed_year=2020,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
            trace_details={"feedType": "movie"},
            source_context=SourceContext(
                source_feed_id="test-feed",
                source_feed_name="test_feed",
                feed_type="movie",
                feed_entry_id="unmapped-after-rss-entry",
                torrent_url="https://example.test/unmapped-after-rss",
                raw_title="Unmapped Film (2020)",
                source_published_at=self.now - datetime.timedelta(days=2),
                observed_at=self.now - datetime.timedelta(days=1),
            ),
            event_kind="source",
        ))
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            mode="all",
            omdb_limit=1,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_recheck_matches.return_value = {0: {"is_valid_match": True}}
        mock_ai.batch_extract_titles.return_value = {
            0: {"title": "Unmapped Film", "year": 2020, "media_type": "movie"}
        }
        scanner.ai_matcher = mock_ai

        run = scanner.run("shared_budget")

        self.assertEqual(run.status, "partial")
        self.assertEqual(run.omdb_requests, 1)
        self.assertEqual(omdb.request_count, 1)
        self.assertTrue(scanner.metadata_resolver.quota_exhausted)

    def test_parse_error_captured_in_parse_logs(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                    <channel>
                        <item>
                            <title></title>
                            <link>https://example.com/torrent/empty</link>
                            <guid>guid_empty</guid>
                        </item>
                    </channel>
                </rss>""",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            trigger="manual",
            is_dry_run=False,
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)
        
        run = scanner.run("run_empty_title")
        self.assertEqual(run.ignored_entries, 1)
        
        logs = self.parse_log_repo.get_all()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].ignore_reason, "empty_title")
        self.assertFalse(logs[0].parsed_successfully)

    def test_parser_exception_logged_in_parse_logs(self):
        from unittest.mock import patch

        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                    <channel>
                        <item>
                            <title>Malformed Title (2022)</title>
                            <link>https://example.com/torrent/err</link>
                            <guid>guid_err</guid>
                        </item>
                    </channel>
                </rss>""",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            trigger="manual",
            is_dry_run=False,
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)

        with patch("movies_feed.scanner.parse_rutracker_title", side_effect=ValueError("Syntax parsing crash")):
            run = scanner.run("run_parse_err")

        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(run.error_count, 1)
        logs = self.parse_log_repo.get_all()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].ignore_reason, "parse_error")
        self.assertIn("Syntax parsing crash", logs[0].error_message or "")

    def test_parse_log_trace_details_and_diagnostics(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "tests/fixtures/movies_feed.atom",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=["Russia"],
            excluded_genres=["Horror"],
            omdb_limit=100
        )
        omdb = MockOmdbClient({
            "four rooms": self.filtered_movie,
        })

        scanner = self.create_scanner(config, omdb)
        scanner.run("run_trace_test")

        logs = scanner.parse_log_repo.get_all()
        self.assertTrue(len(logs) > 0)
        
        # Check that trace_details exist
        logs_with_trace = [l for l in logs if l.trace_details is not None]
        self.assertTrue(len(logs_with_trace) > 0)
        
        # Find the filtered movie log (Horror genre excluded)
        filtered_logs = [l for l in logs if l.ignore_reason == "excluded_country_or_genre"]
        if filtered_logs:
            f_log = filtered_logs[0]
            self.assertIn("Филтриран жанр", f_log.error_message)
            self.assertIsNotNone(f_log.trace_details)
            self.assertEqual(f_log.trace_details.get("decision"), "ignored_excluded_country_or_genre")
            self.assertEqual(f_log.trace_details.get("parsedTitle"), "Four Rooms")

    def test_single_pass_parsing_and_force_days_skips_parse(self):
        from unittest.mock import patch
        from movies_feed.rutracker_parser import parse_rutracker_title as real_parse

        old_date_str = (self.now - datetime.timedelta(days=10)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        new_date_str = (self.now - datetime.timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")

        feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Стар Филм / Old Movie [1990, САЩ, BDRip 1080p]</title>
                    <link>https://example.com/torrent/old</link>
                    <guid>guid_old</guid>
                    <pubDate>{old_date_str}</pubDate>
                </item>
                <item>
                    <title>Матрица / The Matrix (Вачовски) [1999, САЩ, фантастика, BDRip 1080p]</title>
                    <link>https://example.com/torrent/new</link>
                    <guid>guid_new</guid>
                    <pubDate>{new_date_str}</pubDate>
                </item>
            </channel>
        </rss>"""

        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            force_days=3,
            omdb_limit=10,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)

        parse_calls = []
        def parse_spy(raw, **kwargs):
            parse_calls.append(raw)
            return real_parse(raw, **kwargs)

        with patch("movies_feed.scanner.parse_rutracker_title", side_effect=parse_spy):
            run = scanner.run("run_single_pass")

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.entries_seen, 2)
        self.assertEqual(run.ignored_entries, 1) # old movie ignored
        self.assertEqual(run.titles_created, 1)

        # parse_rutracker_title must be called exactly ONCE for the whole feed, and NOT called for old movie!
        self.assertEqual(len(parse_calls), 1)
        self.assertEqual(parse_calls[0], "Матрица / The Matrix (Вачовски) [1999, САЩ, фантастика, BDRip 1080p]")

    def test_same_parsed_context_used_for_prefetch_and_processing(self):
        raw_title = "Матрица / The Matrix (Вачовски) [1999, САЩ, фантастика, BDRip 1080p]"
        feed_xml = make_inline_feed(raw_title)
        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            omdb_limit=10,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)

        prefetch_calls = []
        original_prefetch = scanner.metadata_resolver.prefetch
        def prefetch_spy(requests, section_timings=None):
            prefetch_calls.extend(requests)
            return original_prefetch(requests, section_timings=section_timings)

        scanner.metadata_resolver.prefetch = prefetch_spy

        run = scanner.run("run_prefetch_reuse")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.titles_created, 1)
        # Prefetch received exactly the parsed entry title and year
        self.assertEqual(len(prefetch_calls), 1)
        self.assertEqual(prefetch_calls[0][0], "The Matrix")
        self.assertEqual(prefetch_calls[0][1], 1999)

    def test_parse_only_isolation_makes_no_api_or_db_writes(self):
        feed_xml = make_inline_feed("The Matrix (1999) [1080p]")
        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            is_parse_only=True,
            mode="rss",
            omdb_limit=10,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)

        run = scanner.run("run_parse_only")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.entries_seen, 1)
        # 0 OMDb requests
        self.assertEqual(omdb.request_count, 0)
        self.assertEqual(run.omdb_requests, 0)
        # 0 DB writes
        self.assertEqual(self.title_repo.list_all(), [])
        self.assertEqual(self.parse_log_repo.get_all(), [])

    def test_phase_boundaries_metrics_and_counters(self):
        feed_xml = make_inline_feed("The Matrix (1999) [1080p]")
        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            mode="all",
            omdb_limit=10,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)

        run = scanner.run("run_phase_metrics")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.titles_created, 1)
        self.assertEqual(run.occurrences_created, 1)
        self.assertEqual(run.entries_seen, 1)
        self.assertIn("rss", run.phase_metrics)
        self.assertIn("recheck_existing", run.phase_metrics)
        self.assertIn("reparse_unfound", run.phase_metrics)
        self.assertIn("apply_proposals", run.phase_metrics)

        rss_metrics = run.phase_metrics["rss"]
        self.assertEqual(rss_metrics["status"], "succeeded")
        self.assertEqual(rss_metrics["feeds_processed"], 1)
        self.assertEqual(rss_metrics["entries_seen"], 1)
        self.assertEqual(rss_metrics["titles_created"], 1)
        self.assertIsNotNone(rss_metrics["started_at"])
        self.assertIsNotNone(rss_metrics["finished_at"])

        recheck_metrics = run.phase_metrics["recheck_existing"]
        self.assertEqual(recheck_metrics["status"], "succeeded")

    def test_mode_all_phase_isolation_prevents_same_run_auditing_unless_allowed(self):
        feed_xml = make_inline_feed("The Matrix (1999) [1080p]")
        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            mode="all",
            omdb_limit=10,
            allow_same_run_chaining=False,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)

        recheck_called_with_ids = []

        def spy_recheck(*args, **kwargs):
            excluded = kwargs.get("excluded_title_ids")
            if excluded:
                recheck_called_with_ids.extend(excluded)
            return {
                "titles_checked": 0,
                "mismatches_found": 0,
                "repaired": 0,
                "removed": 0,
                "validated": 0,
                "needs_review": 0,
                "ai_failures": 0,
                "omdb_failures": 0,
                "clusters_checked": 0,
                "valid_clusters": 0,
                "proposals": 0,
                "retryable_failures": 0,
                "orphans": 0,
            }

        scanner.recheck_existing_titles = spy_recheck

        run = scanner.run("run_isolation")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.titles_created, 1)
        # Verify that newly created title ID was in excluded_title_ids
        self.assertTrue(len(recheck_called_with_ids) > 0)
        created_title_id = list(self.title_repo._store.keys())[0]
        self.assertIn(created_title_id, recheck_called_with_ids)

        # Now test with allow_same_run_chaining=True
        self.title_repo._store.clear()
        self.occ_repo._store.clear()
        recheck_called_with_ids.clear()

        config_chained = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            mode="all",
            omdb_limit=10,
            allow_same_run_chaining=True,
        )
        scanner_chained = self.create_scanner(config_chained, omdb)
        scanner_chained.recheck_existing_titles = spy_recheck

        run_chained = scanner_chained.run("run_chained")
        self.assertEqual(run_chained.status, "succeeded")
        self.assertEqual(len(recheck_called_with_ids), 0)

    def test_scan_run_status_partial_on_error(self):
        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": "invalid://not-found",
                    "type": "movie",
                }
            },
            mode="rss",
            omdb_limit=10,
        )
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)

        run = scanner.run("run_error_status")
        self.assertEqual(run.status, "partial")
        self.assertGreater(run.error_count, 0)




