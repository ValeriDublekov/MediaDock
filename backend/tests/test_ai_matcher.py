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


if __name__ == "__main__":
    unittest.main()
