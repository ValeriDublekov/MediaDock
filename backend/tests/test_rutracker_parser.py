import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

# Ensure backend/src is on sys.path if package is not installed in environment
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    import feedparser
except ImportError:
    class _Entry:
        def __init__(self, title: str):
            self.title = title

    class _Feed:
        def __init__(self, entries):
            self.entries = entries

    class _FeedParserMock:
        @staticmethod
        def parse(filepath: str):
            tree = ET.parse(filepath)
            root = tree.getroot()
            entries = []
            for elem in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                title_elem = elem.find("{http://www.w3.org/2005/Atom}title")
                if title_elem is not None and title_elem.text:
                    entries.append(_Entry(title_elem.text.strip()))
            if not entries:
                for elem in root.findall(".//entry"):
                    title_elem = elem.find("title")
                    if title_elem is not None and title_elem.text:
                        entries.append(_Entry(title_elem.text.strip()))
            return _Feed(entries)

    feedparser = _FeedParserMock()

from movies_feed.rutracker_parser import is_latin_candidate, parse_rutracker_title


ROOT = Path(__file__).resolve().parent
VIDEO_SETTINGS = {
    "quality_tags": ["1080p", "2160p", "4K", "720p"],
    "rip_tags": ["BDRemux", "BDRip", "WEB-DLRip", "WEB-DL", "Blu-ray", "WEBRip"],
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
            self.assertTrue(
                is_latin_candidate(item.title),
                f"Title is not latin-like for movie entry #{index}: {item.title!r}",
            )
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

    def test_embedded_slashes_corpus(self):
        corpus = [
            (
                "Face/Off [1997, США, BDRip 1080p]",
                "Face/Off",
                "1997",
                False,
                "1080p",
                "BDRip",
            ),
            (
                "Без лица / Face/Off (Джон Ву) [1997, США, боевик, BDRip 1080p]",
                "Face/Off",
                "1997",
                False,
                "1080p",
                "BDRip",
            ),
            (
                "Фрост против Никсона / Frost/Nixon [2008, США, BDRip 720p]",
                "Frost/Nixon",
                "2008",
                False,
                "720p",
                "BDRip",
            ),
            (
                "50/50 / Жизнь прекрасна / 50/50 [2011, США, BDRip]",
                "50/50",
                "2011",
                False,
                "",
                "BDRip",
            ),
            (
                "F/X / Иллюзия убийства / F/X [1986, США, BDRip]",
                "F/X",
                "1986",
                False,
                "",
                "BDRip",
            ),
            (
                "9/11: Inside the President's War Room [2021, США, WEB-DL 1080p]",
                "9/11: Inside the President's War Room",
                "2021",
                False,
                "1080p",
                "WEB-DL",
            ),
        ]

        for raw, expected_title, expected_year, expected_series, expected_q, expected_r in corpus:
            with self.subTest(raw=raw):
                parsed = parse_rutracker_title(raw, video_settings=VIDEO_SETTINGS)
                self.assertEqual(parsed.title, expected_title)
                self.assertEqual(parsed.year, expected_year)
                self.assertEqual(parsed.is_series, expected_series)
                self.assertEqual(parsed.quality, expected_q)
                self.assertEqual(parsed.rip_type, expected_r)
                self.assertIn("embedded_slash_preserved", parsed.reasons)
                self.assertGreaterEqual(parsed.confidence, 0.80)

    def test_meaningful_parentheses_and_director_stripping_corpus(self):
        corpus = [
            (
                "(500) Days of Summer / (500) дней лета [2009, США, BDRip]",
                "(500) Days of Summer",
                "2009",
            ),
            (
                "Neon Genesis Evangelion (Death and Rebirth) [1997, Япония, BDRip]",
                "Neon Genesis Evangelion (Death and Rebirth)",
                "1997",
            ),
            (
                "The Lord of the Rings: The Two Towers (Extended Edition) [2002, США, BDRip]",
                "The Lord of the Rings: The Two Towers (Extended Edition)",
                "2002",
            ),
            (
                "Четыре комнаты / Four Rooms (Эллисон Андерс, Квентин Тарантино / Allison Anders, Quentin Tarantino) [1995, BDRip]",
                "Four Rooms",
                "1995",
            ),
        ]

        for raw, expected_title, expected_year in corpus:
            with self.subTest(raw=raw):
                parsed = parse_rutracker_title(raw, video_settings=VIDEO_SETTINGS)
                self.assertEqual(parsed.title, expected_title)
                self.assertEqual(parsed.year, expected_year)
                self.assertFalse(parsed.is_series)
                self.assertGreaterEqual(parsed.confidence, 0.90)

    def test_numeric_only_candidates_corpus(self):
        # Letters are required for is_latin_candidate
        self.assertFalse(is_latin_candidate("1984"))
        self.assertFalse(is_latin_candidate("12345"))
        self.assertFalse(is_latin_candidate("50/50"))
        self.assertFalse(is_latin_candidate("300"))
        self.assertFalse(is_latin_candidate(""))
        self.assertFalse(is_latin_candidate("   "))
        self.assertTrue(is_latin_candidate("Face/Off"))
        self.assertTrue(is_latin_candidate("F/X"))
        self.assertTrue(is_latin_candidate("Four Rooms"))

        # Numeric titles are properly selected as fallback when no Latin candidate with letters exists
        p_1984 = parse_rutracker_title("1984 / 1984 [1984, Великобритания, BDRip]")
        self.assertEqual(p_1984.title, "1984")
        self.assertEqual(p_1984.year, "1984")
        self.assertIn("numeric_candidate_selected", p_1984.reasons)

        p_300 = parse_rutracker_title("300 спартанцев / 300 [2006, США, BDRip]")
        self.assertEqual(p_300.title, "300")
        self.assertEqual(p_300.year, "2006")

    def test_invalid_and_realistic_year_corpus(self):
        # Valid year
        p_valid = parse_rutracker_title("Movie Title [2024, США, BDRip 1080p]")
        self.assertEqual(p_valid.year, "2024")
        self.assertIn("valid_year_extracted", p_valid.reasons)
        self.assertGreaterEqual(p_valid.confidence, 0.85)

        # Missing year (only quality tag in brackets)
        p_missing = parse_rutracker_title("Movie Title [1080p, BDRip]")
        self.assertIsNone(p_missing.year)
        self.assertIn("year_missing", p_missing.reasons)

        # Unrealistic years outside 1888..2035 get flagged with invalid_year_range and low confidence
        for bad_year_raw in [
            "Movie Title [9999, США, BDRip]",
            "Movie Title [0000, США, BDRip]",
            "Movie Title [1200, США, BDRip]",
            "Movie Title [2150, США, BDRip]",
        ]:
            with self.subTest(raw=bad_year_raw):
                p_bad = parse_rutracker_title(bad_year_raw)
                self.assertIsNone(p_bad.year)
                self.assertIn("invalid_year_range", p_bad.reasons)
                self.assertLess(p_bad.confidence, 0.70)

    def test_series_markers_avoid_substring_false_positives(self):
        # Movie titles containing season words must NOT be misclassified as series
        p_open_season_unspec = parse_rutracker_title("Сезон охоты / Open Season [2006, США, BDRip]")
        self.assertEqual(p_open_season_unspec.title, "Open Season")
        self.assertFalse(p_open_season_unspec.is_series)

        p_witch = parse_rutracker_title("Время ведьм / Season of the Witch [2011, США, BDRip]")
        self.assertEqual(p_witch.title, "Season of the Witch")
        self.assertFalse(p_witch.is_series)

        p_serial = parse_rutracker_title("Серийный номер / Serial Mom [1994, США, BDRip]")
        self.assertEqual(p_serial.title, "Serial Mom")
        self.assertFalse(p_serial.is_series)

        # Explicit series markers are correctly detected
        p_series = parse_rutracker_title(
            "Монарх: Наследие монстров / Monarch: Legacy of Monsters / Сезон: 2 / Серии: 1-10 [2026]"
        )
        self.assertEqual(p_series.title, "Monarch: Legacy of Monsters")
        self.assertTrue(p_series.is_series)
        self.assertIn("series_inferred_from_markers", p_series.reasons)

    def test_multilingual_titles_corpus(self):
        corpus = [
            ("Без лица / Face/Off / 夺面双雄 [1997, BDRip]", "Face/Off", "1997"),
            ("Грация / Помилование / La grazia / Grace [2025, BDRip]", "La grazia", "2025"),
            ("Четыре комнаты / Four Rooms [1995, BDRip]", "Four Rooms", "1995"),
            ("Снег и пламя / La neige et le feu / Snow and Fire [1991, BDRip]", "La neige et le feu", "1991"),
        ]

        for raw, expected_title, expected_year in corpus:
            with self.subTest(raw=raw):
                parsed = parse_rutracker_title(raw, video_settings=VIDEO_SETTINGS)
                self.assertEqual(parsed.title, expected_title)
                self.assertEqual(parsed.year, expected_year)

    def test_empty_and_low_confidence_diagnostics(self):
        # Empty title
        p_empty = parse_rutracker_title("")
        self.assertEqual(p_empty.title, "")
        self.assertEqual(p_empty.confidence, 0.0)
        self.assertIn("empty_raw_title", p_empty.reasons)

        p_none = parse_rutracker_title(None)  # type: ignore
        self.assertEqual(p_none.title, "")
        self.assertEqual(p_none.confidence, 0.0)

        # Cyrillic only title
        p_cyr = parse_rutracker_title("Четыре комнаты [1995, BDRip]")
        self.assertEqual(p_cyr.title, "Четыре комнаты")
        self.assertIn("cyrillic_candidate_selected", p_cyr.reasons)
        self.assertGreaterEqual(p_cyr.confidence, 0.85)


if __name__ == "__main__":
    unittest.main()

