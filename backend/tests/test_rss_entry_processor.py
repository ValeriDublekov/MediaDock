import datetime
import unittest
from types import SimpleNamespace
from typing import Optional

try:
    from . import _test_stubs
    from .scanner_test_support import (
        MockOmdbClient,
        ScannerTestMixin,
        make_series_result,
    )
except ImportError:
    import _test_stubs
    from scanner_test_support import (
        MockOmdbClient,
        ScannerTestMixin,
        make_series_result,
    )

from movies_feed.ids import get_source_item_id, get_title_id_v2
from movies_feed.models import ManualMapping, ScanRun, SourceContext, Title
from movies_feed.omdb_client import OmdbLimitReachedError, OmdbTransportError
from movies_feed.rss_ingestion import ParsedEntryContext
from movies_feed.rutracker_parser import ParsedTitle
from movies_feed.scan_contracts import FeedDefinition
from movies_feed.scanner import ScannerConfig


class TestRssEntryProcessor(ScannerTestMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.movie_feed = FeedDefinition(
            id="movie-feed",
            name="Movie Feed",
            url=None,
            type="movie",
        )
        self.series_feed = FeedDefinition(
            id="series-feed",
            name="Series Feed",
            url=None,
            type="series",
        )

    def _build_processor(self, responses=None, **config_overrides):
        config_values = {
            "rss_feeds": {},
            "omdb_limit": 10,
        }
        config_values.update(config_overrides)
        omdb = MockOmdbClient(responses or {})
        scanner = self.scanner_builder.build(
            config=ScannerConfig(**config_values),
            omdb_client=omdb,
        )
        return scanner.rss_ingestion, omdb

    def _context(
        self,
        *,
        raw_title: str = "The Matrix (1999) [1080p]",
        parsed_title: Optional[str] = "The Matrix",
        parsed_year: Optional[str] = "1999",
        parsed_is_series: bool = False,
        confidence: float = 1.0,
        reasons=(),
        lookup_year: Optional[int] = 1999,
        expected_source_type: Optional[str] = "movie",
        parse_error: Optional[str] = None,
        is_ignored_by_date: bool = False,
        entry_id: str = "entry-1",
        torrent_url: str = "https://example.test/torrent/entry-1",
        source_published_at: Optional[datetime.datetime] = None,
        feed: Optional[FeedDefinition] = None,
        feed_order: int = 0,
        entry_order: int = 0,
    ) -> ParsedEntryContext:
        selected_feed = feed or self.movie_feed
        entry = SimpleNamespace(
            id=entry_id,
            link=torrent_url,
            title=raw_title,
        )
        source_context = SourceContext(
            source_feed_id=selected_feed.id,
            source_feed_name=selected_feed.name,
            feed_type=selected_feed.type or "unknown",
            feed_entry_id=entry_id,
            torrent_url=torrent_url,
            raw_title=raw_title,
            source_published_at=source_published_at,
            observed_at=self.now,
        )
        parsed = (
            ParsedTitle(
                title=parsed_title,
                year=parsed_year,
                is_series=parsed_is_series,
                quality="1080p",
                rip_type="WEB-DL",
                confidence=confidence,
                reasons=reasons,
            )
            if parsed_title is not None
            else None
        )
        return ParsedEntryContext(
            entry=entry,
            source_context=source_context,
            is_ignored_by_date=is_ignored_by_date,
            raw_title=raw_title,
            parsed=parsed,
            lookup_year=lookup_year,
            expected_source_type=expected_source_type,
            parse_error=parse_error,
            feed_order=feed_order,
            entry_order=entry_order,
        )

    def _new_run(self) -> ScanRun:
        return ScanRun(
            started_at=self.now,
            finished_at=None,
            status="running",
            trigger="manual",
        )

    def _pending_log(self, processor):
        self.assertEqual(len(processor.write_buffer.pending_parse_logs), 1)
        return processor.write_buffer.pending_parse_logs[0]

    def _assert_no_catalog_writes(self, processor):
        self.assertEqual(processor.write_buffer.pending_titles, {})
        self.assertEqual(processor.write_buffer.pending_occurrences, {})
        self.assertEqual(self.title_repo.list_all(), [])
        self.assertEqual(self.occ_repo._store, {})

    def test_ignored_by_date_exits_without_logging_or_lookup(self):
        processor, omdb = self._build_processor({"the matrix": self.valid_movie})
        context = self._context(
            is_ignored_by_date=True,
            source_published_at=self.now - datetime.timedelta(days=10),
        )
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(omdb.request_count, 0)
        self.assertEqual(processor.write_buffer.pending_parse_logs, [])
        self._assert_no_catalog_writes(processor)

    def test_empty_title_exit_logs_ignored_entry_without_lookup(self):
        processor, omdb = self._build_processor({"the matrix": self.valid_movie})
        context = self._context(raw_title="", parsed_title=None)
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        log = self._pending_log(processor)
        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(omdb.request_count, 0)
        self.assertFalse(log.parsed_successfully)
        self.assertEqual(log.omdb_status, "not_parsed")
        self.assertEqual(log.ignore_reason, "empty_title")
        self._assert_no_catalog_writes(processor)

    def test_parser_failure_logs_parse_error_without_lookup(self):
        processor, omdb = self._build_processor({"the matrix": self.valid_movie})
        context = self._context(
            raw_title="Malformed Matrix (1999)",
            parsed_title="",
            parsed_year=None,
            lookup_year=None,
            parse_error="Syntax parsing crash",
        )
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        log = self._pending_log(processor)
        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(run.error_count, 1)
        self.assertIn("Syntax parsing crash", run.error_summary[0])
        self.assertEqual(log.ignore_reason, "parse_error")
        self.assertIn("Syntax parsing crash", log.error_message or "")
        self.assertEqual(omdb.request_count, 0)
        self._assert_no_catalog_writes(processor)

    def test_low_confidence_parse_logs_rejection_without_lookup(self):
        processor, omdb = self._build_processor({"the matrix": self.valid_movie})
        context = self._context(
            confidence=0.6,
            reasons=("ambiguous_title", "weak_year_signal"),
        )
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        log = self._pending_log(processor)
        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(log.ignore_reason, "low_confidence_parse:ambiguous_title")
        self.assertEqual(log.omdb_status, "not_parsed")
        self.assertEqual(log.trace_details["parseConfidence"], 0.6)
        self.assertEqual(omdb.request_count, 0)
        self._assert_no_catalog_writes(processor)

    def test_parse_only_isolation_makes_no_api_or_db_writes(self):
        processor, omdb = self._build_processor(
            {"the matrix": self.valid_movie},
            is_parse_only=True,
            mode="rss",
        )
        context = self._context()
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        self.assertEqual(omdb.request_count, 0)
        self.assertEqual(run.omdb_requests, 0)
        self.assertEqual(run.ignored_entries, 0)
        self.assertEqual(len(processor.write_buffer.written_parse_log_ids), 1)
        self.assertEqual(len(processor.write_buffer.pending_parse_logs), 1)
        self.assertEqual(processor.write_buffer.pending_parse_logs[0].ignore_reason, "parse_only")
        self.assertEqual(self.parse_log_repo.get_all(), [])
        self._assert_no_catalog_writes(processor)
        self.assertEqual(processor.snapshot_collector.build_items(), [])

    def test_confirmed_not_found_logs_terminal_metadata_outcome(self):
        processor, omdb = self._build_processor()
        context = self._context(
            raw_title="Unlisted Film (2024) [1080p]",
            parsed_title="Unlisted Film",
            parsed_year="2024",
            lookup_year=2024,
        )
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        log = self._pending_log(processor)
        self.assertEqual(omdb.request_count, 1)
        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(run.error_count, 0)
        self.assertEqual(log.omdb_status, "not_found")
        self.assertEqual(log.ignore_reason, "omdb_not_found")
        self._assert_no_catalog_writes(processor)

    def test_quota_exhausted_logs_outcome_and_stops_entry(self):
        processor, omdb = self._build_processor({"the matrix": self.valid_movie})
        omdb.limit_reached_on = 1
        context = self._context()
        run = self._new_run()

        with self.assertRaises(OmdbLimitReachedError):
            processor._process_entry(context, self.movie_feed, run)

        log = self._pending_log(processor)
        self.assertEqual(omdb.request_count, 1)
        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(run.error_count, 1)
        self.assertIn("OMDb phase incomplete during rss", run.error_summary)
        self.assertEqual(log.omdb_status, "skipped")
        self.assertEqual(log.ignore_reason, "omdb_limit_reached")
        self._assert_no_catalog_writes(processor)

    def test_transport_error_logs_outcome_and_phase_errors(self):
        processor, omdb = self._build_processor(
            {"the matrix": OmdbTransportError("timeout")}
        )
        context = self._context()
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        log = self._pending_log(processor)
        self.assertEqual(omdb.request_count, 1)
        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(run.error_count, 2)
        self.assertIn("OMDb phase incomplete during rss", run.error_summary)
        self.assertTrue(any("OMDb Transport Error: timeout" in error for error in run.error_summary))
        self.assertEqual(log.omdb_status, "error")
        self.assertEqual(log.ignore_reason, "omdb_error")
        self._assert_no_catalog_writes(processor)

    def test_rejected_media_type_match_is_logged_without_staging(self):
        processor, omdb = self._build_processor(
            {"seasoned show": make_series_result()}
        )
        context = self._context(
            raw_title="Seasoned Show (2012) [1080p]",
            parsed_title="Seasoned Show",
            parsed_year="2012",
            lookup_year=2012,
        )
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        log = self._pending_log(processor)
        self.assertEqual(omdb.request_count, 1)
        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(log.ignore_reason, "media_type_mismatch")
        self.assertEqual(log.trace_details["matchReasonCode"], "type_mismatch")
        self._assert_no_catalog_writes(processor)

    def test_rejected_year_match_is_logged_without_staging(self):
        processor, omdb = self._build_processor({"the matrix": self.valid_movie})
        context = self._context(
            raw_title="The Matrix (2005) [1080p]",
            parsed_year="2005",
            lookup_year=2005,
        )
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        log = self._pending_log(processor)
        self.assertEqual(omdb.request_count, 1)
        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(log.ignore_reason, "year_mismatch")
        self.assertEqual(log.trace_details["matchReasonCode"], "movie_release_year_mismatch")
        self._assert_no_catalog_writes(processor)

    def test_rejected_filter_match_is_logged_without_staging(self):
        processor, omdb = self._build_processor(
            {"filtered movie": self.filtered_movie},
            excluded_countries=["Russia"],
            excluded_genres=["Horror"],
        )
        context = self._context(
            raw_title="Filtered Movie (2000) [1080p]",
            parsed_title="Filtered Movie",
            parsed_year="2000",
            lookup_year=2000,
        )
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        log = self._pending_log(processor)
        self.assertEqual(omdb.request_count, 1)
        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(log.ignore_reason, "excluded_country_or_genre")
        self.assertIn(
            log.trace_details["matchReasonCode"],
            ("excluded_country", "excluded_genre"),
        )
        self._assert_no_catalog_writes(processor)

    def test_existing_accepted_title_is_recorded_in_snapshot(self):
        title_id = get_title_id_v2(
            self.valid_movie.imdb_id,
            self.valid_movie.title,
            self.valid_movie.year,
            "movie",
        )
        self.title_repo.upsert(
            title_id,
            Title(
                title=self.valid_movie.title,
                normalized_title="the matrix",
                year=self.valid_movie.year,
                media_type="movie",
                first_seen_at=self.now,
                last_seen_at=self.now,
                updated_at=self.now,
                imdb_id=self.valid_movie.imdb_id,
                source_type="movie",
            ),
        )
        processor, omdb = self._build_processor({"the matrix": self.valid_movie})
        context = self._context()
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        self.assertEqual(omdb.request_count, 1)
        self.assertEqual(run.titles_created, 0)
        self.assertEqual(run.titles_updated, 1)
        self.assertEqual(run.occurrences_created, 1)
        self.assertIn(title_id, processor.write_buffer.pending_titles)
        self.assertEqual(
            processor.snapshot_collector.build_items()[0].title_id,
            title_id,
        )

    def test_new_accepted_title_is_staged_and_logged(self):
        processor, omdb = self._build_processor({"the matrix": self.valid_movie})
        context = self._context()
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        title_id = get_title_id_v2(
            self.valid_movie.imdb_id,
            self.valid_movie.title,
            self.valid_movie.year,
            "movie",
        )
        occurrence_id = get_source_item_id(
            self.movie_feed.id,
            context.entry.id,
            context.entry.link,
        )
        log = self._pending_log(processor)
        self.assertEqual(omdb.request_count, 1)
        self.assertEqual(run.titles_created, 1)
        self.assertEqual(run.occurrences_created, 1)
        self.assertIn(title_id, processor.write_buffer.pending_titles)
        self.assertIn(
            (title_id, occurrence_id),
            processor.write_buffer.pending_occurrences,
        )
        self.assertFalse(log.ignored)
        self.assertEqual(log.omdb_status, "found")

    def test_accepted_movie_and_series_entries_record_snapshot_candidates(self):
        series_result = make_series_result()
        processor, omdb = self._build_processor(
            {
                "the matrix": self.valid_movie,
                "seasoned show": series_result,
            }
        )
        movie_context = self._context(feed_order=2)
        series_context = self._context(
            raw_title="Seasoned Show (2012) [1080p]",
            parsed_title="Seasoned Show",
            parsed_year="2012",
            parsed_is_series=True,
            lookup_year=2012,
            expected_source_type="series",
            entry_id="series-entry",
            torrent_url="https://example.test/torrent/series-entry",
            feed=self.series_feed,
            feed_order=0,
        )
        run = self._new_run()

        processor._process_entry(movie_context, self.movie_feed, run)
        processor._process_entry(series_context, self.series_feed, run)

        movie_id = get_title_id_v2(
            self.valid_movie.imdb_id,
            self.valid_movie.title,
            self.valid_movie.year,
            "movie",
        )
        series_id = get_title_id_v2(
            series_result.imdb_id,
            series_result.title,
            series_result.year,
            "series",
        )
        items = processor.snapshot_collector.build_items()
        self.assertEqual(omdb.request_count, 2)
        self.assertEqual([item.title_id for item in items], [movie_id, series_id])
        self.assertEqual([item.source_type for item in items], ["movie", "series"])

    def test_manual_mapping_is_looked_up_and_consumed_after_staging(self):
        raw_title = "Matrix Alias (1999) [1080p]"
        entry_id = "mapped-entry"
        torrent_url = "https://example.test/torrent/mapped-entry"
        mapping_id = get_source_item_id(self.movie_feed.id, entry_id, torrent_url)
        mapping = ManualMapping(
            id=mapping_id,
            raw_title=raw_title,
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
            parsed_title="The Matrix",
            parsed_year=1999,
        )
        self.manual_mapping_repo.set(mapping)
        processor, omdb = self._build_processor(
            {self.valid_movie.imdb_id: self.valid_movie}
        )
        processor.write_buffer.load_manual_mappings()
        context = self._context(
            raw_title=raw_title,
            entry_id=entry_id,
            torrent_url=torrent_url,
        )
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        self.assertEqual(omdb.request_count, 1)
        self.assertEqual(run.titles_created, 1)
        self.assertIn(mapping_id, processor.write_buffer.pending_manual_mappings)
        processor.write_buffer.flush_pending_db_upserts()
        self.assertEqual(self.manual_mapping_repo.get_all(), [])
        self.assertEqual(processor.write_buffer.pending_manual_mappings, {})

    def test_dry_run_counts_acceptance_without_staged_catalog_writes(self):
        processor, omdb = self._build_processor(
            {"the matrix": self.valid_movie},
            is_dry_run=True,
        )
        context = self._context()
        run = self._new_run()

        processor._process_entry(context, self.movie_feed, run)

        self.assertEqual(omdb.request_count, 1)
        self.assertEqual(run.titles_created, 1)
        self.assertEqual(run.occurrences_created, 1)
        self._assert_no_catalog_writes(processor)
        self.assertEqual(processor.write_buffer.pending_parse_logs, [])
        self.assertEqual(len(processor.snapshot_collector.build_items()), 1)


if __name__ == "__main__":
    unittest.main()