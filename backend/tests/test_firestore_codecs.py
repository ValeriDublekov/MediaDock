import datetime
import unittest

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

from movies_feed.firestore_codecs import (
    manual_mapping_from_dict,
    occurrence_from_dict,
    parse_log_from_dict,
    rss_snapshot_from_dict,
    rss_snapshot_item_from_dict,
    scan_run_from_dict,
    title_from_dict,
)
from movies_feed.match_policy import BroadcastRange
from movies_feed.models import (
    ManualMapping,
    Occurrence,
    ParseLog,
    ParseLogResolution,
    RssSnapshot,
    RssSnapshotItem,
    ScanRun,
    SourceContext,
    Title,
)


class FirestoreCodecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.utc = datetime.timezone.utc
        self.now = datetime.datetime(2026, 8, 7, 10, 0, tzinfo=self.utc)

    def test_title_round_trip(self) -> None:
        title = Title(
            title="Mad Men",
            normalized_title="mad men",
            year=2007,
            media_type="series",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
            imdb_id="tt0804503",
            imdb_rating=8.7,
            imdb_votes=250000,
            metascore=85,
            genres=["Drama"],
            countries=["US"],
            director="Matthew Weiner",
            plot="An advertising executive navigates New York.",
            poster_url="https://example.test/mad-men.jpg",
            runtime="47 min",
            awards="Multiple awards",
            box_office=None,
            ratings=[{"Source": "IMDb", "Value": "8.7/10"}],
            ai_validated=True,
            ai_checked_at=self.now,
            source_type="series",
            content_kind="standard",
            broadcast_range=BroadcastRange(2007, 2015, "2007-2015"),
        )

        restored = title_from_dict(title.to_dict())

        self.assertEqual(restored, title)

    def test_occurrence_round_trip(self) -> None:
        source_context = SourceContext(
            source_feed_id="feed-1",
            source_feed_name="Movies Feed",
            feed_type="movie",
            feed_entry_id="entry-1",
            torrent_url="https://example.test/torrent",
            raw_title="Example Film 2026",
            source_published_at=self.now,
            observed_at=self.now,
        )
        occurrence = Occurrence(
            source_feed_id="feed-1",
            source_feed_name="Movies Feed",
            feed_entry_id="entry-1",
            torrent_url="https://example.test/torrent",
            raw_title="Example Film 2026",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.now,
            last_seen_at=self.now,
            source_context=source_context,
            validation_status="validated",
            validation_policy_version="v2",
            validated_at=self.now,
            validation_reason="matched policy",
        )

        restored = occurrence_from_dict(occurrence.to_dict())

        self.assertEqual(restored, occurrence)

    def test_scan_run_round_trip(self) -> None:
        run = ScanRun(
            started_at=self.now,
            finished_at=self.now,
            status="succeeded",
            trigger="manual",
            feeds_processed=2,
            entries_seen=12,
            titles_created=3,
            titles_updated=4,
            occurrences_created=5,
            occurrences_updated=6,
            cache_hits=7,
            omdb_requests=8,
            ignored_entries=9,
            ai_calls=10,
            ai_items_processed=11,
            ai_failures=1,
            retries_attempted=2,
            retries_resolved=3,
            retries_failed=1,
            proposals_created=4,
            proposals_applied=3,
            proposals_failed=1,
            error_count=1,
            error_summary=["one error"],
            section_timings={"rss": 1.5},
            phase_metrics={"rss": {"entries": 12}},
        )

        restored = scan_run_from_dict(run.to_dict())

        self.assertEqual(restored, run)

    def test_parse_log_round_trip(self) -> None:
        resolution = ParseLogResolution(
            resolved_at=self.now,
            outcome="matched",
            reason="catalog_match",
            title_id="title-1",
            occurrence_id="occurrence-1",
        )
        log = ParseLog(
            id="log-1",
            raw_title="Example Film 2026",
            feed_name="Movies Feed",
            parsed_successfully=True,
            parsed_title="Example Film",
            parsed_year=2026,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=self.now,
            error_message=None,
            trace_details={"parser": "rutracker"},
            decision="matched",
            event_kind="source",
            retry_state="resolved",
            attempt_count=2,
            last_attempt_at=self.now,
            resolution=resolution,
        )

        restored = parse_log_from_dict(log.to_dict())

        self.assertEqual(restored, log)

    def test_rss_snapshot_and_item_round_trip(self) -> None:
        snapshot = RssSnapshot(
            id="snapshot-1",
            run_id="run-1",
            created_at=self.now,
            item_count=1,
            status="ready",
        )
        item = RssSnapshotItem(
            title_id="title-1",
            source_type="movie",
            group_order=0,
            feed_order=1,
            entry_order=2,
            rss_position=0,
        )

        restored_snapshot = rss_snapshot_from_dict(snapshot.to_dict(), doc_id=snapshot.id)
        restored_item = rss_snapshot_item_from_dict(item.to_dict())

        self.assertEqual(restored_snapshot, snapshot)
        self.assertEqual(restored_item, item)

    def test_manual_mapping_round_trip(self) -> None:
        mapping = ManualMapping(
            id="mapping-1",
            raw_title="Example Film 2026",
            imdb_id="tt1234567",
            created_at=self.now,
            parsed_title="Example Film",
            parsed_year=2026,
            created_by="operator@example.test",
        )

        restored = manual_mapping_from_dict(mapping.to_dict())

        self.assertEqual(restored, mapping)

    def test_legacy_defaults_are_explicit(self) -> None:
        run = scan_run_from_dict({
            "startedAt": self.now,
            "status": "running",
            "trigger": "schedule",
        })
        snapshot = rss_snapshot_from_dict({
            "runId": "legacy-run",
            "createdAt": self.now,
        }, doc_id="legacy-snapshot")

        self.assertEqual(run.feeds_processed, 0)
        self.assertEqual(run.error_summary, [])
        self.assertEqual(run.section_timings, {})
        self.assertEqual(snapshot.id, "legacy-snapshot")
        self.assertEqual(snapshot.item_count, 0)
        self.assertEqual(snapshot.status, "ready")


if __name__ == "__main__":
    unittest.main()