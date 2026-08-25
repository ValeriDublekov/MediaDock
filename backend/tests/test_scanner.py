import datetime
import unittest
from pathlib import Path
from typing import Any, Dict

from movies_feed.models import ManualMapping, OmdbCacheEntry, Title, Occurrence, ScanRun
from movies_feed.omdb_client import OmdbMovieResult, OmdbLimitReachedError, OmdbTransportError, OmdbNoMatchError, OmdbClient, HttpTransport
from movies_feed.repository import (
    FakeTitleRepository,
    FakeOccurrenceRepository,
    FakeOmdbCacheRepository,
    FakeScanRunRepository,
    FakeParseLogRepository,
    FakeManualMappingRepository,
)
from movies_feed.scanner import ScannerConfig, ScannerService
from movies_feed.feed_fetcher import FeedFetcher


class StaticTestFeedFetcher:
    def __init__(self):
        self.validator = FeedFetcher(
            allowed_hosts={"feed.example.test"},
            dns_resolver=lambda host, port: ["8.8.8.8"],
        )

    def fetch(self, url: str) -> bytes:
        if url.lstrip().startswith("<"):
            return url.encode("utf-8")
        return Path(url).read_bytes()

    def fetch_file(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def validate_parsed_feed(self, feed: Any):
        return self.validator.validate_parsed_feed(feed)

class MockOmdbClient(OmdbClient):
    def __init__(self, responses: Dict[str, Any]):
        super().__init__(api_key="mock")
        self.responses = responses
        self.request_count = 0
        self.limit_reached_on = -1

    def get_movie_info(self, title: str, year: str = None, media_type: str = None) -> OmdbMovieResult:
        self.request_count += 1
        if self.limit_reached_on > 0 and self.request_count >= self.limit_reached_on:
            raise OmdbLimitReachedError("limit reached")
        
        for k, v in self.responses.items():
            if k.lower() in title.lower():
                if isinstance(v, Exception):
                    raise v
                return v
        
        raise OmdbNoMatchError("Not found")

    def get_by_imdb_id(self, imdb_id: str) -> OmdbMovieResult:
        self.request_count += 1
        for k, v in self.responses.items():
            if k.lower() == imdb_id.lower():
                if isinstance(v, Exception):
                    raise v
                return v
        raise OmdbNoMatchError(f"IMDb ID {imdb_id} not found")

    def _normalize_payload(self, payload: Dict[str, Any]) -> OmdbMovieResult:
        return OmdbMovieResult(
            title=payload.get("Title", ""),
            year=int(payload.get("Year")) if payload.get("Year") else None,
            imdb_id=payload.get("imdbID"),
            media_type="movie",
            rating=None, votes=None, metascore=None,
            genres=payload.get("Genre", "").split(", "),
            countries=payload.get("Country", "").split(", "),
            director=None, plot=None, poster_url=None,
            runtime=None, awards=None, box_office=None, ratings=[], raw_payload=payload
        )

class TestScanner(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime.now(datetime.timezone.utc)
        self.title_repo = FakeTitleRepository()
        self.occ_repo = FakeOccurrenceRepository()
        self.cache_repo = FakeOmdbCacheRepository()
        self.run_repo = FakeScanRunRepository()
        self.parse_log_repo = FakeParseLogRepository()
        self.manual_mapping_repo = FakeManualMappingRepository()

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
        return ScannerService(
            config=config,
            omdb_client=omdb_client,
            title_repo=self.title_repo,
            occurrence_repo=self.occ_repo,
            cache_repo=self.cache_repo,
            run_repo=self.run_repo,
            parse_log_repo=self.parse_log_repo,
            manual_mapping_repo=self.manual_mapping_repo,
            now=self.now,
            feed_fetcher=StaticTestFeedFetcher(),
        )

    def add_recheck_occurrence(self, title_id: str, raw_title: str = "Stored Film 2020 1080p") -> None:
        self.occ_repo.upsert(
            title_id,
            f"{title_id}-occurrence",
            Occurrence(
                source_feed_id="test-feed",
                source_feed_name="Test Feed",
                feed_entry_id=f"{title_id}-entry",
                torrent_url=f"https://example.test/{title_id}",
                raw_title=raw_title,
                quality="1080p",
                rip_type="WEB-DL",
                first_seen_at=self.now,
                last_seen_at=self.now,
            ),
        )

    def seed_recheck_title(self, title_id: str = "t1", title: str = "Stored Film", year: int = 2020) -> Title:
        title_record = Title(
            title=title,
            normalized_title=title.lower(),
            year=year,
            media_type="movie",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
            ai_validated=False,
        )
        self.title_repo.upsert(title_id, title_record)
        self.add_recheck_occurrence(title_id, f"{title} {year} 1080p")
        return title_record

    def make_recheck_scanner(
        self,
        ai_response: Dict[int, Dict[str, Any]],
        omdb_client: OmdbClient = None,
        is_dry_run: bool = False,
    ):
        config = ScannerConfig(
            trigger="manual",
            mode="recheck-existing",
            is_dry_run=is_dry_run,
        )
        scanner = self.create_scanner(config, omdb_client or MockOmdbClient({}))
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_recheck_matches.return_value = ai_response
        scanner.ai_matcher = mock_ai
        return scanner, mock_ai

    def test_parse_logs_creation_and_pruning(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "backend/tests/fixtures/movies_feed.atom",
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

    def test_section_timings_recorded(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "backend/tests/fixtures/movies_feed.atom",
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
                "url": "backend/tests/fixtures/movies_feed.atom",
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
                "url": "backend/tests/fixtures/movies_feed.atom",
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

    def test_duplicate_entries_idempotent(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "backend/tests/fixtures/movies_feed.atom",
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
                "url": "backend/tests/fixtures/movies_feed.atom",
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

    def test_recheck_skips_ai_validated_titles_and_persists_flag(self):
        t1 = Title(
            title="Matrix", normalized_title="matrix", year=1999, media_type="movie",
            first_seen_at=self.now, last_seen_at=self.now, updated_at=self.now,
            ai_validated=True
        )
        t2 = Title(
            title="Inception", normalized_title="inception", year=2010, media_type="movie",
            first_seen_at=self.now, last_seen_at=self.now, updated_at=self.now,
            ai_validated=False
        )
        self.title_repo.upsert("t1", t1)
        self.title_repo.upsert("t2", t2)
        self.add_recheck_occurrence("t2", "Inception 2010 1080p")

        config = ScannerConfig(trigger="manual", mode="recheck-existing")
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)

        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_recheck_matches.return_value = {0: {"is_valid_match": True}}
        scanner.ai_matcher = mock_ai

        res = scanner._recheck_existing_titles()
        # Should only check 1 title (t2), because t1 was already ai_validated=True
        self.assertEqual(res["titles_checked"], 1)
        # Verify t2 is now marked ai_validated=True in repository
        updated_t2 = self.title_repo.get("t2")
        self.assertTrue(updated_t2.ai_validated)

    def test_recheck_stops_on_first_ai_error(self):
        t1 = Title(
            title="Film 1", normalized_title="film 1", year=2020, media_type="movie",
            first_seen_at=self.now, last_seen_at=self.now, updated_at=self.now,
        )
        t2 = Title(
            title="Film 2", normalized_title="film 2", year=2021, media_type="movie",
            first_seen_at=self.now, last_seen_at=self.now, updated_at=self.now,
        )
        self.title_repo.upsert("t1", t1)
        self.title_repo.upsert("t2", t2)
        self.add_recheck_occurrence("t1", "Film 1 2020 1080p")
        self.add_recheck_occurrence("t2", "Film 2 2021 1080p")

        config = ScannerConfig(trigger="manual", mode="recheck-existing")
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)

        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        # AI returns empty dict (simulating 429 error or failure)
        mock_ai.batch_recheck_matches.return_value = {}
        scanner.ai_matcher = mock_ai

        res = scanner._recheck_existing_titles()
        # On batch 1 failure, it should stop immediately
        self.assertEqual(mock_ai.batch_recheck_matches.call_count, 1)

    def test_recheck_audit_days_filtering(self):
        old_date = self.now - datetime.timedelta(days=10)
        recent_date = self.now - datetime.timedelta(days=1)

        t_old = Title(
            title="Old Film", normalized_title="old film", year=2020, media_type="movie",
            first_seen_at=old_date, last_seen_at=old_date, updated_at=old_date, ai_validated=False
        )
        t_recent = Title(
            title="Recent Film", normalized_title="recent film", year=2023, media_type="movie",
            first_seen_at=recent_date, last_seen_at=recent_date, updated_at=recent_date, ai_validated=False
        )
        self.title_repo.upsert("t_old", t_old)
        self.title_repo.upsert("t_recent", t_recent)
        self.add_recheck_occurrence("t_old", "Old Film 2020 1080p")
        self.add_recheck_occurrence("t_recent", "Recent Film 2023 1080p")

        config = ScannerConfig(trigger="manual", mode="recheck-existing")
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)

        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_recheck_matches.return_value = {0: {"is_valid_match": True}}
        scanner.ai_matcher = mock_ai

        # With audit_days=3, only t_recent (1 day old) should be audited
        res_filtered = scanner.recheck_existing_titles(audit_days=3)
        self.assertEqual(res_filtered["titles_checked"], 1)

        # Reset ai_validated flag on t_recent for unlimited test
        t_recent.ai_validated = False
        self.title_repo.upsert("t_recent", t_recent)

        # With audit_days=0 (unlimited), both t_recent and t_old should be audited
        res_unlimited = scanner.recheck_existing_titles(audit_days=0)
        self.assertEqual(res_unlimited["titles_checked"], 2)

    def test_recheck_missing_ai_item_id_is_non_destructive_and_partial(self):
        self.seed_recheck_title("t1", "Stored Film 1", 2020)
        self.seed_recheck_title("t2", "Stored Film 2", 2021)
        before_titles = dict(self.title_repo.list_all_ids_and_titles())
        before_occurrences = {
            title_id: self.occ_repo.list_by_title(title_id)
            for title_id in ("t1", "t2")
        }
        scanner, _ = self.make_recheck_scanner({0: {"is_valid_match": True}})

        run = scanner.run("recheck_missing_id")

        self.assertEqual(run.status, "partial")
        self.assertGreater(run.error_count, 0)
        self.assertEqual(before_titles, dict(self.title_repo.list_all_ids_and_titles()))
        for title_id, occurrences in before_occurrences.items():
            self.assertEqual(occurrences, self.occ_repo.list_by_title(title_id))
        logs = self.parse_log_repo.get_all()
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(log.decision == "needs_review" for log in logs))
        self.assertTrue(all(log.trace_details["auditOutcome"] == "ai_batch_incomplete" for log in logs))

    def test_recheck_missing_ai_fields_is_non_destructive(self):
        self.seed_recheck_title()
        before_title = self.title_repo.get("t1")
        before_occurrences = self.occ_repo.list_by_title("t1")
        scanner, _ = self.make_recheck_scanner({0: {}})

        run = scanner.run("recheck_missing_field")

        self.assertEqual(run.status, "partial")
        self.assertEqual(before_title, self.title_repo.get("t1"))
        self.assertEqual(before_occurrences, self.occ_repo.list_by_title("t1"))
        self.assertEqual(self.parse_log_repo.get_all()[0].decision, "needs_review")

    def test_recheck_empty_ai_batch_is_non_destructive(self):
        self.seed_recheck_title()
        before_title = self.title_repo.get("t1")
        before_occurrences = self.occ_repo.list_by_title("t1")
        scanner, mock_ai = self.make_recheck_scanner({})

        run = scanner.run("recheck_empty_batch")

        self.assertEqual(run.status, "partial")
        self.assertEqual(mock_ai.batch_recheck_matches.call_count, 1)
        self.assertEqual(before_title, self.title_repo.get("t1"))
        self.assertEqual(before_occurrences, self.occ_repo.list_by_title("t1"))
        self.assertEqual(self.parse_log_repo.get_all()[0].decision, "needs_review")

    def test_recheck_low_confidence_ai_result_is_non_destructive(self):
        self.seed_recheck_title()
        before_title = self.title_repo.get("t1")
        before_occurrences = self.occ_repo.list_by_title("t1")
        scanner, _ = self.make_recheck_scanner({0: {"is_valid_match": True, "confidence": 0.2}})

        run = scanner.run("recheck_low_confidence")

        self.assertEqual(run.status, "partial")
        self.assertEqual(before_title, self.title_repo.get("t1"))
        self.assertEqual(before_occurrences, self.occ_repo.list_by_title("t1"))
        self.assertEqual(self.parse_log_repo.get_all()[0].decision, "needs_review")

    def test_recheck_orphan_is_not_sent_to_ai_and_needs_review(self):
        title_record = Title(
            title="Orphan Film",
            normalized_title="orphan film",
            year=2020,
            media_type="movie",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
            ai_validated=False,
        )
        self.title_repo.upsert("orphan", title_record)
        before_title = self.title_repo.get("orphan")
        scanner, mock_ai = self.make_recheck_scanner({0: {"is_valid_match": True}})

        run = scanner.run("recheck_orphan")

        self.assertEqual(run.status, "succeeded")
        mock_ai.batch_recheck_matches.assert_not_called()
        self.assertEqual(before_title, self.title_repo.get("orphan"))
        self.assertEqual(self.occ_repo.list_by_title("orphan"), [])
        log = self.parse_log_repo.get_all()[0]
        self.assertEqual(log.decision, "needs_review")
        self.assertEqual(log.trace_details["auditOutcome"], "orphan")

    def test_recheck_missing_corrected_title_is_review_only(self):
        self.seed_recheck_title()
        before_title = self.title_repo.get("t1")
        before_occurrences = self.occ_repo.list_by_title("t1")
        omdb = MockOmdbClient({"replacement": self.valid_movie})
        scanner, _ = self.make_recheck_scanner(
            {0: {"is_valid_match": False, "reason": "Stored match is unrelated"}},
            omdb,
        )

        run = scanner.run("recheck_missing_correction")

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(omdb.request_count, 0)
        self.assertEqual(before_title, self.title_repo.get("t1"))
        self.assertEqual(before_occurrences, self.occ_repo.list_by_title("t1"))
        log = self.parse_log_repo.get_all()[0]
        self.assertEqual(log.decision, "needs_review")
        self.assertEqual(log.trace_details["omdbOutcome"], "missing_corrected_title")

    def test_recheck_omdb_outcomes_are_distinguishable_and_non_destructive(self):
        cases = (
            ("timeout", OmdbTransportError("timeout"), "transport_error", "partial"),
            ("quota", OmdbLimitReachedError("quota"), "quota_exhausted", "partial"),
            ("no_match", None, "confirmed_not_found", "succeeded"),
            ("malformed", "malformed payload", "malformed_result", "partial"),
        )
        for name, omdb_error, expected_outcome, expected_status in cases:
            with self.subTest(name=name):
                self.setUp()
                self.seed_recheck_title()
                before_title = self.title_repo.get("t1")
                before_occurrences = self.occ_repo.list_by_title("t1")
                responses = {"replacement": omdb_error} if omdb_error else {}
                scanner, _ = self.make_recheck_scanner(
                    {
                        0: {
                            "is_valid_match": False,
                            "corrected_title": "Replacement",
                            "corrected_year": 2020,
                            "corrected_media_type": "movie",
                        }
                    },
                    MockOmdbClient(responses),
                )

                run = scanner.run(f"recheck_omdb_{name}")

                self.assertEqual(run.status, expected_status)
                self.assertEqual(before_title, self.title_repo.get("t1"))
                self.assertEqual(before_occurrences, self.occ_repo.list_by_title("t1"))
                log = self.parse_log_repo.get_all()[0]
                self.assertEqual(log.decision, "needs_review")
                self.assertEqual(log.trace_details["omdbOutcome"], expected_outcome)

    def test_recheck_valid_replacement_suggestion_is_retained(self):
        self.seed_recheck_title()
        before_title = self.title_repo.get("t1")
        before_occurrences = self.occ_repo.list_by_title("t1")
        scanner, mock_ai = self.make_recheck_scanner(
            {
                0: {
                    "is_valid_match": False,
                    "corrected_title": "Replacement",
                    "corrected_year": 1999,
                    "corrected_media_type": "movie",
                    "reason": "Stored match is unrelated",
                }
            },
            MockOmdbClient({"replacement": self.valid_movie}),
        )
        mock_ai.batch_validate_omdb_matches.return_value = {
            0: {"is_match": True, "confidence": 0.9}
        }

        run = scanner.run("recheck_replacement_suggestion")

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.error_count, 0)
        self.assertEqual(before_title, self.title_repo.get("t1"))
        self.assertEqual(before_occurrences, self.occ_repo.list_by_title("t1"))
        self.assertEqual(len(self.title_repo.list_all_ids_and_titles()), 1)
        log = self.parse_log_repo.get_all()[0]
        self.assertEqual(log.decision, "needs_review")
        self.assertEqual(log.trace_details["candidateOutcome"], "valid_suggestion")

    def test_recheck_dry_run_does_not_mutate_shared_fake_models(self):
        original_title = Title(
            title="Dry Run Film",
            normalized_title="dry run film",
            year=2020,
            media_type="movie",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
            ai_validated=False,
        )
        original_occurrence = Occurrence(
            source_feed_id="test-feed",
            source_feed_name="Test Feed",
            feed_entry_id="dry-run-entry",
            torrent_url="https://example.test/dry-run",
            raw_title="Dry Run Film 2020 1080p",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.now,
            last_seen_at=self.now,
        )
        self.title_repo.upsert("dry-run", original_title)
        self.occ_repo.upsert("dry-run", "dry-run-occurrence", original_occurrence)
        before_title = self.title_repo.get("dry-run")
        before_occurrences = self.occ_repo.list_by_title("dry-run")
        scanner, _ = self.make_recheck_scanner(
            {0: {"is_valid_match": True}},
            is_dry_run=True,
        )

        run = scanner.run("recheck_dry_run")

        self.assertEqual(run.status, "succeeded")
        self.assertFalse(original_title.ai_validated)
        self.assertEqual(before_title, self.title_repo.get("dry-run"))
        self.assertEqual(before_occurrences, self.occ_repo.list_by_title("dry-run"))

    def test_parse_log_trace_details_and_diagnostics(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "backend/tests/fixtures/movies_feed.atom",
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



