import datetime
import os
import unittest
from unittest.mock import patch

try:
    from . import _test_stubs
    from .scanner_test_support import ScannerTestBuilder
except ImportError:
    import _test_stubs
    from scanner_test_support import ScannerTestBuilder

from movies_feed.cli import (
    ConfigurationError,
    EXIT_FAILURE,
    EXIT_PARTIAL,
    EXIT_SUCCESS,
    EXIT_CONFIGURATION_ERROR,
    _sanitize_diagnostic,
    exit_code_for_status,
    main,
    validate_settings_document,
    validate_runtime_configuration,
)
from movies_feed.ai_matcher import GeminiModelCapabilityError
from movies_feed.models import ScanRun
from movies_feed.proposal_application import ProposalApplicationResult
from movies_feed.proposal_application_store import FakeProposalApplicationStore
from movies_feed.scanner import ScannerConfig, ScannerRepositories, ScannerServices


class TestCliConfiguration(unittest.TestCase):
    def test_parse_only_rss_requires_no_scanner_secrets(self) -> None:
        result = validate_runtime_configuration(
            mode="rss",
            force_days="0",
            audit_days="0",
            parse_only=True,
            environment={},
        )
        self.assertEqual(result, (0, 0))

    def test_parse_only_rejects_all_before_any_api_configuration_check(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "only with --mode rss"):
            validate_runtime_configuration(
                mode="all",
                force_days="0",
                audit_days="0",
                parse_only=True,
                environment={},
            )

    def test_feed_file_is_restricted_to_rss_mode(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "--feed-file"):
            validate_runtime_configuration(
                mode="all",
                force_days="0",
                audit_days="0",
                feed_file="fixture.atom",
                environment={},
            )

    def test_mode_specific_secrets_are_required(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "OMDB_API_KEY"):
            validate_runtime_configuration(
                mode="rss",
                force_days="0",
                audit_days="0",
                environment={"FIREBASE_SERVICE_ACCOUNT": "configured"},
            )

        with self.assertRaisesRegex(ConfigurationError, "GEMINI_API_KEY"):
            validate_runtime_configuration(
                mode="reparse-unfound",
                force_days="0",
                audit_days="0",
                environment={
                    "FIREBASE_SERVICE_ACCOUNT": "configured",
                    "OMDB_API_KEY": "configured",
                },
            )

    def test_fake_repositories_remove_only_the_firebase_requirement(self) -> None:
        result = validate_runtime_configuration(
            mode="rss",
            force_days="1",
            audit_days="2",
            fake_repos=True,
            environment={"OMDB_API_KEY": "configured"},
        )
        self.assertEqual(result, (1, 2))

    def test_days_require_decimal_values_in_the_bounded_range(self) -> None:
        for value in ("-1", "+1", "1.0", "1e1", "31", ""):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                validate_runtime_configuration(
                    mode="rss",
                    force_days=value,
                    audit_days="0",
                    parse_only=True,
                    environment={},
                )

    def test_status_exit_codes(self) -> None:
        self.assertEqual(exit_code_for_status("succeeded"), EXIT_SUCCESS)
        self.assertEqual(exit_code_for_status("partial"), EXIT_PARTIAL)
        self.assertEqual(exit_code_for_status("failed"), EXIT_FAILURE)
        self.assertEqual(exit_code_for_status("unknown"), EXIT_FAILURE)

    def test_secret_free_diagnostics(self) -> None:
        secret = "super-secret-value"
        diagnostic = _sanitize_diagnostic(
            f"request failed?key={secret} token={secret}",
            {"OMDB_API_KEY": secret},
        )
        self.assertNotIn(secret, diagnostic)
        self.assertNotIn(f"?key={secret}", diagnostic)
        self.assertIn("[REDACTED]", diagnostic)

    def test_firestore_settings_are_validated_before_use(self) -> None:
        valid = {
            "rssFeeds": {
                "movies": {"url": "https://feed.example.test/movies.atom", "type": "movie"},
            },
            "excludedGenres": ["Horror"],
            "excludedCountries": ["India"],
            "minMovieRating": 6.5,
            "minSeriesRating": 7,
            "minImdbVotes": 0,
            "updatedBy": "admin-456",
        }
        self.assertEqual(validate_settings_document(valid), valid)

        for invalid in (
            {**valid, "extra": True},
            {**valid, "minMovieRating": 11},
            {**valid, "rssFeeds": {"movies": {"url": "https://feed.example.test/movies.atom", "type": "invalid"}}},
            {**valid, "rssFeeds": {"movies": {"url": "http://feed.example.test/movies.atom", "type": "movie"}}},
            {**valid, "excludedGenres": [""]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigurationError):
                validate_settings_document(invalid)

    def test_main_returns_status_exit_code(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        for status, expected_code in (
            ("succeeded", EXIT_SUCCESS),
            ("partial", EXIT_PARTIAL),
            ("failed", EXIT_FAILURE),
        ):
            with self.subTest(status=status):
                run = ScanRun(
                    started_at=now,
                    finished_at=now,
                    status=status,
                    trigger="local",
                )
                with patch.dict(os.environ, {"OMDB_API_KEY": "configured"}, clear=True), patch(
                    "movies_feed.cli.load_config", return_value={}
                ), patch("movies_feed.cli.ScannerService") as scanner_type:
                    scanner_type.return_value.run.return_value = run
                    self.assertEqual(
                        main(["--fake-repos", "--mode", "rss"]),
                        expected_code,
                    )

    def test_main_composes_grouped_scanner_dependencies(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        run = ScanRun(
            started_at=now,
            finished_at=now,
            status="succeeded",
            trigger="local",
        )
        with patch.dict(os.environ, {"OMDB_API_KEY": "configured"}, clear=True), patch(
            "movies_feed.cli.load_config", return_value={}
        ), patch("movies_feed.cli.ScannerService") as scanner_type:
            scanner_type.return_value.run.return_value = run
            self.assertEqual(
                main(["--fake-repos", "--mode", "rss"]),
                EXIT_SUCCESS,
            )

        scanner_kwargs = scanner_type.call_args.kwargs
        repositories = scanner_kwargs["repositories"]
        services = scanner_kwargs["services"]
        self.assertIsInstance(repositories, ScannerRepositories)
        self.assertIsInstance(services, ScannerServices)
        self.assertNotIn("title_repo", scanner_kwargs)
        self.assertIs(services.metadata_resolver.omdb_client, services.omdb_client)
        self.assertIs(services.metadata_resolver.cache_repo, repositories.cache_repo)

    def test_main_rejects_model_without_generate_content_capability(self) -> None:
        from unittest.mock import MagicMock

        matcher = MagicMock()
        matcher.is_available = True
        matcher.validate_model_capability.side_effect = GeminiModelCapabilityError("unsupported model")
        with patch.dict(
            os.environ,
            {"OMDB_API_KEY": "configured", "GEMINI_API_KEY": "configured"},
            clear=True,
        ), patch("movies_feed.cli.load_config", return_value={}), patch(
            "movies_feed.cli.AiMatcher", return_value=matcher
        ):
            self.assertEqual(
                main(["--fake-repos", "--mode", "reparse-unfound"]),
                EXIT_FAILURE,
            )

    def test_main_rejects_parse_only_with_apply_proposals(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "movies_feed.cli.load_config", return_value={}
        ):
            self.assertEqual(
                main(["--fake-repos", "--parse-only", "--mode", "apply-proposals"]),
                EXIT_CONFIGURATION_ERROR,
            )

    def test_apply_proposals_requires_an_explicit_proposal_id(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "--proposal-id"):
            validate_runtime_configuration(
                mode="apply-proposals",
                force_days="0",
                audit_days="0",
                dry_run=True,
                fake_repos=True,
                environment={},
            )

    def test_main_rejects_more_than_one_proposal_id(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "movies_feed.cli.ScannerService"
        ) as scanner_type:
            self.assertEqual(
                main([
                    "--fake-repos",
                    "--dry-run",
                    "--mode", "apply-proposals",
                    "--proposal-id", "prop-123",
                    "--proposal-id", "prop-456",
                ]),
                EXIT_CONFIGURATION_ERROR,
            )

        scanner_type.assert_not_called()

    def test_reject_proposal_requires_an_explicit_proposal_id(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "--proposal-id"):
            validate_runtime_configuration(
                mode="rss",
                force_days="0",
                audit_days="0",
                reject_proposal=True,
                fake_repos=True,
                environment={"OMDB_API_KEY": "configured"},
            )

    def test_proposal_arguments_are_restricted_to_apply_mode(self) -> None:
        for mode in ("rss", "recheck-existing", "reparse-unfound", "all"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ConfigurationError, "supported only"):
                validate_runtime_configuration(
                    mode=mode,
                    force_days="0",
                    audit_days="0",
                    proposal_id="prop-123",
                    fake_repos=True,
                    environment={"OMDB_API_KEY": "configured", "GEMINI_API_KEY": "configured"},
                )

    def test_non_dry_run_apply_accepts_one_explicit_proposal(self) -> None:
        self.assertEqual(
            validate_runtime_configuration(
                mode="apply-proposals",
                force_days="0",
                audit_days="0",
                proposal_id="prop-123",
                fake_repos=True,
                environment={},
            ),
            (0, 0),
        )

    def test_explicit_proposal_dry_run_does_not_require_the_production_gate(self) -> None:
        self.assertEqual(
            validate_runtime_configuration(
                mode="apply-proposals",
                force_days="0",
                audit_days="0",
                dry_run=True,
                proposal_id="prop-123",
                fake_repos=True,
                environment={},
            ),
            (0, 0),
        )

    def test_main_accepts_apply_proposals(self) -> None:
        run = ScanRun(
            started_at=datetime.datetime.now(datetime.timezone.utc),
            finished_at=datetime.datetime.now(datetime.timezone.utc),
            status="succeeded",
            trigger="local",
        )
        with patch.dict(os.environ, {}, clear=True), patch(
            "movies_feed.cli.load_config", return_value={}
        ), patch("movies_feed.cli.ScannerService") as scanner_type:
            scanner_type.return_value.run.return_value = run
            self.assertEqual(
                main([
                    "--fake-repos",
                    "--mode", "apply-proposals",
                    "--proposal-id", "prop-123",
                    "--reject-proposal"
                ]),
                EXIT_SUCCESS,
            )

        scanner_config = scanner_type.call_args.kwargs["config"]
        self.assertEqual(scanner_config.mode, "apply-proposals")
        self.assertEqual(scanner_config.proposal_id, "prop-123")
        self.assertTrue(scanner_config.reject_proposal)

    def test_all_mode_skips_proposal_application(self) -> None:
        scanner = ScannerTestBuilder().build(
            config=ScannerConfig(mode="all", rss_feeds={}),
            omdb_client=object(),
        )

        with patch.object(
            scanner,
            "_apply_proposals",
            side_effect=AssertionError("all mode must not apply proposals"),
        ):
            run = scanner.run("all-mode-non-destructive")

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.phase_metrics["apply_proposals"]["status"], "skipped")

    def test_apply_proposals_requires_explicit_id_and_counts_failures_truthfully(self) -> None:
        run = ScanRun(
            started_at=datetime.datetime.now(datetime.timezone.utc),
            finished_at=None,
            status="running",
            trigger="local",
        )
        scanner = ScannerTestBuilder().build(
            config=ScannerConfig(mode="apply-proposals"),
            omdb_client=object(),
            application_store=FakeProposalApplicationStore(),
        )

        stats = scanner._apply_proposals(run=run)

        self.assertEqual(stats["proposals_failed"], 1)
        self.assertEqual(stats["proposals_seen"], 0)
        self.assertEqual(run.proposals_failed, 1)
        self.assertEqual(run.error_count, 1)

    def test_stale_application_counts_as_failed_without_exposing_reason(self) -> None:
        run = ScanRun(
            started_at=datetime.datetime.now(datetime.timezone.utc),
            finished_at=None,
            status="running",
            trigger="local",
        )
        scanner = ScannerTestBuilder().build(
            config=ScannerConfig(mode="apply-proposals", proposal_id="proposal-1"),
            omdb_client=object(),
            application_store=FakeProposalApplicationStore(),
        )
        result = ProposalApplicationResult(
            "proposal-1",
            "stale",
            "sensitive occurrence details",
            reason_code="occurrence_changed",
        )

        with patch(
            "movies_feed.scanner.ProposalApplicationService.apply_proposal",
            return_value=result,
        ):
            stats = scanner._apply_proposals(run=run)

        self.assertEqual(stats["proposals_failed"], 1)
        self.assertEqual(run.proposals_failed, 1)
        self.assertEqual(run.error_summary, ["Proposal proposal-1 failed (occurrence_changed)"])

    def test_main_passes_fixture_as_separate_scanner_input(self) -> None:
        fixture_path = "backend/tests/fixtures/movies_feed.atom"
        run = ScanRun(
            started_at=datetime.datetime.now(datetime.timezone.utc),
            finished_at=datetime.datetime.now(datetime.timezone.utc),
            status="succeeded",
            trigger="local",
        )
        with patch.dict(os.environ, {}, clear=True), patch(
            "movies_feed.cli.load_config", return_value={}
        ), patch("movies_feed.cli.ScannerService") as scanner_type:
            scanner_type.return_value.run.return_value = run
            self.assertEqual(
                main([
                    "--fake-repos",
                    "--parse-only",
                    "--feed-file",
                    fixture_path,
                ]),
                EXIT_SUCCESS,
            )

        scanner_config = scanner_type.call_args.kwargs["config"]
        self.assertEqual(scanner_config.feed_file, fixture_path)
        self.assertEqual(scanner_config.rss_feeds, {})


class TestParseOnlyExecution(unittest.TestCase):
    def test_parse_only_does_not_call_omdb_or_ai(self) -> None:
        class ExplodingOmdb:
            def get_movie_info(self, *args, **kwargs):
                raise AssertionError("OMDb must not be called in parse-only mode")

            def get_by_imdb_id(self, *args, **kwargs):
                raise AssertionError("OMDb must not be called in parse-only mode")

        class ExplodingAi:
            is_available = True

            def batch_extract_titles(self, *args, **kwargs):
                raise AssertionError("AI must not be called in parse-only mode")

            def batch_recheck_matches(self, *args, **kwargs):
                raise AssertionError("AI must not be called in parse-only mode")

            def get_stats(self):
                return {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "failed_calls": 0,
                    "total_items_processed": 0,
                }

        now = datetime.datetime.now(datetime.timezone.utc)
        scanner = ScannerTestBuilder().build(
            config=ScannerConfig(
                rss_feeds={},
                feed_file="tests/fixtures/movies_feed.atom",
                is_parse_only=True,
                mode="rss",
            ),
            omdb_client=ExplodingOmdb(),
            ai_matcher=ExplodingAi(),
            now=now,
        )

        run = scanner.run("parse-only")

        self.assertEqual(run.status, "succeeded")
        self.assertGreater(run.entries_seen, 0)


if __name__ == "__main__":
    unittest.main()