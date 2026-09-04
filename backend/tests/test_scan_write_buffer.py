import datetime
import unittest

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

from movies_feed.models import ManualMapping, Occurrence, ParseLog, ScanRun, Title
from movies_feed.repository import (
    FakeManualMappingRepository,
    FakeOccurrenceRepository,
    FakeParseLogRepository,
    FakeTitleRepository,
)
from movies_feed.scan_write_buffer import ScanWriteBuffer


class RecordingTitleRepository(FakeTitleRepository):
    def __init__(self):
        super().__init__()
        self.batches = []

    def upsert_many(self, titles):
        self.batches.append(list(titles))
        super().upsert_many(titles)


class RecordingOccurrenceRepository(FakeOccurrenceRepository):
    def __init__(self, fail=False):
        super().__init__()
        self.batches = []
        self.fail = fail

    def upsert_many(self, occurrences):
        self.batches.append(list(occurrences))
        if self.fail:
            raise RuntimeError("simulated occurrence write failure")
        super().upsert_many(occurrences)


class RecordingParseLogRepository(FakeParseLogRepository):
    def __init__(self):
        super().__init__()
        self.batches = []

    def add_many(self, logs):
        self.batches.append(list(logs))
        super().add_many(logs)


class TestScanWriteBuffer(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

    def make_title(self, title_id):
        return Title(
            title=title_id,
            normalized_title=title_id.lower(),
            year=2020,
            media_type="movie",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
        )

    def make_occurrence(self, occurrence_id):
        return Occurrence(
            source_feed_id="feed",
            source_feed_name="Feed",
            feed_entry_id=occurrence_id,
            torrent_url=f"https://example.test/{occurrence_id}",
            raw_title=occurrence_id,
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.now,
            last_seen_at=self.now,
        )

    def make_log(self, log_id):
        return ParseLog(
            id=log_id,
            raw_title=log_id,
            feed_name="feed",
            parsed_successfully=False,
            parsed_title=None,
            parsed_year=None,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
        )

    def make_run(self):
        return ScanRun(
            started_at=self.now,
            finished_at=None,
            status="running",
            trigger="test",
        )

    def make_buffer(self, *, occurrence_repo=None, is_dry_run=False, is_parse_only=False):
        return ScanWriteBuffer(
            title_repo=RecordingTitleRepository(),
            occurrence_repo=occurrence_repo or RecordingOccurrenceRepository(),
            parse_log_repo=RecordingParseLogRepository(),
            manual_mapping_repo=FakeManualMappingRepository(),
            is_dry_run=is_dry_run,
            is_parse_only=is_parse_only,
        )

    def test_pending_reads_are_visible_and_duplicate_stage_is_deduplicated(self):
        buffer = self.make_buffer()
        first_title = self.make_title("matrix")
        first_occurrence = self.make_occurrence("occurrence")
        buffer.stage_title_and_occurrence(
            "title-id",
            first_title,
            "occurrence-id",
            first_occurrence,
            self.make_run(),
        )

        self.assertIs(buffer.get_title("title-id"), first_title)
        self.assertIs(buffer.get_occurrence("title-id", "occurrence-id"), first_occurrence)

        second_title = self.make_title("matrix refreshed")
        second_occurrence = self.make_occurrence("occurrence refreshed")
        run = self.make_run()
        buffer.stage_title_and_occurrence(
            "title-id",
            second_title,
            "occurrence-id",
            second_occurrence,
            run,
        )

        self.assertEqual(len(buffer.pending_titles), 1)
        self.assertEqual(len(buffer.pending_occurrences), 1)
        self.assertEqual(run.titles_updated, 1)
        self.assertEqual(run.occurrences_updated, 1)

    def test_flush_writes_in_stage_order_and_clears_successful_pending_data(self):
        title_repo = RecordingTitleRepository()
        occurrence_repo = RecordingOccurrenceRepository()
        parse_log_repo = RecordingParseLogRepository()
        mapping_repo = FakeManualMappingRepository()
        buffer = ScanWriteBuffer(
            title_repo=title_repo,
            occurrence_repo=occurrence_repo,
            parse_log_repo=parse_log_repo,
            manual_mapping_repo=mapping_repo,
        )
        buffer.stage_title_and_occurrence(
            "title-b",
            self.make_title("title-b"),
            "occurrence-b",
            self.make_occurrence("occurrence-b"),
            self.make_run(),
        )
        buffer.stage_title_and_occurrence(
            "title-a",
            self.make_title("title-a"),
            "occurrence-a",
            self.make_occurrence("occurrence-a"),
            self.make_run(),
        )
        buffer.stage_parse_log(self.make_log("log-1"))
        mapping = ManualMapping(
            id="mapping-1",
            raw_title="Mapped Film",
            imdb_id="tt0000001",
            created_at=self.now,
        )
        mapping_repo.set(mapping)
        buffer.load_manual_mappings()
        buffer.stage_manual_mapping(mapping)

        buffer.flush_parse_logs({"parse_log_write": 0.0})
        buffer.flush_pending_db_upserts({"db_upsert": 0.0})

        self.assertEqual([item[0] for item in title_repo.batches[0]], ["title-b", "title-a"])
        self.assertEqual(
            [item[1] for item in occurrence_repo.batches[0]],
            ["occurrence-b", "occurrence-a"],
        )
        self.assertEqual([item.id for item in parse_log_repo.get_all()], ["log-1"])
        self.assertEqual(buffer.pending_titles, {})
        self.assertEqual(buffer.pending_occurrences, {})
        self.assertEqual(buffer.pending_parse_logs, [])
        self.assertEqual(buffer.pending_manual_mappings, {})
        self.assertEqual(mapping_repo.get_all(), [])

    def test_repository_exception_keeps_unsuccessful_pending_writes(self):
        occurrence_repo = RecordingOccurrenceRepository(fail=True)
        buffer = self.make_buffer(occurrence_repo=occurrence_repo)
        mapping = ManualMapping(
            id="mapping-1",
            raw_title="Mapped Film",
            imdb_id="tt0000001",
            created_at=self.now,
        )
        buffer.stage_title_and_occurrence(
            "title-id",
            self.make_title("title-id"),
            "occurrence-id",
            self.make_occurrence("occurrence-id"),
            self.make_run(),
        )
        buffer.stage_manual_mapping(mapping)

        with self.assertRaisesRegex(RuntimeError, "simulated occurrence write failure"):
            buffer.flush_pending_db_upserts()

        self.assertEqual(buffer.pending_titles, {})
        self.assertIn(("title-id", "occurrence-id"), buffer.pending_occurrences)
        self.assertIn("mapping-1", buffer.pending_manual_mappings)

    def test_dry_run_and_parse_only_do_not_persist_staged_data(self):
        dry_buffer = self.make_buffer(is_dry_run=True)
        dry_buffer.stage_title_and_occurrence(
            "title-id",
            self.make_title("title-id"),
            "occurrence-id",
            self.make_occurrence("occurrence-id"),
            self.make_run(),
        )
        dry_buffer.stage_parse_log(self.make_log("dry-log"))
        dry_buffer.flush_parse_logs({"parse_log_write": 0.0})
        dry_buffer.flush_pending_db_upserts({"db_upsert": 0.0})
        self.assertEqual(dry_buffer.pending_titles, {})
        self.assertEqual(dry_buffer.pending_occurrences, {})
        self.assertEqual(dry_buffer.pending_parse_logs, [])

        parse_only_buffer = self.make_buffer(is_parse_only=True)
        parse_only_buffer.stage_parse_log(self.make_log("parse-only-log"))
        parse_only_buffer.flush_parse_logs({"parse_log_write": 0.0})
        self.assertEqual(parse_only_buffer.pending_parse_logs, [parse_only_buffer.pending_parse_logs[0]])


if __name__ == "__main__":
    unittest.main()