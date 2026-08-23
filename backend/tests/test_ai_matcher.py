import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from movies_feed.ai_matcher import AiMatcher


class TestAiMatcher(unittest.TestCase):
    def test_availability(self):
        matcher_no_key = AiMatcher(api_key="")
        self.assertFalse(matcher_no_key.is_available)

        matcher_with_key = AiMatcher(api_key="valid_gemini_key_12345")
        self.assertTrue(matcher_with_key.is_available)

    @patch.object(AiMatcher, "_call_gemini")
    def test_batch_extract_titles(self, mock_call):
        mock_call.return_value = [
            {
                "id": 0,
                "title": "Dune: Part Two",
                "year": 2024,
                "media_type": "movie",
                "confidence": "high"
            },
            {
                "id": 1,
                "title": "Fallout",
                "year": 2024,
                "media_type": "series",
                "confidence": "high"
            }
        ]

        matcher = AiMatcher(api_key="valid_key")
        items = [
            {"id": 0, "raw_title": "Дюна 2 / Dune: Part Two [2024, HDRip]", "feed_type": "movie"},
            {"id": 1, "raw_title": "Фоллаут / Fallout [Сезон 1] (2024)", "feed_type": "series"}
        ]
        res = matcher.batch_extract_titles(items)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["title"], "Dune: Part Two")
        self.assertEqual(res[0]["year"], 2024)
        self.assertEqual(res[0]["media_type"], "movie")
        self.assertEqual(res[1]["title"], "Fallout")
        self.assertEqual(res[1]["media_type"], "series")

    @patch.object(AiMatcher, "_call_gemini")
    def test_batch_validate_omdb_matches(self, mock_call):
        mock_call.return_value = [
            {
                "id": 0,
                "is_match": True,
                "confidence": 0.98,
                "reason": "Exact title and year match"
            },
            {
                "id": 1,
                "is_match": False,
                "confidence": 0.1,
                "reason": "Series matched to an old 1995 movie documentary"
            }
        ]

        matcher = AiMatcher(api_key="valid_key")
        candidates = [
            {
                "id": 0,
                "raw_title": "Dune 2 (2024)",
                "feed_type": "movie",
                "omdb_title": "Dune: Part Two",
                "omdb_year": 2024,
                "omdb_type": "movie"
            },
            {
                "id": 1,
                "raw_title": "Fallout Season 1 (2024)",
                "feed_type": "series",
                "omdb_title": "Fallout",
                "omdb_year": 1995,
                "omdb_type": "movie"
            }
        ]
        res = matcher.batch_validate_omdb_matches(candidates)
        self.assertEqual(len(res), 2)
        self.assertTrue(res[0]["is_match"])
        self.assertFalse(res[1]["is_match"])

    @patch.object(AiMatcher, "_call_gemini")
    def test_batch_recheck_matches(self, mock_call):
        mock_call.return_value = [
            {
                "id": 0,
                "is_valid_match": True,
                "reason": "Correct match",
                "corrected_title": None,
                "corrected_year": None,
                "corrected_media_type": None
            },
            {
                "id": 1,
                "is_valid_match": False,
                "reason": "Title is a TV series from 2024, but was matched to 1980 short movie",
                "corrected_title": "Fallout",
                "corrected_year": 2024,
                "corrected_media_type": "series"
            }
        ]

        matcher = AiMatcher(api_key="valid_key")
        items = [
            {
                "id": 0,
                "raw_title": "Dune 2 (2024)",
                "current_omdb_title": "Dune: Part Two",
                "current_omdb_year": 2024,
                "current_omdb_type": "movie",
            },
            {
                "id": 1,
                "raw_title": "Fallout (Сезон 1) (2024)",
                "current_omdb_title": "Fallout",
                "current_omdb_year": 1980,
                "current_omdb_type": "short",
            }
        ]
        res = matcher.batch_recheck_matches(items)
        self.assertEqual(len(res), 2)
        self.assertTrue(res[0]["is_valid_match"])
        self.assertFalse(res[1]["is_valid_match"])
        self.assertEqual(res[1]["corrected_title"], "Fallout")
        self.assertEqual(res[1]["corrected_year"], 2024)
        self.assertEqual(res[1]["corrected_media_type"], "series")

    @patch("time.sleep", return_value=None)
    @patch("urllib.request.urlopen")
    def test_call_gemini_retry_on_429(self, mock_urlopen, mock_sleep):
        import urllib.error
        from io import BytesIO

        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"candidates": [{"content": {"parts": [{"text": "{\\"id\\": 0}"}]}}]}'

        # Raise HTTP 429 once, then succeed
        error_429 = urllib.error.HTTPError("http://example.com", 429, "Too Many Requests", {}, BytesIO())
        mock_urlopen.side_effect = [error_429, mock_resp]

        matcher = AiMatcher(api_key="valid_key")
        res = matcher._call_gemini("test prompt")
        self.assertEqual(res, {"id": 0})
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(2.0)

    def test_clean_title_for_comparison(self):
        from movies_feed.ids import clean_title_for_comparison

        self.assertEqual(
            clean_title_for_comparison("Dune: Part Two"),
            clean_title_for_comparison("Dune Part Two")
        )
        self.assertEqual(
            clean_title_for_comparison("Deadpool & Wolverine"),
            clean_title_for_comparison("Deadpool and Wolverine")
        )
        self.assertNotEqual(
            clean_title_for_comparison("Inside Out 2"),
            clean_title_for_comparison("Inside Out")
        )


if __name__ == "__main__":
    unittest.main()
