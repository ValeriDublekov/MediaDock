import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from movies_feed.feed_fetcher import (
    FeedContentTypeError,
    FeedDnsError,
    FeedEntryLimitError,
    FeedFetcher,
    FeedFixtureError,
    FeedNetworkError,
    FeedParseError,
    FeedSizeLimitError,
    FeedStatusError,
    FeedUrlError,
)
from movies_feed.omdb_client import OmdbClient
from movies_feed.repository import (
    FakeOccurrenceRepository,
    FakeOmdbCacheRepository,
    FakeParseLogRepository,
    FakeScanRunRepository,
    FakeTitleRepository,
)
from movies_feed.scanner import ScannerConfig, ScannerService


class FakeResponse:
    def __init__(self, status_code=200, headers=None, chunks=()):
        self.status_code = status_code
        self.headers = headers or {}
        self.chunks = chunks
        self.closed = False
        self.chunk_size = None

    def iter_content(self, chunk_size):
        self.chunk_size = chunk_size
        if isinstance(self.chunks, BaseException):
            raise self.chunks
        return iter(self.chunks)

    def close(self):
        self.closed = True


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, timeout, verify, allow_redirects, stream):
        self.calls.append({
            "url": url,
            "timeout": timeout,
            "verify": verify,
            "allow_redirects": allow_redirects,
            "stream": stream,
        })
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FeedFetcherTests(unittest.TestCase):
    def make_fetcher(self, transport, dns_resolver=None, **kwargs):
        return FeedFetcher(
            allowed_hosts={"feed.example.test"},
            transport=transport,
            dns_resolver=dns_resolver or (lambda host, port: ["8.8.8.8"]),
            **kwargs,
        )

    def test_accepts_https_feed_and_passes_safe_transport_options(self):
        transport = FakeTransport([
            FakeResponse(
                headers={"Content-Type": "application/atom+xml; charset=utf-8"},
                chunks=[b"<feed>", b"ok</feed>"],
            )
        ])
        fetcher = self.make_fetcher(transport, connect_timeout=2, read_timeout=7)

        self.assertEqual(fetcher.fetch("https://feed.example.test/feed.atom"), b"<feed>ok</feed>")
        self.assertEqual(transport.calls[0]["timeout"], (2.0, 7.0))
        self.assertTrue(transport.calls[0]["verify"])
        self.assertFalse(transport.calls[0]["allow_redirects"])
        self.assertTrue(transport.calls[0]["stream"])

    def test_rejects_unsafe_url_forms_before_transport(self):
        transport = FakeTransport([])
        fetcher = self.make_fetcher(transport)

        for url in (
            "http://feed.example.test/feed.atom",
            "file:///tmp/feed.atom",
            "https://user:password@feed.example.test/feed.atom",
            "https://other.example.test/feed.atom",
            "https://feed.example.test/feed atom",
        ):
            with self.subTest(url=url), self.assertRaises(FeedUrlError):
                fetcher.fetch(url)

        self.assertEqual(transport.calls, [])

    def test_rejects_private_loopback_link_local_reserved_and_mapped_addresses(self):
        blocked_addresses = (
            "10.0.0.1",
            "127.0.0.1",
            "169.254.1.1",
            "192.0.2.1",
            "::1",
            "::ffff:127.0.0.1",
        )
        for blocked_address in blocked_addresses:
            with self.subTest(blocked_address=blocked_address):
                transport = FakeTransport([])
                fetcher = self.make_fetcher(
                    transport,
                    dns_resolver=lambda host, port, address=blocked_address: [address],
                )
                with self.assertRaises(FeedDnsError):
                    fetcher.fetch("https://feed.example.test/feed.atom")
                self.assertEqual(transport.calls, [])

    def test_validates_every_redirect_and_disables_transport_redirects(self):
        transport = FakeTransport([
            FakeResponse(status_code=302, headers={"Location": "/next.atom"}),
            FakeResponse(
                headers={"Content-Type": "application/rss+xml"},
                chunks=[b"<rss />"],
            ),
        ])
        fetcher = self.make_fetcher(transport, max_redirects=1)

        self.assertEqual(fetcher.fetch("https://feed.example.test/start.atom"), b"<rss />")
        self.assertEqual(
            [call["url"] for call in transport.calls],
            [
                "https://feed.example.test/start.atom",
                "https://feed.example.test/next.atom",
            ],
        )
        self.assertTrue(all(not call["allow_redirects"] for call in transport.calls))

    def test_rejects_redirect_to_disallowed_host_before_following(self):
        transport = FakeTransport([
            FakeResponse(
                status_code=302,
                headers={"Location": "https://other.example.test/feed.atom"},
            )
        ])
        fetcher = self.make_fetcher(transport)

        with self.assertRaises(FeedUrlError):
            fetcher.fetch("https://feed.example.test/start.atom")
        self.assertEqual(len(transport.calls), 1)

    def test_rejects_redirect_that_resolves_to_private_address(self):
        transport = FakeTransport([
            FakeResponse(
                status_code=302,
                headers={"Location": "https://redirect.example.test/feed.atom"},
            )
        ])

        def resolve(host, port):
            return ["127.0.0.1" if host == "redirect.example.test" else "8.8.8.8"]

        fetcher = FeedFetcher(
            allowed_hosts={"feed.example.test", "redirect.example.test"},
            transport=transport,
            dns_resolver=resolve,
        )

        with self.assertRaises(FeedDnsError):
            fetcher.fetch("https://feed.example.test/start.atom")
        self.assertEqual(len(transport.calls), 1)

    def test_rejects_status_and_content_type_failures(self):
        response_cases = (
            (FakeResponse(status_code=503, headers={"Content-Type": "application/rss+xml"}), FeedStatusError),
            (FakeResponse(headers={"Content-Type": "text/html"}, chunks=[b"<html />"]), FeedContentTypeError),
            (FakeResponse(headers={}, chunks=[b"<rss />"]), FeedContentTypeError),
        )
        for response, expected_error in response_cases:
            with self.subTest(expected_error=expected_error.__name__):
                fetcher = self.make_fetcher(FakeTransport([response]))
                with self.assertRaises(expected_error):
                    fetcher.fetch("https://feed.example.test/feed.atom")

    def test_wraps_transport_timeout_without_exposing_response_data(self):
        transport = FakeTransport([requests.Timeout("read timed out")])
        fetcher = self.make_fetcher(transport)

        with self.assertRaises(FeedNetworkError) as context:
            fetcher.fetch("https://feed.example.test/feed.atom")
        self.assertEqual(str(context.exception), "feed request failed")

    def test_enforces_decompressed_response_size_limit(self):
        response = FakeResponse(
            headers={"Content-Type": "application/rss+xml"},
            chunks=[b"123", b"456"],
        )
        fetcher = self.make_fetcher(
            FakeTransport([response]),
            max_response_bytes=5,
        )

        with self.assertRaises(FeedSizeLimitError):
            fetcher.fetch("https://feed.example.test/feed.atom")
        self.assertTrue(response.closed)

    def test_rejects_feed_entry_amplification_and_bozo_results(self):
        fetcher = self.make_fetcher(FakeTransport([]), max_entries=2)

        with self.assertRaises(FeedEntryLimitError):
            fetcher.validate_entry_count([1, 2, 3])

        bozo_feed = SimpleNamespace(
            bozo=True,
            bozo_exception=ValueError("malformed"),
            entries=[1],
        )
        with self.assertRaises(FeedParseError):
            fetcher.validate_parsed_feed(bozo_feed)

    def test_reads_only_explicit_fixture_files(self):
        transport = FakeTransport([])
        fetcher = self.make_fetcher(transport)
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_path = Path(temp_dir) / "feed.atom"
            fixture_path.write_bytes(b"<feed />")

            self.assertEqual(fetcher.fetch_file(fixture_path), b"<feed />")
            with self.assertRaises(FeedUrlError):
                fetcher.fetch(str(fixture_path))

    def test_rejects_empty_or_oversized_fixtures(self):
        fetcher = self.make_fetcher(FakeTransport([]), max_response_bytes=3)
        with tempfile.TemporaryDirectory() as temp_dir:
            empty_path = Path(temp_dir) / "empty.atom"
            empty_path.write_bytes(b"")
            oversized_path = Path(temp_dir) / "large.atom"
            oversized_path.write_bytes(b"1234")

            with self.assertRaises(FeedFixtureError):
                fetcher.fetch_file(empty_path)
            with self.assertRaises(FeedSizeLimitError):
                fetcher.fetch_file(oversized_path)

    def create_scanner(self, feed_fetcher):
        return ScannerService(
            config=ScannerConfig(
                rss_feeds={
                    "test": {
                        "url": "https://feed.example.test/feed.atom",
                        "type": "movie",
                    }
                },
            ),
            omdb_client=OmdbClient(api_key="test"),
            title_repo=FakeTitleRepository(),
            occurrence_repo=FakeOccurrenceRepository(),
            cache_repo=FakeOmdbCacheRepository(),
            run_repo=FakeScanRunRepository(),
            parse_log_repo=FakeParseLogRepository(),
            feed_fetcher=feed_fetcher,
        )

    def test_scanner_passes_fetched_bytes_to_feedparser(self):
        transport = FakeTransport([
            FakeResponse(
                headers={"Content-Type": "application/rss+xml"},
                chunks=[b"<rss />"],
            )
        ])
        fetcher = self.make_fetcher(transport)
        scanner = self.create_scanner(fetcher)
        parsed_feed = SimpleNamespace(bozo=False, entries=[])

        with patch("movies_feed.scanner.feedparser.parse", return_value=parsed_feed) as parse:
            run = scanner.run("bytes-only")

        self.assertEqual(run.status, "succeeded")
        parse.assert_called_once_with(b"<rss />")

    def test_scanner_rejects_bozo_feed_before_processing_entries(self):
        transport = FakeTransport([
            FakeResponse(
                headers={"Content-Type": "application/rss+xml"},
                chunks=[b"<rss />"],
            )
        ])
        scanner = self.create_scanner(self.make_fetcher(transport))
        bozo_feed = SimpleNamespace(
            bozo=True,
            bozo_exception=ValueError("truncated"),
            entries=[SimpleNamespace(title="Should not be processed")],
        )

        with patch("movies_feed.scanner.feedparser.parse", return_value=bozo_feed):
            run = scanner.run("bozo")

        self.assertEqual(run.status, "partial")
        self.assertEqual(run.entries_seen, 0)
        self.assertEqual(scanner.title_repo.list_all(), [])
        self.assertTrue(any("Feed error" in error for error in run.error_summary))


if __name__ == "__main__":
    unittest.main()