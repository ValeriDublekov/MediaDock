import datetime
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from movies_feed.ids import get_cache_key
from movies_feed.metadata_resolver import MetadataOutcomeStatus, OmdbResolver
from movies_feed.models import OmdbCacheEntry
from movies_feed.omdb_client import HttpTransport, OmdbClient
from backend.tests.fakes import FakeOmdbCacheRepository


class MockHttpTransport(HttpTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, params, timeout):
        self.requests.append((url, params, timeout))
        if not self.responses:
            raise RuntimeError("MockHttpTransport: no response configured")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def movie_payload(title="The Matrix", year="1999", imdb_id="tt0133093"):
    return {
        "Response": "True",
        "Title": title,
        "Year": year,
        "imdbID": imdb_id,
        "Type": "movie",
        "Genre": "Action",
        "Country": "USA",
    }


class MetadataResolverTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 8, 25, tzinfo=datetime.timezone.utc)

    def test_fallback_requests_are_counted_as_actual_http_attempts(self):
        transport = MockHttpTransport([
            {"Response": "False", "Error": "Movie not found!"},
            movie_payload(),
        ])
        timings = {}
        resolver = OmdbResolver(
            OmdbClient("secret", transport=transport),
            FakeOmdbCacheRepository(),
            request_limit=10,
            now=self.now,
        )

        outcome = resolver.resolve_title("The Matrix", 1999, media_type="movie", section_timings=timings)

        self.assertEqual(outcome.status, MetadataOutcomeStatus.FOUND)
        self.assertEqual(outcome.http_attempts, 2)
        self.assertEqual(resolver.http_attempts, 2)
        self.assertEqual(len(transport.requests), 2)
        self.assertIn("cache_lookup", timings)
        self.assertIn("omdb_api", timings)

    def test_movie_and_series_cache_entries_are_isolated(self):
        transport = MockHttpTransport([movie_payload(), movie_payload(title="Same Title", year="2020")])
        cache = FakeOmdbCacheRepository()
        resolver = OmdbResolver(
            OmdbClient("secret", transport=transport),
            cache,
            request_limit=10,
            now=self.now,
        )

        first = resolver.resolve_title("Same Title", 2020, media_type="movie")
        second = resolver.resolve_title("Same Title", 2020, media_type="series")

        self.assertEqual(first.status, MetadataOutcomeStatus.FOUND)
        self.assertEqual(second.status, MetadataOutcomeStatus.FOUND)
        self.assertFalse(second.cache_hit)
        self.assertEqual(len(transport.requests), 2)
        self.assertNotEqual(first.cache_key, second.cache_key)

    def test_transient_errors_are_not_cached(self):
        transport = MockHttpTransport([
            TimeoutError("temporary timeout"),
            movie_payload(),
        ])
        cache = FakeOmdbCacheRepository()
        resolver = OmdbResolver(
            OmdbClient("secret", transport=transport),
            cache,
            request_limit=10,
            now=self.now,
        )

        first = resolver.resolve_title("The Matrix", 1999, media_type="movie")
        second = resolver.resolve_title("The Matrix", 1999, media_type="movie")

        self.assertEqual(first.status, MetadataOutcomeStatus.TRANSPORT_ERROR)
        self.assertEqual(second.status, MetadataOutcomeStatus.FOUND)
        self.assertFalse(second.cache_hit)
        self.assertEqual(len(transport.requests), 2)
        self.assertEqual(len(cache._store), 1)

    def test_authentication_errors_are_not_cached(self):
        transport = MockHttpTransport([
            {"Response": "False", "Error": "Invalid API key!"},
            movie_payload(),
        ])
        cache = FakeOmdbCacheRepository()
        resolver = OmdbResolver(
            OmdbClient("secret", transport=transport),
            cache,
            request_limit=10,
            now=self.now,
        )

        first = resolver.resolve_title("The Matrix", 1999, media_type="movie")
        second = resolver.resolve_title("The Matrix", 1999, media_type="movie")

        self.assertEqual(first.status, MetadataOutcomeStatus.UNEXPECTED_ERROR)
        self.assertEqual(second.status, MetadataOutcomeStatus.FOUND)
        self.assertFalse(second.cache_hit)
        self.assertEqual(len(transport.requests), 2)
        self.assertEqual(cache._store, {
            second.cache_key: cache.get(second.cache_key),
        })

    def test_budget_stops_a_fallback_before_a_second_http_attempt(self):
        transport = MockHttpTransport([
            {"Response": "False", "Error": "Movie not found!"},
            movie_payload(),
        ])
        cache = FakeOmdbCacheRepository()
        resolver = OmdbResolver(
            OmdbClient("secret", transport=transport),
            cache,
            request_limit=1,
            now=self.now,
        )

        outcome = resolver.resolve_title("The Matrix", 1999, media_type="movie")

        self.assertEqual(outcome.status, MetadataOutcomeStatus.QUOTA_EXHAUSTED)
        self.assertEqual(outcome.http_attempts, 1)
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(cache._store, {})

    def test_quota_stops_later_requests_without_cache_entry(self):
        transport = MockHttpTransport([
            {"Response": "False", "Error": "Request limit reached!"},
            movie_payload(),
        ])
        cache = FakeOmdbCacheRepository()
        resolver = OmdbResolver(
            OmdbClient("secret", transport=transport),
            cache,
            request_limit=10,
            now=self.now,
        )

        first = resolver.resolve_title("First", 2020, media_type="movie")
        second = resolver.resolve_title("Second", 2020, media_type="movie")

        self.assertEqual(first.status, MetadataOutcomeStatus.QUOTA_EXHAUSTED)
        self.assertEqual(second.status, MetadataOutcomeStatus.QUOTA_EXHAUSTED)
        self.assertEqual(resolver.http_attempts, 1)
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(cache._store, {})

    def test_old_type_less_cache_entry_is_ignored(self):
        cache = FakeOmdbCacheRepository()
        old_key = get_cache_key("Old", 2020, media_type="movie")
        cache.set(
            old_key,
            OmdbCacheEntry(
                lookup_title="old",
                lookup_year=2020,
                status="found",
                payload=movie_payload(title="Old", year="2020"),
                fetched_at=self.now,
                expires_at=self.now + datetime.timedelta(days=1),
            ),
        )
        transport = MockHttpTransport([movie_payload(title="Old", year="2020")])
        resolver = OmdbResolver(
            OmdbClient("secret", transport=transport),
            cache,
            request_limit=10,
            now=self.now,
        )

        outcome = resolver.resolve_title("Old", 2020, media_type="movie")

        self.assertEqual(outcome.status, MetadataOutcomeStatus.FOUND)
        self.assertFalse(outcome.cache_hit)
        self.assertEqual(len(transport.requests), 1)
        stored = cache.get(outcome.cache_key)
        self.assertEqual(stored.source_type, "movie")
        self.assertEqual(stored.lookup_year_semantics, "movie_release_year")

    def test_manual_imdb_lookup_honors_run_budget(self):
        transport = MockHttpTransport([movie_payload()])
        resolver = OmdbResolver(
            OmdbClient("secret", transport=transport),
            FakeOmdbCacheRepository(),
            request_limit=0,
            now=self.now,
        )

        outcome = resolver.resolve_by_imdb_id(
            "tt0133093",
            lookup_title="The Matrix",
            lookup_year=1999,
            media_type="movie",
        )

        self.assertEqual(outcome.status, MetadataOutcomeStatus.QUOTA_EXHAUSTED)
        self.assertEqual(resolver.http_attempts, 0)
        self.assertEqual(len(transport.requests), 0)

    def test_manual_imdb_lookup_does_not_cache_a_different_returned_id(self):
        transport = MockHttpTransport([
            movie_payload(imdb_id="tt9999999"),
            movie_payload(imdb_id="tt0133093"),
        ])
        cache = FakeOmdbCacheRepository()
        resolver = OmdbResolver(
            OmdbClient("secret", transport=transport),
            cache,
            request_limit=10,
            now=self.now,
        )

        first = resolver.resolve_by_imdb_id(
            "tt0133093",
            lookup_title="The Matrix",
            lookup_year=1999,
            media_type="movie",
        )
        second = resolver.resolve_by_imdb_id(
            "tt0133093",
            lookup_title="The Matrix",
            lookup_year=1999,
            media_type="movie",
        )

        self.assertEqual(first.status, MetadataOutcomeStatus.UNEXPECTED_ERROR)
        self.assertEqual(second.status, MetadataOutcomeStatus.FOUND)
        self.assertFalse(second.cache_hit)
        self.assertEqual(len(transport.requests), 2)


if __name__ == "__main__":
    unittest.main()