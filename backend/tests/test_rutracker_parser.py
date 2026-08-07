import sys
import unittest
from pathlib import Path

# Ensure backend/src is on sys.path if package is not installed in environment
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import feedparser

from movies_feed.rutracker_parser import is_latin_candidate, parse_rutracker_title


ROOT = Path(__file__).resolve().parent
VIDEO_SETTINGS = {
    "quality_tags": ["1080p", "2160p", "4K", "720p"],
    "rip_tags": ["BDRip", "WEB-DL", "Blu-ray", "WEBRip"],
}


class RutrackerParserTests(unittest.TestCase):
    def parse_titles(self, fixture_name, content_type):
        feed = feedparser.parse(str(ROOT / "fixtures" / fixture_name))
        return [
            parse_rutracker_title(
                entry.title,
                content_type=content_type,
                video_settings=VIDEO_SETTINGS,
            )
            for entry in feed.entries
        ]

    def test_movie_feed_uses_movie_parser(self):
        parsed = self.parse_titles("movies_feed.atom", "movie")

        self.assertGreater(len(parsed), 0)
        for index, item in enumerate(parsed):
            self.assertTrue(item.title, f"Missing title for movie entry #{index}")
            self.assertTrue(is_latin_candidate(item.title), f"Title is not latin-like for movie entry #{index}: {item.title!r}")
            self.assertTrue(item.year, f"Missing year for movie entry #{index}: {item.title!r}")

        self.assertEqual(parsed[0].title, "Four Rooms")
        self.assertEqual(parsed[0].year, "1995")
        self.assertFalse(parsed[0].is_series)
        self.assertEqual(parsed[0].quality, "1080p")
        self.assertEqual(parsed[1].title, "La grazia")

    def test_series_feed_uses_series_parser(self):
        parsed = self.parse_titles("series_feed.atom", "series")

        self.assertEqual(parsed[0].title, "Monarch: Legacy of Monsters")
        self.assertTrue(parsed[0].is_series)
        self.assertEqual(parsed[0].year, "2026")

        self.assertEqual(parsed[1].title, "Party of Five")
        self.assertEqual(parsed[2].title, "Pitch")
        self.assertEqual(parsed[3].title, "The Third Day: Autumn")
        self.assertEqual(parsed[3].rip_type, "WEBRip")

    def test_content_type_controls_series_flag(self):
        raw = "Example / Example Title / Сезон: 1 / Серии: 1-8 из 8 [2026, США, WEB-DL 1080p]"

        movie_parsed = parse_rutracker_title(raw, content_type="movie", video_settings=VIDEO_SETTINGS)
        series_parsed = parse_rutracker_title(raw, content_type="series", video_settings=VIDEO_SETTINGS)

        self.assertEqual(movie_parsed.title, "Example")
        self.assertEqual(series_parsed.title, "Example")
        self.assertFalse(movie_parsed.is_series)
        self.assertTrue(series_parsed.is_series)


if __name__ == "__main__":
    unittest.main()
