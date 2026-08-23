import sys
import unittest
from pathlib import Path

# Ensure backend/src is on sys.path if package is not installed in environment
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from movies_feed.omdb_client import (
    OmdbClient,
    HttpTransport,
    OmdbNoMatchError,
    OmdbLimitReachedError,
    OmdbTransportError,
    _parse_year,
    _parse_float,
    _parse_int_with_commas,
    is_year_in_series_period,
)


class MockHttpTransport(HttpTransport):
    def __init__(self, responses):
        """
        responses is a list of either dictionaries to return
        or exceptions to raise.
        """
        self.responses = list(responses)
        self.requests = []

    def get(self, url, params, timeout):
        self.requests.append((url, params, timeout))
        if not self.responses:
            raise RuntimeError("MockHttpTransport: No more mocked responses configured!")
        next_resp = self.responses.pop(0)
        if isinstance(next_resp, Exception):
            raise next_resp
        return next_resp


class OmdbClientTests(unittest.TestCase):
    def test_init_raises_value_error_for_empty_key(self):
        with self.assertRaises(ValueError):
            OmdbClient("")

    def test_empty_title_raises_value_error(self):
        client = OmdbClient("test_key")
        with self.assertRaises(ValueError):
            client.get_movie_info("", "2026")

    def test_success_title_and_year_no_fallback(self):
        mock_response = {
            "Response": "True",
            "Title": "The Matrix",
            "Year": "1999",
            "imdbID": "tt0133093",
            "Type": "movie",
            "imdbRating": "8.7",
            "imdbVotes": "1,960,000",
            "Metascore": "73",
            "Genre": "Action, Sci-Fi",
            "Country": "USA, Australia",
            "Director": "Lana Wachowski, Lilly Wachowski",
            "Plot": "When a beautiful stranger...",
            "Poster": "https://example.com/matrix.jpg",
            "Runtime": "136 min",
            "Awards": "Won 4 Oscars.",
            "BoxOffice": "$171,479,930",
            "Ratings": [
                {"Source": "Internet Movie Database", "Value": "8.7/10"}
            ]
        }
        transport = MockHttpTransport([mock_response])
        client = OmdbClient("secret_key_12345", transport=transport)

        result = client.get_movie_info("The Matrix", "1999")

        # Verify result content
        self.assertEqual(result.title, "The Matrix")
        self.assertEqual(result.year, 1999)
        self.assertEqual(result.imdb_id, "tt0133093")
        self.assertEqual(result.media_type, "movie")
        self.assertEqual(result.rating, 8.7)
        self.assertEqual(result.votes, 1960000)
        self.assertEqual(result.metascore, 73)
        self.assertEqual(result.genres, ["Action", "Sci-Fi"])
        self.assertEqual(result.countries, ["USA", "Australia"])
        self.assertEqual(result.director, "Lana Wachowski, Lilly Wachowski")
        self.assertEqual(result.plot, "When a beautiful stranger...")
        self.assertEqual(result.poster_url, "https://example.com/matrix.jpg")
        self.assertEqual(result.runtime, "136 min")
        self.assertEqual(result.awards, "Won 4 Oscars.")
        self.assertEqual(result.box_office, "$171,479,930")
        self.assertEqual(result.ratings, [{"Source": "Internet Movie Database", "Value": "8.7/10"}])

        # Verify Firestore to_dict compatibility
        camel_dict = result.to_dict()
        self.assertEqual(camel_dict["title"], "The Matrix")
        self.assertEqual(camel_dict["year"], 1999)
        self.assertEqual(camel_dict["mediaType"], "movie")
        self.assertEqual(camel_dict["imdbId"], "tt0133093")
        self.assertEqual(camel_dict["imdbRating"], 8.7)
        self.assertEqual(camel_dict["imdbVotes"], 1960000)
        self.assertEqual(camel_dict["metascore"], 73)
        self.assertEqual(camel_dict["genres"], ["Action", "Sci-Fi"])
        self.assertEqual(camel_dict["countries"], ["USA", "Australia"])

        # Verify transport requests (only 1 request, since primary search succeeded)
        self.assertEqual(len(transport.requests), 1)
        url, params, timeout = transport.requests[0]
        self.assertEqual(params["t"], "The Matrix")
        self.assertEqual(params["y"], "1999")
        self.assertEqual(params["apikey"], "secret_key_12345")

    def test_fallback_when_title_and_year_fails(self):
        # 1st request fails, 2nd request succeeds
        responses = [
            {"Response": "False", "Error": "Movie not found!"},
            {
                "Response": "True",
                "Title": "The Matrix",
                "Year": "1999",
                "imdbID": "tt0133093",
                "Type": "movie",
                "Genre": "Action"
            }
        ]
        transport = MockHttpTransport(responses)
        client = OmdbClient("secret_key_12345", transport=transport)

        result = client.get_movie_info("The Matrix", "1999")

        self.assertEqual(result.title, "The Matrix")
        self.assertEqual(result.year, 1999)

        # Verify 2 requests were made
        self.assertEqual(len(transport.requests), 2)
        # 1st request with year
        self.assertEqual(transport.requests[0][1]["t"], "The Matrix")
        self.assertEqual(transport.requests[0][1]["y"], "1999")
        # 2nd request without year
        self.assertEqual(transport.requests[1][1]["t"], "The Matrix")
        self.assertNotIn("y", transport.requests[1][1])

    def test_no_match_raises_no_match_error(self):
        # Both requests fail with Response False
        responses = [
            {"Response": "False", "Error": "Movie not found!"},
            {"Response": "False", "Error": "Something else was wrong!"}
        ]
        transport = MockHttpTransport(responses)
        client = OmdbClient("secret_key_12345", transport=transport)

        with self.assertRaises(OmdbNoMatchError) as ctx:
            client.get_movie_info("Unknown Movie", "2026")

        self.assertIn("OMDb lookup failed", str(ctx.exception))
        self.assertEqual(len(transport.requests), 2)

    def test_limit_reached_on_primary_raises_limit_error(self):
        responses = [
            {"Response": "False", "Error": "Request limit reached!"}
        ]
        transport = MockHttpTransport(responses)
        client = OmdbClient("secret_key_12345", transport=transport)

        with self.assertRaises(OmdbLimitReachedError):
            client.get_movie_info("Some Movie", "2026")

        # Should stop immediately and not try fallback
        self.assertEqual(len(transport.requests), 1)

    def test_limit_reached_on_fallback_raises_limit_error(self):
        responses = [
            {"Response": "False", "Error": "Movie not found!"},
            {"Response": "False", "Error": "Request limit reached!"}
        ]
        transport = MockHttpTransport(responses)
        client = OmdbClient("secret_key_12345", transport=transport)

        with self.assertRaises(OmdbLimitReachedError):
            client.get_movie_info("Some Movie", "2026")

        self.assertEqual(len(transport.requests), 2)

    def test_transport_timeout_raises_transport_error_and_hides_api_key(self):
        raw_error_message = "Timeout occurred connecting to https://www.omdbapi.com/?apikey=secret_key_12345&t=Some"
        responses = [
            TimeoutError(raw_error_message)
        ]
        transport = MockHttpTransport(responses)
        client = OmdbClient("secret_key_12345", transport=transport)

        with self.assertRaises(OmdbTransportError) as ctx:
            client.get_movie_info("Some Movie", "2026")

        error_str = str(ctx.exception)
        self.assertNotIn("secret_key_12345", error_str)
        self.assertIn("***", error_str)

    def test_documentary_and_short_type_determination(self):
        # Movie with Documentary genre
        doc_resp = {
            "Response": "True",
            "Title": "Documentary Movie",
            "Year": "2020",
            "Type": "movie",
            "Genre": "Documentary, Biography"
        }
        transport1 = MockHttpTransport([doc_resp])
        client1 = OmdbClient("secret_key_12345", transport=transport1)
        res1 = client1.get_movie_info("Documentary Movie")
        self.assertEqual(res1.media_type, "documentary")

        # Movie with Short genre
        short_resp = {
            "Response": "True",
            "Title": "Short Film",
            "Year": "2021",
            "Type": "movie",
            "Genre": "Animation, Short, Comedy"
        }
        transport2 = MockHttpTransport([short_resp])
        client2 = OmdbClient("secret_key_12345", transport=transport2)
        res2 = client2.get_movie_info("Short Film")
        self.assertEqual(res2.media_type, "short")

    def test_omdb_representation_hides_api_key(self):
        client = OmdbClient("secret_key_12345")
        rep = repr(client)
        self.assertNotIn("secret_key_12345", rep)

    def test_parse_helpers_edge_cases(self):
        self.assertIsNone(_parse_year("N/A"))
        self.assertIsNone(_parse_year(""))
        self.assertEqual(_parse_year("2015-2020"), 2015)

        self.assertIsNone(_parse_float("N/A"))
        self.assertIsNone(_parse_float("abc"))

        self.assertIsNone(_parse_int_with_commas("N/A"))
        self.assertEqual(_parse_int_with_commas("1,234,567"), 1234567)

    def test_is_year_in_series_period(self):
        # Range 2007-2015
        self.assertTrue(is_year_in_series_period("2007–2015", 2012))
        self.assertTrue(is_year_in_series_period("2007-2015", 2007))
        self.assertTrue(is_year_in_series_period("2007–2015", 2015))
        self.assertFalse(is_year_in_series_period("2007–2015", 2005))
        self.assertFalse(is_year_in_series_period("2007–2015", 2018))

        # Ongoing series 2019–
        self.assertTrue(is_year_in_series_period("2019–", 2026))
        self.assertFalse(is_year_in_series_period("2019–", 2015))

        # Single year 2012
        self.assertTrue(is_year_in_series_period("2012", 2012))
        self.assertFalse(is_year_in_series_period("2012", 2014))

        # N/A or empty
        self.assertTrue(is_year_in_series_period("N/A", 2012))
        self.assertTrue(is_year_in_series_period("", 2012))

    def test_series_matching_mad_men_season_year(self):
        # For series, search is done without 'y' param first to avoid OMDb matching single-year wrong shows like "Modern Mad Men".
        # Mad Men broadcasting period (2007–2015) covers requested season year 2012.
        response = {
            "Response": "True",
            "Title": "Mad Men",
            "Year": "2007–2015",
            "imdbID": "tt0804497",
            "Type": "series",
            "Genre": "Drama"
        }
        transport = MockHttpTransport([response])
        client = OmdbClient("secret_key_12345", transport=transport)

        result = client.get_movie_info("Mad Men", "2012", media_type="series")

        self.assertEqual(result.title, "Mad Men")
        self.assertEqual(result.year, 2007)
        self.assertEqual(result.media_type, "series")
        self.assertEqual(result.imdb_id, "tt0804497")

        # Verify only 1 request was made and it did NOT pass y=2012
        self.assertEqual(len(transport.requests), 1)
        url, params, timeout = transport.requests[0]
        self.assertEqual(params["t"], "Mad Men")
        self.assertEqual(params["type"], "series")
        self.assertNotIn("y", params)

    def test_series_year_out_of_range_raises_no_match(self):
        # Searching for Mad Men with year 1990 (outside 2007-2015) raises OmdbNoMatchError
        response = {
            "Response": "True",
            "Title": "Mad Men",
            "Year": "2007–2015",
            "imdbID": "tt0804497",
            "Type": "series",
            "Genre": "Drama"
        }
        transport = MockHttpTransport([response])
        client = OmdbClient("secret_key_12345", transport=transport)

        with self.assertRaises(OmdbNoMatchError):
            client.get_movie_info("Mad Men", "1990", media_type="series")

    def test_get_by_imdb_id_success(self):
        response = {
            "Response": "True",
            "Title": "Interstellar",
            "Year": "2014",
            "imdbID": "tt0816692",
            "Type": "movie",
            "Genre": "Adventure, Drama, Sci-Fi"
        }
        transport = MockHttpTransport([response])
        client = OmdbClient("secret_key_12345", transport=transport)

        result = client.get_by_imdb_id("tt0816692")

        self.assertEqual(result.title, "Interstellar")
        self.assertEqual(result.year, 2014)
        self.assertEqual(result.imdb_id, "tt0816692")
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(transport.requests[0][1]["i"], "tt0816692")

    def test_get_by_imdb_id_not_found(self):
        response = {"Response": "False", "Error": "Incorrect IMDb ID."}
        transport = MockHttpTransport([response])
        client = OmdbClient("secret_key_12345", transport=transport)

        with self.assertRaises(OmdbNoMatchError):
            client.get_by_imdb_id("tt0000000")

    def test_movie_fallback_rejects_year_mismatch_exceeding_one_year(self):
        # 1st request with year 2024 fails
        # 2nd fallback request returns a 1980 film with same title -> should be rejected (>1 year diff)
        responses = [
            {"Response": "False", "Error": "Movie not found!"},
            {
                "Response": "True",
                "Title": "Classic Movie",
                "Year": "1980",
                "imdbID": "tt0080000",
                "Type": "movie",
                "Genre": "Drama"
            }
        ]
        transport = MockHttpTransport(responses)
        client = OmdbClient("secret_key_12345", transport=transport)

        with self.assertRaises(OmdbNoMatchError):
            client.get_movie_info("Classic Movie", "2024", media_type="movie")

    def test_movie_fallback_accepts_year_difference_within_one_year(self):
        # 1st request with year 2024 fails
        # 2nd fallback returns 2023 (festival release vs commercial release) -> accepted (tolerance ±1)
        responses = [
            {"Response": "False", "Error": "Movie not found!"},
            {
                "Response": "True",
                "Title": "Recent Movie",
                "Year": "2023",
                "imdbID": "tt1234567",
                "Type": "movie",
                "Genre": "Drama"
            }
        ]
        transport = MockHttpTransport(responses)
        client = OmdbClient("secret_key_12345", transport=transport)

        result = client.get_movie_info("Recent Movie", "2024", media_type="movie")
        self.assertEqual(result.title, "Recent Movie")
        self.assertEqual(result.year, 2023)

    def test_movie_search_does_not_fallback_to_series(self):
        # Search for a movie where only a series exists -> should NOT return the series
        responses = [
            {"Response": "False", "Error": "Movie not found!"},
            {"Response": "False", "Error": "Movie not found!"}
        ]
        transport = MockHttpTransport(responses)
        client = OmdbClient("secret_key_12345", transport=transport)

        with self.assertRaises(OmdbNoMatchError):
            client.get_movie_info("Some Series Title", "2024", media_type="movie")

        # Verify both requests requested type=movie and did NOT drop the type constraint
        self.assertEqual(len(transport.requests), 2)
        self.assertEqual(transport.requests[0][1]["type"], "movie")
        self.assertEqual(transport.requests[1][1]["type"], "movie")


if __name__ == "__main__":
    unittest.main()
