import datetime
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock

try:
    from . import _test_stubs
    from .scanner_test_support import MockOmdbClient, ScannerTestBuilder, make_series_result
except ImportError:
    import _test_stubs
    from scanner_test_support import MockOmdbClient, ScannerTestBuilder, make_series_result

from movies_feed.audit_proposal import ProposalTarget, audit_proposal_from_dict
from movies_feed.metadata_resolver import MetadataOutcome, MetadataOutcomeStatus
from movies_feed.models import Occurrence, ScanRun, Title
from movies_feed.omdb_client import OmdbLimitReachedError, OmdbMovieResult, OmdbTransportError
from movies_feed.proposal_application import ProposalApplicationService
from movies_feed.repository import (
    FakeAuditProposalRepository,
    FakeOccurrenceRepository,
    FakeOmdbCacheRepository,
    FakeParseLogRepository,
    FakeScanRunRepository,
    FakeTitleRepository,
)
from movies_feed.scanner import ScannerConfig, ScannerService
from movies_feed.ids import get_source_item_id, get_title_id_v2


class TestExistingTitleAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
        self.title_repo = FakeTitleRepository()
        self.occurrence_repo = FakeOccurrenceRepository()
        self.cache_repo = FakeOmdbCacheRepository()
        self.run_repo = FakeScanRunRepository()
        self.parse_log_repo = FakeParseLogRepository()
        self.proposal_repo = FakeAuditProposalRepository()
        self.scanner_builder = ScannerTestBuilder(
            now=self.now,
            title_repo=self.title_repo,
            occurrence_repo=self.occurrence_repo,
            cache_repo=self.cache_repo,
            run_repo=self.run_repo,
            parse_log_repo=self.parse_log_repo,
            audit_proposal_repo=self.proposal_repo,
        )

        self.candidate = OmdbMovieResult(
            title="Replacement Film",
            year=1999,
            imdb_id="tt1234567",
            media_type="movie",
            rating=8.0,
            votes=1000,
            metascore=80,
            genres=["Drama"],
            countries=["USA"],
            director=None,
            plot=None,
            poster_url=None,
            runtime=None,
            awards=None,
            box_office=None,
            ratings=[],
            raw_payload={
                "Response": "True",
                "Title": "Replacement Film",
                "Year": "1999",
                "imdbID": "tt1234567",
                "Type": "movie",
            },
        )
        self.valid_movie = self.candidate

    def test_source_and_audit_logs_do_not_overwrite_each_other(self):
        scanner = self.create_scanner(ScannerConfig(), MockOmdbClient({}))
        timings = {"parse_log_write": 0.0}

        scanner._log_parse_entry(
            raw_title="Stored Film 2020",
            feed_name="Movies",
            parsed_successfully=False,
            parsed_title=None,
            parsed_year=None,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            source_feed_id="movies",
            feed_entry_id="shared-identity",
        )
        scanner._log_parse_entry(
            raw_title="Stored Film 2020",
            feed_name="Movies",
            parsed_successfully=True,
            parsed_title="Stored Film",
            parsed_year=2020,
            omdb_status="skipped",
            ignored=True,
            ignore_reason="audit_needs_review",
            audit_event_identity="movies:entry:shared-identity",
        )
        scanner._flush_parse_logs(timings)

        logs = self.parse_log_repo.get_all()
        self.assertEqual(len(logs), 2)
        self.assertEqual({log.event_kind for log in logs}, {"source", "audit_review"})

    def create_scanner(self, config: ScannerConfig, omdb_client, metadata_resolver=None) -> ScannerService:
        return self.scanner_builder.build(
            config=config,
            omdb_client=omdb_client,
            metadata_resolver=metadata_resolver,
        )

    def add_recheck_occurrence(self, title_id: str, raw_title: str = "Stored Film 2020 1080p") -> None:
        feed_entry_id = f"{title_id}-entry"
        torrent_url = f"https://example.test/{title_id}"
        occ_id = get_source_item_id("test-feed", feed_entry_id, torrent_url)
        self.occurrence_repo.upsert(
            title_id,
            occ_id,
            Occurrence(
                source_feed_id="test-feed",
                source_feed_name="Test Feed",
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                raw_title=raw_title,
                quality="1080p",
                rip_type="WEB-DL",
                first_seen_at=self.now,
                last_seen_at=self.now,
            ),
        )

    def seed_recheck_title(self, title_id: str = "t1", title: str = "Stored Film", year: int = 2020) -> Title:
        title_record = Title(
            title=title,
            normalized_title=title.lower(),
            year=year,
            media_type="movie",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
            ai_validated=False,
        )
        self.title_repo.upsert(title_id, title_record)
        self.add_recheck_occurrence(title_id, f"{title} {year} 1080p")
        return title_record

    def make_recheck_scanner(
        self,
        ai_response: Dict[int, Dict[str, Any]],
        omdb_client=None,
        is_dry_run: bool = False,
    ):
        config = ScannerConfig(
            trigger="manual",
            mode="recheck-existing",
            is_dry_run=is_dry_run,
        )
        scanner = self.create_scanner(config, omdb_client or MockOmdbClient({}))
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_recheck_matches.return_value = ai_response
        scanner.ai_matcher = mock_ai
        return scanner, mock_ai

    def test_recheck_candidate_uses_series_broadcast_range(self):
        result = make_series_result()
        scanner = self.create_scanner(ScannerConfig(mode="recheck-existing"), MockOmdbClient({"seasoned show": result}))
        run = ScanRun(started_at=self.now, finished_at=None, status="running", trigger="local")

        outcome = scanner.existing_title_audit._inspect_recheck_suggestion(
            raw_title="Seasoned Show / Сезон 5 [2012]",
            corrected_title="Seasoned Show",
            corrected_year=2012,
            corrected_media_type="series",
            run=run,
            section_timings={"omdb_api": 0.0},
            expected_source_type="series",
        )

        self.assertEqual(outcome.candidate_outcome, "valid_suggestion")
        self.assertEqual(outcome.match_reason_code, "series_season_year_in_range")
        self.assertIs(outcome.candidate, result)
        self.assertEqual(outcome.candidate.imdb_id, result.imdb_id)
        self.assertEqual(outcome.candidate.title, result.title)
        self.assertEqual(outcome.candidate.year, result.year)
        self.assertEqual(outcome.candidate.media_type, result.media_type)
        self.assertEqual(outcome.candidate.source_type, result.source_type)
        self.assertEqual(outcome.candidate.content_kind, result.content_kind)
        self.assertEqual(outcome.candidate.broadcast_range, result.broadcast_range)

    def test_recheck_rejected_candidate_has_no_target(self):
        result = make_series_result()
        scanner = self.create_scanner(
            ScannerConfig(mode="recheck-existing"),
            MockOmdbClient({"seasoned alias": result}),
        )
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_validate_omdb_matches.return_value = {
            0: {"id": 0, "is_match": False, "confidence": 0.9, "reason": "Candidate does not match"}
        }
        scanner.ai_matcher = mock_ai
        run = ScanRun(started_at=self.now, finished_at=None, status="running", trigger="local")

        outcome = scanner.existing_title_audit._inspect_recheck_suggestion(
            raw_title="Seasoned Alias / Сезон 5 [2012]",
            corrected_title="Seasoned Alias",
            corrected_year=2012,
            corrected_media_type="series",
            run=run,
            section_timings={"omdb_api": 0.0},
            expected_source_type="series",
        )

        self.assertEqual(outcome.candidate_outcome, "ai_rejected")
        self.assertIsNone(outcome.candidate)

    def test_recheck_skips_ai_validated_titles_and_persists_flag(self):
        t1 = Title(
            title="Matrix", normalized_title="matrix", year=1999, media_type="movie",
            first_seen_at=self.now, last_seen_at=self.now, updated_at=self.now,
            ai_validated=True
        )
        t2 = Title(
            title="Inception", normalized_title="inception", year=2010, media_type="movie",
            first_seen_at=self.now, last_seen_at=self.now, updated_at=self.now,
            ai_validated=False
        )
        self.title_repo.upsert("t1", t1)
        self.title_repo.upsert("t2", t2)
        self.add_recheck_occurrence("t2", "Inception 2010 1080p")

        config = ScannerConfig(trigger="manual", mode="recheck-existing")
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)

        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_recheck_matches.return_value = {
            0: {
                "id": 0,
                "is_valid_match": True,
                "confidence": 0.9,
                "reason": "Stored match is valid",
                "corrected_title": None,
                "corrected_year": None,
                "corrected_media_type": None,
            }
        }
        scanner.ai_matcher = mock_ai

        res = scanner.recheck_existing_titles()
        # Should only check 1 title (t2), because t1 was already ai_validated=True
        self.assertEqual(res["titles_checked"], 1)
        # Verify t2 is now marked ai_validated=True in repository
        updated_t2 = self.title_repo.get("t2")
        self.assertTrue(updated_t2.ai_validated)

    def test_recheck_stops_on_first_ai_error(self):
        t1 = Title(
            title="Film 1", normalized_title="film 1", year=2020, media_type="movie",
            first_seen_at=self.now, last_seen_at=self.now, updated_at=self.now,
        )
        t2 = Title(
            title="Film 2", normalized_title="film 2", year=2021, media_type="movie",
            first_seen_at=self.now, last_seen_at=self.now, updated_at=self.now,
        )
        self.title_repo.upsert("t1", t1)
        self.title_repo.upsert("t2", t2)
        self.add_recheck_occurrence("t1", "Film 1 2020 1080p")
        self.add_recheck_occurrence("t2", "Film 2 2021 1080p")

        config = ScannerConfig(trigger="manual", mode="recheck-existing")
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)

        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        # AI returns empty dict (simulating 429 error or failure)
        mock_ai.batch_recheck_matches.return_value = {}
        scanner.ai_matcher = mock_ai

        res = scanner.recheck_existing_titles()
        # On batch 1 failure, it should stop immediately
        self.assertEqual(mock_ai.batch_recheck_matches.call_count, 1)

    def seed_recency_title(self, title_id, title_seen_at, occurrences):
        self.title_repo.upsert(
            title_id,
            Title(
                title=f"Film {title_id}",
                normalized_title=f"film {title_id}",
                year=2020,
                media_type="movie",
                first_seen_at=title_seen_at,
                last_seen_at=title_seen_at,
                updated_at=title_seen_at,
                ai_validated=False,
            ),
        )
        for index, (raw_title, last_seen_at) in enumerate(occurrences):
            feed_entry_id = f"{title_id}-entry-{index}"
            torrent_url = f"https://example.test/{title_id}/{index}"
            self.occurrence_repo.upsert(
                title_id,
                get_source_item_id("test-feed", feed_entry_id, torrent_url),
                Occurrence(
                    source_feed_id="test-feed",
                    source_feed_name="Test Feed",
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    raw_title=raw_title,
                    quality="1080p",
                    rip_type="WEB-DL",
                    first_seen_at=last_seen_at,
                    last_seen_at=last_seen_at,
                ),
            )

    def make_recency_scanner(self):
        scanner = self.create_scanner(
            ScannerConfig(trigger="manual", mode="recheck-existing"),
            MockOmdbClient({}),
        )
        mock_ai = MagicMock()
        mock_ai.is_available = True

        def valid_results(items):
            return {
                item["id"]: {
                    "id": item["id"],
                    "is_valid_match": True,
                    "confidence": 0.9,
                    "reason": "Stored match is valid",
                    "corrected_title": None,
                    "corrected_year": None,
                    "corrected_media_type": None,
                }
                for item in items
            }

        mock_ai.batch_recheck_matches.side_effect = valid_results
        scanner.ai_matcher = mock_ai
        return scanner, mock_ai

    def test_recheck_filters_clusters_by_occurrence_recency_within_one_title(self):
        old_date = self.now - datetime.timedelta(days=10)
        recent_date = self.now - datetime.timedelta(days=1)
        self.seed_recency_title(
            "mixed",
            recent_date,
            [("Old Cluster 2020", old_date), ("Recent Cluster 2020", recent_date)],
        )
        scanner, mock_ai = self.make_recency_scanner()

        stats = scanner.recheck_existing_titles(audit_days=3)

        mock_ai.batch_recheck_matches.assert_called_once()
        items = mock_ai.batch_recheck_matches.call_args.args[0]
        self.assertEqual([item["id"] for item in items], [0])
        self.assertEqual([item["raw_title"] for item in items], ["Recent Cluster 2020"])
        self.assertEqual(stats["titles_checked"], 1)
        self.assertEqual(stats["clusters_checked"], 1)
        self.assertEqual(stats["validated"], 1)

    def test_recheck_includes_recent_occurrence_under_stale_title(self):
        old_date = self.now - datetime.timedelta(days=10)
        recent_date = self.now - datetime.timedelta(days=1)
        self.seed_recency_title("stale-title", old_date, [("Recent Cluster 2020", recent_date)])
        scanner, mock_ai = self.make_recency_scanner()

        stats = scanner.recheck_existing_titles(audit_days=3)

        mock_ai.batch_recheck_matches.assert_called_once()
        items = mock_ai.batch_recheck_matches.call_args.args[0]
        self.assertEqual([item["id"] for item in items], [0])
        self.assertEqual([item["raw_title"] for item in items], ["Recent Cluster 2020"])
        self.assertEqual(stats["titles_checked"], 1)
        self.assertEqual(stats["clusters_checked"], 1)
        self.assertEqual(stats["validated"], 1)

    def test_recheck_excludes_old_occurrence_under_recent_title(self):
        old_date = self.now - datetime.timedelta(days=10)
        recent_date = self.now - datetime.timedelta(days=1)
        self.seed_recency_title("recent-title", recent_date, [("Old Cluster 2020", old_date)])
        scanner, mock_ai = self.make_recency_scanner()

        stats = scanner.recheck_existing_titles(audit_days=3)

        mock_ai.batch_recheck_matches.assert_not_called()
        self.assertEqual(stats["titles_checked"], 0)
        self.assertEqual(stats["clusters_checked"], 0)
        self.assertEqual(stats["validated"], 0)

    def test_recheck_audit_days_zero_includes_all_clusters(self):
        old_date = self.now - datetime.timedelta(days=10)
        recent_date = self.now - datetime.timedelta(days=1)
        self.seed_recency_title(
            "unlimited",
            old_date,
            [("Old Cluster 2020", old_date), ("Recent Cluster 2020", recent_date)],
        )
        scanner, mock_ai = self.make_recency_scanner()

        stats = scanner.recheck_existing_titles(audit_days=0)

        items = mock_ai.batch_recheck_matches.call_args.args[0]
        self.assertEqual([item["id"] for item in items], [0, 1])
        self.assertEqual(
            [item["raw_title"] for item in items],
            ["Old Cluster 2020", "Recent Cluster 2020"],
        )
        self.assertEqual(stats["titles_checked"], 1)
        self.assertEqual(stats["clusters_checked"], 2)
        self.assertEqual(stats["validated"], 2)

    def test_recheck_stale_orphan_is_reviewed_independently_of_cluster_recency(self):
        old_date = self.now - datetime.timedelta(days=10)
        self.seed_recency_title("orphan", old_date, [])
        scanner, mock_ai = self.make_recency_scanner()

        stats = scanner.recheck_existing_titles(audit_days=3)

        mock_ai.batch_recheck_matches.assert_not_called()
        self.assertEqual(stats["titles_checked"], 1)
        self.assertEqual(stats["clusters_checked"], 0)
        self.assertEqual(stats["orphans"], 1)
        self.assertEqual(stats["needs_review"], 1)
        log = self.parse_log_repo.get_all()[0]
        self.assertEqual(log.trace_details["auditOutcome"], "orphan")

    def test_recheck_missing_ai_item_id_is_non_destructive_and_partial(self):
        self.seed_recheck_title("t1", "Stored Film 1", 2020)
        self.seed_recheck_title("t2", "Stored Film 2", 2021)
        before_titles = dict(self.title_repo.list_all_ids_and_titles())
        before_occurrences = {
            title_id: self.occurrence_repo.list_by_title(title_id)
            for title_id in ("t1", "t2")
        }
        scanner, _ = self.make_recheck_scanner({0: {"id": 0, "is_valid_match": True, "confidence": 0.9}})

        run = scanner.run("recheck_missing_id")

        self.assertEqual(run.status, "partial")
        self.assertGreater(run.error_count, 0)
        self.assertEqual(before_titles, dict(self.title_repo.list_all_ids_and_titles()))
        for title_id, occurrences in before_occurrences.items():
            self.assertEqual(occurrences, self.occurrence_repo.list_by_title(title_id))
        logs = self.parse_log_repo.get_all()
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(log.decision == "needs_review" for log in logs))
        self.assertTrue(all(log.trace_details["auditOutcome"] == "ai_batch_incomplete" for log in logs))

    def test_recheck_missing_ai_fields_is_non_destructive(self):
        self.seed_recheck_title()
        before_title = self.title_repo.get("t1")
        before_occurrences = self.occurrence_repo.list_by_title("t1")
        scanner, _ = self.make_recheck_scanner({0: {"id": 0, "is_valid_match": True}})

        run = scanner.run("recheck_missing_field")

        self.assertEqual(run.status, "partial")
        self.assertEqual(before_title, self.title_repo.get("t1"))
        self.assertEqual(before_occurrences, self.occurrence_repo.list_by_title("t1"))
        self.assertEqual(self.parse_log_repo.get_all()[0].decision, "needs_review")

    def test_recheck_empty_ai_batch_is_non_destructive(self):
        self.seed_recheck_title()
        before_title = self.title_repo.get("t1")
        before_occurrences = self.occurrence_repo.list_by_title("t1")
        scanner, mock_ai = self.make_recheck_scanner({})

        run = scanner.run("recheck_empty_batch")

        self.assertEqual(run.status, "partial")
        self.assertEqual(mock_ai.batch_recheck_matches.call_count, 1)
        self.assertEqual(before_title, self.title_repo.get("t1"))
        self.assertEqual(before_occurrences, self.occurrence_repo.list_by_title("t1"))
        self.assertEqual(self.parse_log_repo.get_all()[0].decision, "needs_review")

    def test_recheck_low_confidence_ai_result_is_non_destructive(self):
        self.seed_recheck_title()
        before_title = self.title_repo.get("t1")
        before_occurrences = self.occurrence_repo.list_by_title("t1")
        scanner, _ = self.make_recheck_scanner({
            0: {
                "id": 0,
                "is_valid_match": True,
                "confidence": 0.2,
                "reason": "Low confidence",
                "corrected_title": None,
                "corrected_year": None,
                "corrected_media_type": None,
            }
        })

        run = scanner.run("recheck_low_confidence")

        self.assertEqual(run.status, "partial")
        self.assertEqual(before_title, self.title_repo.get("t1"))
        self.assertEqual(before_occurrences, self.occurrence_repo.list_by_title("t1"))
        self.assertEqual(self.parse_log_repo.get_all()[0].decision, "needs_review")

    def test_recheck_orphan_is_not_sent_to_ai_and_needs_review(self):
        title_record = Title(
            title="Orphan Film",
            normalized_title="orphan film",
            year=2020,
            media_type="movie",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
            ai_validated=False,
        )
        self.title_repo.upsert("orphan", title_record)
        before_title = self.title_repo.get("orphan")
        scanner, mock_ai = self.make_recheck_scanner({
            0: {
                "id": 0,
                "is_valid_match": True,
                "confidence": 0.9,
                "reason": "Stored match is valid",
                "corrected_title": None,
                "corrected_year": None,
                "corrected_media_type": None,
            }
        })

        run = scanner.run("recheck_orphan")

        self.assertEqual(run.status, "succeeded")
        mock_ai.batch_recheck_matches.assert_not_called()
        self.assertEqual(before_title, self.title_repo.get("orphan"))
        self.assertEqual(self.occurrence_repo.list_by_title("orphan"), [])
        log = self.parse_log_repo.get_all()[0]
        self.assertEqual(log.decision, "needs_review")
        self.assertEqual(log.trace_details["auditOutcome"], "orphan")

    def test_recheck_missing_corrected_title_is_review_only(self):
        self.seed_recheck_title()
        before_title = self.title_repo.get("t1")
        before_occurrences = self.occurrence_repo.list_by_title("t1")
        omdb = MockOmdbClient({"replacement": self.valid_movie})
        scanner, _ = self.make_recheck_scanner(
            {
                0: {
                    "id": 0,
                    "is_valid_match": False,
                    "confidence": 0.9,
                    "reason": "Stored match is unrelated",
                    "corrected_title": None,
                    "corrected_year": None,
                    "corrected_media_type": None,
                }
            },
            omdb,
        )

        run = scanner.run("recheck_missing_correction")

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(omdb.request_count, 0)
        self.assertEqual(before_title, self.title_repo.get("t1"))
        self.assertEqual(before_occurrences, self.occurrence_repo.list_by_title("t1"))
        log = self.parse_log_repo.get_all()[0]
        self.assertEqual(log.decision, "needs_review")
        self.assertEqual(log.trace_details["omdbOutcome"], "missing_corrected_title")
        proposal = self.proposal_repo.list_all()[0]
        self.assertEqual(proposal.action_kind, "review_only")
        self.assertIsNone(proposal.target)
        self.assertEqual(proposal.proposed_metadata, {})

    def test_recheck_omdb_outcomes_are_distinguishable_and_non_destructive(self):
        cases = (
            ("timeout", OmdbTransportError("timeout"), "transport_error", "partial"),
            ("quota", OmdbLimitReachedError("quota"), "quota_exhausted", "partial"),
            ("no_match", None, "confirmed_not_found", "succeeded"),
            ("malformed", "malformed payload", "malformed_result", "partial"),
        )
        for name, omdb_error, expected_outcome, expected_status in cases:
            with self.subTest(name=name):
                self.setUp()
                self.seed_recheck_title()
                before_title = self.title_repo.get("t1")
                before_occurrences = self.occurrence_repo.list_by_title("t1")
                responses = {"replacement": omdb_error} if omdb_error else {}
                scanner, _ = self.make_recheck_scanner(
                    {
                        0: {
                            "id": 0,
                            "is_valid_match": False,
                            "confidence": 0.9,
                            "corrected_title": "Replacement",
                            "corrected_year": 2020,
                            "corrected_media_type": "movie",
                            "reason": "Stored match is unrelated",
                        }
                    },
                    MockOmdbClient(responses),
                )

                run = scanner.run(f"recheck_omdb_{name}")

                self.assertEqual(run.status, expected_status)
                self.assertEqual(before_title, self.title_repo.get("t1"))
                self.assertEqual(before_occurrences, self.occurrence_repo.list_by_title("t1"))
                log = self.parse_log_repo.get_all()[0]
                self.assertEqual(log.decision, "needs_review")
                self.assertEqual(log.trace_details["omdbOutcome"], expected_outcome)

    def test_recheck_valid_replacement_suggestion_is_retained(self):
        self.seed_recheck_title()
        before_title = self.title_repo.get("t1")
        before_occurrences = self.occurrence_repo.list_by_title("t1")
        scanner, mock_ai = self.make_recheck_scanner(
            {
                0: {
                    "id": 0,
                    "is_valid_match": False,
                    "confidence": 0.9,
                    "corrected_title": "Replacement",
                    "corrected_year": 1999,
                    "corrected_media_type": "movie",
                    "reason": "Stored match is unrelated",
                }
            },
            MockOmdbClient({"replacement": self.valid_movie}),
        )
        mock_ai.batch_validate_omdb_matches.return_value = {
            0: {"id": 0, "is_match": True, "confidence": 0.9, "reason": "Candidate matches"}
        }

        run = scanner.run("recheck_replacement_suggestion")

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.error_count, 0)
        self.assertEqual(before_title, self.title_repo.get("t1"))
        self.assertEqual(before_occurrences, self.occurrence_repo.list_by_title("t1"))
        self.assertEqual(len(self.title_repo.list_all_ids_and_titles()), 1)
        log = self.parse_log_repo.get_all()[0]
        self.assertEqual(log.decision, "needs_review")
        self.assertEqual(log.trace_details["candidateOutcome"], "valid_suggestion")

    def test_recheck_dry_run_does_not_mutate_shared_fake_models(self):
        original_title = Title(
            title="Dry Run Film",
            normalized_title="dry run film",
            year=2020,
            media_type="movie",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
            ai_validated=False,
        )
        original_occurrence = Occurrence(
            source_feed_id="test-feed",
            source_feed_name="Test Feed",
            feed_entry_id="dry-run-entry",
            torrent_url="https://example.test/dry-run",
            raw_title="Dry Run Film 2020 1080p",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.now,
            last_seen_at=self.now,
        )
        self.title_repo.upsert("dry-run", original_title)
        self.occurrence_repo.upsert("dry-run", "dry-run-occurrence", original_occurrence)
        before_title = self.title_repo.get("dry-run")
        before_occurrences = self.occurrence_repo.list_by_title("dry-run")
        scanner, _ = self.make_recheck_scanner(
            {
                0: {
                    "id": 0,
                    "is_valid_match": True,
                    "confidence": 0.9,
                    "reason": "Stored match is valid",
                    "corrected_title": None,
                    "corrected_year": None,
                    "corrected_media_type": None,
                }
            },
            is_dry_run=True,
        )

        run = scanner.run("recheck_dry_run")

        self.assertEqual(run.status, "succeeded")
        self.assertFalse(original_title.ai_validated)
        self.assertEqual(before_title, self.title_repo.get("dry-run"))
        self.assertEqual(before_occurrences, self.occurrence_repo.list_by_title("dry-run"))

    def test_changed_target_identity_clears_occurrence_and_title_validation(self):
        title_id = "target-change"
        occurrence_id = "target-change-occurrence"
        validated_at = self.now - datetime.timedelta(days=1)
        self.title_repo.upsert(
            title_id,
            Title(
                title="Stored Film",
                normalized_title="stored film",
                year=2020,
                media_type="movie",
                first_seen_at=self.now,
                last_seen_at=self.now,
                updated_at=self.now,
                imdb_id="tt0000001",
                ai_validated=True,
                ai_checked_at=validated_at,
            ),
        )
        validated_occurrence = Occurrence(
            source_feed_id="test-feed",
            source_feed_name="Test Feed",
            feed_entry_id="target-change-entry",
            torrent_url="https://example.test/target-change",
            raw_title="Stored Film 2020 1080p",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.now,
            last_seen_at=self.now,
            validation_status="valid",
            validation_policy_version="v1",
            validated_at=validated_at,
            validation_reason="Stored match is valid",
        )
        self.occurrence_repo.upsert(title_id, occurrence_id, validated_occurrence)
        scanner = self.create_scanner(ScannerConfig(), MockOmdbClient({}))
        changed_target = Title(
            title="Replacement Film",
            normalized_title="replacement film",
            year=1999,
            media_type="movie",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
            imdb_id="tt1234567",
        )
        incoming_occurrence = Occurrence(
            source_feed_id="test-feed",
            source_feed_name="Test Feed",
            feed_entry_id="target-change-entry",
            torrent_url="https://example.test/target-change",
            raw_title="Stored Film 2020 1080p",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.now,
            last_seen_at=self.now + datetime.timedelta(hours=1),
        )

        scanner.write_buffer.stage_title_and_occurrence(
            title_id,
            changed_target,
            occurrence_id,
            incoming_occurrence,
            ScanRun(started_at=self.now, finished_at=None, status="running", trigger="test"),
        )

        staged_title = scanner.write_buffer.pending_titles[title_id]
        staged_occurrence = scanner.write_buffer.pending_occurrences[(title_id, occurrence_id)]
        self.assertFalse(staged_title.ai_validated)
        self.assertIsNone(staged_title.ai_checked_at)
        self.assertIsNone(staged_occurrence.validation_status)
        self.assertIsNone(staged_occurrence.validation_policy_version)
        self.assertIsNone(staged_occurrence.validated_at)
        self.assertIsNone(staged_occurrence.validation_reason)

    def _seed_source(self) -> None:
        self.title_repo.upsert(
            "source-title",
            Title(
                title="Stored Film",
                normalized_title="stored film",
                year=2020,
                media_type="movie",
                first_seen_at=self.now,
                last_seen_at=self.now,
                updated_at=self.now,
                ai_validated=False,
            ),
        )
        self.occurrence_repo.upsert(
            "source-title",
            get_source_item_id("test-feed", "source-entry", "https://example.test/source"),
            Occurrence(
                source_feed_id="test-feed",
                source_feed_name="Test Feed",
                feed_entry_id="source-entry",
                torrent_url="https://example.test/source",
                raw_title="Replacement Film 1999 1080p",
                quality="1080p",
                rip_type="WEB-DL",
                first_seen_at=self.now,
                last_seen_at=self.now,
            ),
        )

    def _seed_source_cluster(self, occurrence_count: int):
        self.title_repo.upsert(
            "source-title",
            Title(
                title="Stored Film",
                normalized_title="stored film",
                year=2020,
                media_type="movie",
                first_seen_at=self.now,
                last_seen_at=self.now,
                updated_at=self.now,
                ai_validated=False,
            ),
        )
        occurrence_ids = []
        for index in reversed(range(occurrence_count)):
            feed_entry_id = f"source-entry-{index:03d}"
            torrent_url = f"https://example.test/source-{index:03d}"
            occurrence_id = get_source_item_id("test-feed", feed_entry_id, torrent_url)
            occurrence_ids.append(occurrence_id)
            self.occurrence_repo.upsert(
                "source-title",
                occurrence_id,
                Occurrence(
                    source_feed_id="test-feed",
                    source_feed_name="Test Feed",
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    raw_title="Replacement Film 1999 1080p",
                    quality="1080p",
                    rip_type="WEB-DL",
                    first_seen_at=self.now,
                    last_seen_at=self.now,
                ),
            )
        return sorted(occurrence_ids)

    def _make_scanner(self) -> ScannerService:
        metadata_resolver = MagicMock()
        metadata_resolver.http_attempts = 0
        metadata_resolver.resolve_title.return_value = MetadataOutcome(
            status=MetadataOutcomeStatus.FOUND,
            result=self.candidate,
        )
        scanner = self.scanner_builder.build(
            config=ScannerConfig(trigger="manual", mode="recheck-existing"),
            omdb_client=MockOmdbClient({"replacement film": self.candidate}),
            metadata_resolver=metadata_resolver,
        )
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_recheck_matches.return_value = {
            0: {
                "id": 0,
                "is_valid_match": False,
                "corrected_title": "Replacement Film",
                "corrected_year": 1999,
                "corrected_media_type": "movie",
                "reason": "Stored match is unrelated",
                "confidence": 0.9,
            }
        }
        scanner.ai_matcher = mock_ai
        return scanner

    def test_scanner_proposal_is_consumable_by_application_service(self) -> None:
        self._seed_source()
        scanner = self._make_scanner()

        stats = scanner.recheck_existing_titles()

        self.assertEqual(stats["mismatches_found"], 1)
        self.assertEqual(stats["proposals"], 1)
        proposal = self.proposal_repo.list_all()[0]
        self.assertEqual(proposal.action_kind, "repair")
        self.assertIsInstance(proposal.target, ProposalTarget)
        self.assertEqual(proposal.target.to_dict(), proposal.proposed_metadata)
        self.assertEqual(proposal.proposed_metadata["title"], self.candidate.title)
        audit_log = self.parse_log_repo.get_all()[0]
        self.assertEqual(audit_log.trace_details["candidateOutcome"], "valid_suggestion")

        proposal = audit_proposal_from_dict(proposal.to_dict())
        proposal.status = "approved"
        self.proposal_repo.upsert(proposal)
        self.assertEqual(self.proposal_repo.get(proposal.id).status, "approved")

        service = ProposalApplicationService(
            self.proposal_repo,
            self.title_repo,
            self.occurrence_repo,
            clock=lambda: self.now,
        )
        result = service.apply_proposal(proposal.id)

        expected_target_id = get_title_id_v2(
            self.candidate.imdb_id,
            self.candidate.title,
            self.candidate.year,
            self.candidate.media_type,
        )
        self.assertEqual(result.outcome, "applied")
        self.assertEqual(result.target_title_id, expected_target_id)
        target = self.title_repo.get(expected_target_id)
        self.assertIsNotNone(target)
        self.assertEqual(target.title, self.candidate.title)
        self.assertEqual(target.year, self.candidate.year)
        self.assertEqual(target.media_type, self.candidate.media_type)
        self.assertEqual(target.imdb_id, self.candidate.imdb_id)

    def test_same_raw_title_on_two_feeds_creates_distinct_proposals(self) -> None:
        self._seed_source()
        self.occurrence_repo.upsert(
            "source-title",
            get_source_item_id("alternate-feed", "source-entry", "https://example.test/alternate"),
            Occurrence(
                source_feed_id="alternate-feed",
                source_feed_name="Alternate Feed",
                feed_entry_id="source-entry",
                torrent_url="https://example.test/alternate",
                raw_title="Replacement Film 1999 1080p",
                quality="1080p",
                rip_type="WEB-DL",
                first_seen_at=self.now,
                last_seen_at=self.now,
            ),
        )
        scanner = self._make_scanner()
        mismatch = scanner.ai_matcher.batch_recheck_matches.return_value[0]
        second_mismatch = dict(mismatch)
        second_mismatch["id"] = 1
        scanner.ai_matcher.batch_recheck_matches.return_value = {0: mismatch, 1: second_mismatch}

        stats = scanner.recheck_existing_titles()

        proposals = self.proposal_repo.list_all()
        self.assertEqual(stats["proposals"], 2)
        self.assertEqual(len(proposals), 2)
        self.assertEqual(len({proposal.id for proposal in proposals}), 2)
        self.assertEqual(
            {proposal.evidence["source_feed_name"] for proposal in proposals},
            {"Test Feed", "Alternate Feed"},
        )

    def test_unchanged_audit_rerun_reuses_proposal_identity(self) -> None:
        self._seed_source()
        scanner = self._make_scanner()

        scanner.recheck_existing_titles()
        first_proposal = self.proposal_repo.list_all()[0]
        scanner.recheck_existing_titles()

        proposals = self.proposal_repo.list_all()
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].id, first_proposal.id)
        self.assertEqual(proposals[0].created_at, first_proposal.created_at)

    def test_changed_cluster_membership_creates_new_proposal_revision(self) -> None:
        self._seed_source()
        scanner = self._make_scanner()

        scanner.recheck_existing_titles()
        first_proposal = self.proposal_repo.list_all()[0]
        self.occurrence_repo.upsert(
            "source-title",
            get_source_item_id("test-feed", "source-entry-2", "https://example.test/source-2"),
            Occurrence(
                source_feed_id="test-feed",
                source_feed_name="Test Feed",
                feed_entry_id="source-entry-2",
                torrent_url="https://example.test/source-2",
                raw_title="Replacement Film 1999 1080p",
                quality="1080p",
                rip_type="WEB-DL",
                first_seen_at=self.now,
                last_seen_at=self.now,
            ),
        )
        scanner.recheck_existing_titles()

        proposals = self.proposal_repo.list_all()
        self.assertEqual(len(proposals), 2)
        self.assertNotEqual(proposals[0].id, proposals[1].id)
        self.assertEqual(len(first_proposal.occurrence_ids), 1)
        self.assertEqual(len(proposals[1].occurrence_ids), 2)
        self.assertEqual(proposals[1].occurrence_ids, sorted(proposals[1].occurrence_ids))

    def test_200_occurrences_create_one_bounded_proposal(self) -> None:
        expected_occurrence_ids = self._seed_source_cluster(200)
        scanner = self._make_scanner()

        stats = scanner.recheck_existing_titles()

        proposals = self.proposal_repo.list_all()
        self.assertEqual(stats["proposals"], 1)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].occurrence_ids, expected_occurrence_ids)
        self.assertLessEqual(len(proposals[0].occurrence_ids), 200)

    def test_201_occurrences_create_stable_exhaustive_chunks(self) -> None:
        expected_occurrence_ids = self._seed_source_cluster(201)
        scanner = self._make_scanner()

        first_stats = scanner.recheck_existing_titles()
        first_proposals = sorted(
            self.proposal_repo.list_all(),
            key=lambda proposal: proposal.occurrence_ids[0],
        )
        first_chunks = [proposal.occurrence_ids for proposal in first_proposals]
        first_ids = [proposal.id for proposal in first_proposals]

        self.assertEqual(first_stats["proposals"], 2)
        self.assertEqual([len(chunk) for chunk in first_chunks], [200, 1])
        self.assertEqual([item for chunk in first_chunks for item in chunk], expected_occurrence_ids)
        self.assertEqual(len(set(first_chunks[0]).intersection(first_chunks[1])), 0)
        self.assertTrue(all(len(chunk) <= 200 for chunk in first_chunks))

        scanner.recheck_existing_titles()
        rerun_proposals = sorted(
            self.proposal_repo.list_all(),
            key=lambda proposal: proposal.occurrence_ids[0],
        )
        self.assertEqual([proposal.occurrence_ids for proposal in rerun_proposals], first_chunks)
        self.assertEqual([proposal.id for proposal in rerun_proposals], first_ids)

    def test_mismatch_generation_does_not_mutate_title_or_occurrence(self) -> None:
        self._seed_source()
        before_title = self.title_repo.get("source-title")
        before_occurrences = self.occurrence_repo.list_by_title("source-title")
        scanner = self._make_scanner()

        stats = scanner.recheck_existing_titles()

        self.assertEqual(stats["mismatches_found"], 1)
        self.assertEqual(before_title, self.title_repo.get("source-title"))
        self.assertEqual(before_occurrences, self.occurrence_repo.list_by_title("source-title"))
        self.assertFalse(self.title_repo.get("source-title").ai_validated)


if __name__ == "__main__":
    unittest.main()