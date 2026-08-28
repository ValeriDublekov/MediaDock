import hashlib
import unittest

from movies_feed.ids import (
    get_audit_event_id,
    get_fallback_title_id_v1,
    get_fallback_title_id_v2,
    get_occurrence_id,
    get_occurrence_id_v1,
    get_source_item_id,
    get_title_id_v2,
)


class VersionedIdTests(unittest.TestCase):
    def test_equal_entry_ids_from_different_feeds_do_not_collide(self) -> None:
        movies_id = get_source_item_id("movies", "shared-guid", "https://example.test/1")
        series_id = get_source_item_id("series", "shared-guid", "https://example.test/1")

        self.assertNotEqual(movies_id, series_id)

    def test_url_fallback_is_feed_aware(self) -> None:
        movies_id = get_source_item_id("movies", None, " https://example.test/topic?id=1 ")
        series_id = get_source_item_id("series", "", "https://example.test/topic?id=1")

        self.assertNotEqual(movies_id, series_id)
        self.assertEqual(
            movies_id,
            hashlib.sha256(
                b"v2:source:movies:url:https://example.test/topic?id=1"
            ).hexdigest(),
        )

    def test_entry_id_precedes_url_and_repeated_items_are_idempotent(self) -> None:
        first_id = get_source_item_id(" movies ", " entry-1 ", "https://example.test/old")
        second_id = get_source_item_id("movies", "entry-1", "https://example.test/new")

        self.assertEqual(first_id, second_id)
        self.assertEqual(
            first_id,
            hashlib.sha256(b"v2:source:movies:entry:entry-1").hexdigest(),
        )

    def test_source_and_audit_namespaces_cannot_collide(self) -> None:
        source_id = get_source_item_id("movies", "entry-1", None)
        audit_id = get_audit_event_id("movies:entry:entry-1")

        self.assertNotEqual(source_id, audit_id)

    def test_v1_compatibility_helpers_preserve_legacy_outputs(self) -> None:
        expected_occurrence_id = hashlib.sha256(b"v1:entry-1").hexdigest()
        expected_title_id = hashlib.sha256(b"v1:the matrix:1999:movie").hexdigest()

        self.assertEqual(get_occurrence_id_v1("entry-1", "ignored"), expected_occurrence_id)
        self.assertEqual(get_occurrence_id("entry-1", "ignored"), expected_occurrence_id)
        self.assertEqual(
            get_fallback_title_id_v1("the matrix", 1999, "movie"),
            expected_title_id,
        )

    def test_v2_fallback_title_uses_resolved_canonical_metadata(self) -> None:
        expected_id = hashlib.sha256(
            b"v2:title:the matrix:movie_release_year:1999:movie"
        ).hexdigest()

        self.assertEqual(
            get_fallback_title_id_v2("  The   Matrix ", 1999, "documentary"),
            expected_id,
        )
        self.assertEqual(
            get_title_id_v2(None, "The Matrix", 1999, "movie"),
            expected_id,
        )

    def test_v2_series_fallback_uses_series_start_year_semantics(self) -> None:
        expected_id = hashlib.sha256(
            b"v2:title:seasoned show:series_start_year:2007:series"
        ).hexdigest()

        self.assertEqual(
            get_fallback_title_id_v2("Seasoned Show", 2007, "series"),
            expected_id,
        )

    def test_v2_source_id_rejects_incomplete_identity(self) -> None:
        with self.assertRaises(ValueError):
            get_source_item_id("", "entry-1", None)
        with self.assertRaises(ValueError):
            get_source_item_id("movies", None, "")


if __name__ == "__main__":
    unittest.main()