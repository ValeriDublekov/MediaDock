import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

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

    def test_model_selection_preserves_configured_ids(self):
        matcher_default = AiMatcher(api_key="valid_key", inter_request_delay=0.1)
        self.assertEqual(matcher_default.model, "gemini-3.1-flash-lite")

        matcher_legacy_25_lite = AiMatcher(api_key="valid_key", model="gemini-2.5-flash-lite", inter_request_delay=0.1)
        self.assertEqual(matcher_legacy_25_lite.model, "gemini-2.5-flash-lite")

        matcher_legacy_25_flash = AiMatcher(api_key="valid_key", model="gemini-2.5-flash", inter_request_delay=0.1)
        self.assertEqual(matcher_legacy_25_flash.model, "gemini-2.5-flash")

    def test_model_capability_requires_generate_content(self):
        payload = {
            "models": [
                {
                    "name": "models/gemini-2.5-flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-2.5-flash-image",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ]
        }
        AiMatcher.validate_model_capability_payload(payload, "gemini-2.5-flash")

        with self.assertRaises(ValueError):
            AiMatcher.validate_model_capability_payload(payload, "gemini-2.5-flash-lite")

    @patch("urllib.request.urlopen")
    def test_model_capability_request_uses_header_api_key(self, mock_urlopen):
        response = MagicMock()
        response.read.return_value = b'{"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}]}'
        response.__enter__.return_value = response
        mock_urlopen.return_value = response

        matcher = AiMatcher(api_key="secret-key", model="gemini-2.5-flash")
        matcher.validate_model_capability()

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.headers["X-goog-api-key"], "secret-key")
        self.assertNotIn("key=secret-key", request.full_url)

    @patch("urllib.request.urlopen")
    def test_generation_request_uses_header_api_key(self, mock_urlopen):
        response = MagicMock()
        response.read.return_value = b'{"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}'
        response.__enter__.return_value = response
        mock_urlopen.return_value = response

        matcher = AiMatcher(api_key="secret-key", inter_request_delay=0.0)
        matcher._call_gemini("test prompt")

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.headers["X-goog-api-key"], "secret-key")
        self.assertNotIn("key=secret-key", request.full_url)

    @patch.object(AiMatcher, "_call_gemini")
    def test_batch_extract_titles(self, mock_call):
        mock_call.return_value = [
            {
                "id": 0,
                "title": "Dune: Part Two",
                "year": 2024,
                "media_type": "movie",
                "confidence": 0.95,
            },
            {
                "id": 1,
                "title": "Fallout",
                "year": 2024,
                "media_type": "series",
                "confidence": 0.90,
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
        self.assertEqual(res[0]["confidence"], 0.95)
        self.assertEqual(res[1]["title"], "Fallout")
        self.assertEqual(res[1]["media_type"], "series")
        self.assertEqual(res[1]["confidence"], 0.90)

    @patch.object(AiMatcher, "_call_gemini")
    def test_batch_extract_titles_fails_closed_on_low_confidence_or_malformed(self, mock_call):
        matcher = AiMatcher(api_key="valid_key")
        items = [
            {"id": 0, "raw_title": "Film A", "feed_type": "movie"},
            {"id": 1, "raw_title": "Film B", "feed_type": "movie"},
        ]

        # Low confidence (< 0.70)
        mock_call.return_value = [
            {"id": 0, "title": "Film A", "year": 2024, "media_type": "movie", "confidence": 0.65},
            {"id": 1, "title": "Film B", "year": 2024, "media_type": "movie", "confidence": 0.90},
        ]
        self.assertEqual(matcher.batch_extract_titles(items), {})

        # Invalid media type
        mock_call.return_value = [
            {"id": 0, "title": "Film A", "year": 2024, "media_type": "game", "confidence": 0.95},
            {"id": 1, "title": "Film B", "year": 2024, "media_type": "movie", "confidence": 0.90},
        ]
        self.assertEqual(matcher.batch_extract_titles(items), {})

        # Empty title
        mock_call.return_value = [
            {"id": 0, "title": "   ", "year": 2024, "media_type": "movie", "confidence": 0.95},
            {"id": 1, "title": "Film B", "year": 2024, "media_type": "movie", "confidence": 0.90},
        ]
        self.assertEqual(matcher.batch_extract_titles(items), {})

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
                "confidence": 0.85,
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
        self.assertEqual(res[0]["confidence"], 0.98)
        self.assertFalse(res[1]["is_match"])
        self.assertEqual(res[1]["confidence"], 0.85)

    @patch.object(AiMatcher, "_call_gemini")
    def test_batch_validate_omdb_matches_fails_closed_on_low_confidence_or_malformed(self, mock_call):
        matcher = AiMatcher(api_key="valid_key")
        candidates = [
            {"id": 0, "raw_title": "Dune 2", "omdb_title": "Dune"},
            {"id": 1, "raw_title": "Fallout", "omdb_title": "Fallout"},
        ]

        # Low confidence (< 0.70)
        mock_call.return_value = [
            {"id": 0, "is_match": True, "confidence": 0.50, "reason": "maybe"},
            {"id": 1, "is_match": True, "confidence": 0.90, "reason": "yes"},
        ]
        self.assertEqual(matcher.batch_validate_omdb_matches(candidates), {})

        # Non-boolean is_match
        mock_call.return_value = [
            {"id": 0, "is_match": "true", "confidence": 0.90, "reason": "yes"},
            {"id": 1, "is_match": True, "confidence": 0.90, "reason": "yes"},
        ]
        self.assertEqual(matcher.batch_validate_omdb_matches(candidates), {})

    @patch.object(AiMatcher, "_call_gemini")
    def test_batch_recheck_matches(self, mock_call):
        mock_call.return_value = [
            {
                "id": 0,
                "is_valid_match": True,
                "confidence": 0.95,
                "reason": "Correct match",
                "corrected_title": None,
                "corrected_year": None,
                "corrected_media_type": None
            },
            {
                "id": 1,
                "is_valid_match": False,
                "confidence": 0.90,
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
        self.assertEqual(res[0]["confidence"], 0.95)
        self.assertFalse(res[1]["is_valid_match"])
        self.assertEqual(res[1]["confidence"], 0.90)
        self.assertEqual(res[1]["corrected_title"], "Fallout")
        self.assertEqual(res[1]["corrected_year"], 2024)
        self.assertEqual(res[1]["corrected_media_type"], "series")

    @patch.object(AiMatcher, "_call_gemini")
    def test_batch_recheck_rejects_incomplete_or_unknown_ids(self, mock_call):
        matcher = AiMatcher(api_key="valid_key")
        items = [
            {"id": 0, "raw_title": "Film 1", "current_omdb_title": "Film 1"},
            {"id": 1, "raw_title": "Film 2", "current_omdb_title": "Film 2"},
        ]

        for response in (
            [{"id": 0, "is_valid_match": True, "confidence": 0.95}],
            [
                {"id": 0, "is_valid_match": True, "confidence": 0.95},
                {"id": 0, "is_valid_match": True, "confidence": 0.95},
            ],
            [
                {"id": 0, "is_valid_match": True, "confidence": 0.95},
                {"id": 2, "is_valid_match": True, "confidence": 0.95},
            ],
            [
                {"id": 0, "is_valid_match": None, "confidence": 0.95},
                {"id": 1, "is_valid_match": True, "confidence": 0.95},
            ],
            [
                {"id": 0, "is_valid_match": True, "confidence": 0.75},  # Low audit confidence (<0.80)
                {"id": 1, "is_valid_match": True, "confidence": 0.95},
            ],
        ):
            with self.subTest(response=response):
                mock_call.return_value = response
                self.assertEqual(matcher.batch_recheck_matches(items), {})

    def test_transport_timeout_then_success_with_injected_clock_and_sleep(self):
        import urllib.error

        slept_durations = []
        fake_time = [1000.0]

        def fake_clock():
            return fake_time[0]

        def fake_sleep(duration):
            slept_durations.append(duration)
            fake_time[0] += duration

        timeout_err = urllib.error.URLError("The read operation timed out")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"candidates": [{"content": {"parts": [{"text": "{\\"result\\": true}"}]}}]}'
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", side_effect=[timeout_err, mock_resp]) as mock_urlopen:
            matcher = AiMatcher(
                api_key="valid_key",
                inter_request_delay=0.0,
                clock=fake_clock,
                sleep=fake_sleep,
            )
            res = matcher._call_gemini("test prompt", item_count=5)

            self.assertEqual(res, {"result": True})
            self.assertTrue(matcher.is_available)
            self.assertEqual(mock_urlopen.call_count, 2)
            self.assertEqual(slept_durations, [2.0])  # Retry backoff for attempt 0 is 2.0s
            stats = matcher.get_stats()
            self.assertEqual(stats["total_calls"], 1)
            self.assertEqual(stats["successful_calls"], 1)
            self.assertEqual(stats["failed_calls"], 0)
            self.assertEqual(stats["total_items_processed"], 5)

    def test_transport_retry_exhaustion_on_5xx_server_error(self):
        import urllib.error
        from io import BytesIO

        slept_durations = []
        fake_time = [1000.0]

        def fake_clock():
            return fake_time[0]

        def fake_sleep(duration):
            slept_durations.append(duration)
            fake_time[0] += duration

        error_503 = urllib.error.HTTPError("http://example.com", 503, "Service Unavailable", {}, BytesIO())

        with patch("urllib.request.urlopen", side_effect=error_503) as mock_urlopen:
            matcher = AiMatcher(
                api_key="valid_key",
                inter_request_delay=0.0,
                clock=fake_clock,
                sleep=fake_sleep,
            )
            res = matcher._call_gemini("test prompt", item_count=3)

            self.assertIsNone(res)
            self.assertFalse(matcher.is_available)
            self.assertEqual(mock_urlopen.call_count, 3)
            self.assertEqual(slept_durations, [2.0, 4.0])  # Attempt 0: 2s, Attempt 1: 4s
            stats = matcher.get_stats()
            self.assertEqual(stats["total_calls"], 1)
            self.assertEqual(stats["successful_calls"], 0)
            self.assertEqual(stats["failed_calls"], 1)
            self.assertEqual(stats["total_items_processed"], 0)

    def test_transport_terminal_errors_disable_matcher_immediately(self):
        import urllib.error
        from io import BytesIO

        for status_code in (400, 401, 404):
            with self.subTest(status_code=status_code):
                error = urllib.error.HTTPError("http://example.com", status_code, "Terminal Error", {}, BytesIO())
                with patch("urllib.request.urlopen", side_effect=error) as mock_urlopen:
                    matcher = AiMatcher(api_key="valid_key", inter_request_delay=0.0)
                    res = matcher._call_gemini("test prompt")

                    self.assertIsNone(res)
                    self.assertFalse(matcher.is_available)
                    self.assertEqual(mock_urlopen.call_count, 1)
                    stats = matcher.get_stats()
                    self.assertEqual(stats["total_calls"], 1)
                    self.assertEqual(stats["failed_calls"], 1)

    def test_forbidden_cooldown_behavior(self):
        import urllib.error
        from io import BytesIO

        fake_time = [1000.0]

        def fake_clock():
            return fake_time[0]

        error_403 = urllib.error.HTTPError("http://example.com", 403, "Forbidden", {}, BytesIO())

        with patch("urllib.request.urlopen", side_effect=error_403) as mock_urlopen:
            matcher = AiMatcher(
                api_key="valid_key",
                forbidden_cooldown_seconds=120.0,
                clock=fake_clock,
            )
            self.assertTrue(matcher.is_available)
            res = matcher._call_gemini("test prompt")
            self.assertIsNone(res)
            self.assertEqual(mock_urlopen.call_count, 1)

            # Inside cooldown window
            self.assertFalse(matcher.is_available)
            fake_time[0] += 60.0
            self.assertFalse(matcher.is_available)

            # Advance past cooldown window
            fake_time[0] += 61.0
            self.assertTrue(matcher.is_available)

    def test_enforced_inter_request_delay(self):
        slept_durations = []
        fake_time = [1000.0]

        def fake_clock():
            return fake_time[0]

        def fake_sleep(duration):
            slept_durations.append(duration)
            fake_time[0] += duration

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"candidates": [{"content": {"parts": [{"text": "{\\"ok\\": true}"}]}}]}'
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            matcher = AiMatcher(
                api_key="valid_key",
                inter_request_delay=5.0,
                clock=fake_clock,
                sleep=fake_sleep,
            )
            # Call 1: no previous request, no inter-request delay slept
            matcher._call_gemini("prompt 1")
            self.assertEqual(slept_durations, [])

            # Simulate 2.0s passing before call 2
            fake_time[0] += 2.0

            # Call 2: should sleep remaining 3.0s
            matcher._call_gemini("prompt 2")
            self.assertEqual(slept_durations, [3.0])
            self.assertEqual(mock_urlopen.call_count, 2)

    def test_response_size_limit_rejection(self):
        from movies_feed.ai_validator import MAX_RESPONSE_BYTES

        mock_resp = MagicMock()
        # Return bytes larger than MAX_RESPONSE_BYTES
        mock_resp.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            matcher = AiMatcher(api_key="valid_key", inter_request_delay=0.0)
            res = matcher._call_gemini("prompt")
            self.assertIsNone(res)
            self.assertEqual(matcher.get_stats()["failed_calls"], 1)

    def test_validate_model_capability_response_size_limit(self):
        from movies_feed.ai_validator import MAX_RESPONSE_BYTES
        from movies_feed.ai_matcher import GeminiModelCapabilityError

        mock_resp = MagicMock()
        mock_resp.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            matcher = AiMatcher(api_key="valid_key")
            with self.assertRaises(GeminiModelCapabilityError) as cm:
                matcher.validate_model_capability()
            self.assertIn("exceeded maximum allowed size", str(cm.exception))

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
