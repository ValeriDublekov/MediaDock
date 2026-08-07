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
        import requests
        # Raise standard requests timeout which might have the API key in its details
        raw_error_message = "Timeout occurred connecting to https://www.omdbapi.com/?apikey=secret_key_12345&t=Some"
        responses = [
            requests.Timeout(raw_error_message)
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


if __name__ == "__main__":
    unittest.main()
