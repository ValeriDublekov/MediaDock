import unittest
from dataclasses import FrozenInstanceError

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

from movies_feed.rss_snapshot import RssSnapshotCollector


class TestRssSnapshotCollector(unittest.TestCase):
    def test_duplicate_title_keeps_earliest_effective_position(self):
        collector = RssSnapshotCollector()
        collector.record_candidate("movie-1", "movie", feed_order=2, entry_order=3)
        collector.record_candidate("movie-1", "movie", feed_order=1, entry_order=4)
        collector.record_candidate("movie-1", "movie", feed_order=1, entry_order=2)

        items = collector.build_items()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].feed_order, 1)
        self.assertEqual(items[0].entry_order, 2)
        self.assertEqual(items[0].rss_position, 0)
        with self.assertRaises(FrozenInstanceError):
            items[0].rss_position = 1

    def test_mixed_movie_and_series_items_are_grouped_movie_first(self):
        collector = RssSnapshotCollector()
        collector.record_candidate("series-1", "series", feed_order=0, entry_order=0)
        collector.record_candidate("movie-1", "movie", feed_order=1, entry_order=0)

        items = collector.build_items()

        self.assertEqual([item.title_id for item in items], ["movie-1", "series-1"])
        self.assertEqual([item.source_type for item in items], ["movie", "series"])
        self.assertEqual([item.rss_position for item in items], [0, 1])

    def test_feed_order_precedes_entry_order(self):
        collector = RssSnapshotCollector()
        collector.record_candidate("movie-2", "movie", feed_order=1, entry_order=5)
        collector.record_candidate("movie-1", "movie", feed_order=0, entry_order=9)
        collector.record_candidate("movie-3", "movie", feed_order=1, entry_order=2)

        items = collector.build_items()

        self.assertEqual([item.title_id for item in items], ["movie-1", "movie-3", "movie-2"])
        self.assertEqual([item.rss_position for item in items], [0, 1, 2])

    def test_empty_collector_builds_no_items(self):
        self.assertEqual(RssSnapshotCollector().build_items(), [])