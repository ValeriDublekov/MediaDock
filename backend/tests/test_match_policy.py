import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from movies_feed.match_policy import (
    evaluate_match,
    classify_media,
    parse_broadcast_range,
)


class MatchPolicyTests(unittest.TestCase):
    def test_table_driven_match_decisions(self):
        cases = [
            ("movie exact", "movie", "movie", 2024, 2024, None, "accepted", "movie_release_year_within_tolerance"),
            ("movie plus one", "movie", "movie", 2024, 2023, None, "accepted", "movie_release_year_within_tolerance"),
            ("movie out of range", "movie", "movie", 2024, 2021, None, "rejected", "movie_release_year_mismatch"),
            ("series later season", "series", "series", 2012, 2007, "2007-2015", "accepted", "series_season_year_in_range"),
            ("series open ended", "series", "series", 2026, 2019, "2019-", "accepted", "series_season_year_in_range"),
            ("series out of range", "series", "series", 1990, 2007, "2007-2015", "rejected", "series_season_year_out_of_range"),
            ("series range unavailable", "series", "series", 2012, 2007, None, "accepted", "series_broadcast_range_unavailable"),
            ("movie year unknown", "movie", "movie", None, 2024, None, "accepted", "movie_release_year_unknown"),
            ("series year unknown", "series", "series", None, 2024, "2007-2015", "accepted", "series_season_year_unknown"),
            ("documentary series", "series", "series", 2022, 2018, "2018-", "accepted", "series_season_year_in_range"),
            ("movie documentary", "movie", "movie", 2022, 2022, None, "accepted", "movie_release_year_within_tolerance"),
            ("short movie", "movie", "movie", 2022, 2022, None, "accepted", "movie_release_year_within_tolerance"),
            ("known type mismatch", "movie", "series", 2022, 2022, "2020-", "rejected", "type_mismatch"),
            ("unknown feed inferred", None, "series", 2022, 2020, "2020-", "accepted", "series_season_year_in_range"),
        ]

        for name, expected, actual, source_year, resolved_year, raw_range, status, reason_code in cases:
            with self.subTest(name=name):
                decision = evaluate_match(
                    expected_source_type=expected,
                    actual_source_type=actual,
                    source_year=source_year,
                    resolved_year=resolved_year,
                    broadcast_range=parse_broadcast_range(raw_range),
                )
                self.assertEqual(decision.status, status)
                self.assertEqual(decision.reason_code, reason_code)

    def test_manual_mapping_bypasses_type_and_year_but_not_exclusions(self):
        accepted = evaluate_match(
            expected_source_type="movie",
            actual_source_type="series",
            source_year=1990,
            resolved_year=2024,
            broadcast_range=parse_broadcast_range("2020-"),
            manual_mapping=True,
        )
        self.assertEqual(accepted.status, "accepted")
        self.assertEqual(accepted.reason_code, "manual_mapping_bypass")

        rejected = evaluate_match(
            expected_source_type="movie",
            actual_source_type="series",
            countries=["Russia"],
            excluded_countries=["Russia"],
            manual_mapping=True,
        )
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.reason_code, "excluded_country")

    def test_unknown_resolved_type_is_ambiguous(self):
        decision = evaluate_match(
            expected_source_type="series",
            actual_source_type=None,
            actual_media_type=None,
            source_year=2024,
            resolved_year=2020,
        )
        self.assertEqual(decision.status, "ambiguous")
        self.assertEqual(decision.reason_code, "source_type_unknown")

    def test_media_classification_preserves_series_source_type(self):
        documentary_series = classify_media("series", ["Documentary", "History"])
        self.assertEqual(documentary_series.source_type, "series")
        self.assertEqual(documentary_series.content_kind, "documentary")
        self.assertEqual(documentary_series.media_type, "series")

        documentary_movie = classify_media("movie", ["Documentary"])
        self.assertEqual(documentary_movie.source_type, "movie")
        self.assertEqual(documentary_movie.content_kind, "documentary")
        self.assertEqual(documentary_movie.media_type, "documentary")

        short_movie = classify_media("movie", ["Short"])
        self.assertEqual(short_movie.source_type, "movie")
        self.assertEqual(short_movie.content_kind, "short")
        self.assertEqual(short_movie.media_type, "short")

    def test_broadcast_range_parser(self):
        closed = parse_broadcast_range("2007–2015")
        self.assertEqual((closed.start_year, closed.end_year), (2007, 2015))

        open_ended = parse_broadcast_range("2019-")
        self.assertEqual((open_ended.start_year, open_ended.end_year), (2019, None))
        present_ended = parse_broadcast_range("2019–Present")
        self.assertEqual((present_ended.start_year, present_ended.end_year), (2019, None))

        single_year = parse_broadcast_range("2012")
        self.assertEqual((single_year.start_year, single_year.end_year), (2012, 2012))
        self.assertIsNone(parse_broadcast_range("N/A"))


if __name__ == "__main__":
    unittest.main()