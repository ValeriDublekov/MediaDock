import datetime
import os
import unittest
from unittest.mock import patch

from movies_feed.cli import (
    ConfigurationError,
    EXIT_FAILURE,
    EXIT_PARTIAL,
    EXIT_SUCCESS,
    _sanitize_diagnostic,
    exit_code_for_status,
    main,
    validate_runtime_configuration,
)
from movies_feed.models import ScanRun
from movies_feed.repository import (
    FakeOccurrenceRepository,
    FakeOmdbCacheRepository,
    FakeParseLogRepository,
    FakeScanRunRepository,
    FakeTitleRepository,
)
from movies_feed.scanner import ScannerConfig, ScannerService


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
        scanner = ScannerService(
            config=ScannerConfig(
                rss_feeds={
                    "fixture": {
                        "name": "fixture",
                        "url": "backend/tests/fixtures/movies_feed.atom",
                        "type": "movie",
                    }
                },
                is_parse_only=True,
                mode="rss",
            ),
            omdb_client=ExplodingOmdb(),
            title_repo=FakeTitleRepository(),
            occurrence_repo=FakeOccurrenceRepository(),
            cache_repo=FakeOmdbCacheRepository(),
            run_repo=FakeScanRunRepository(),
            parse_log_repo=FakeParseLogRepository(),
            ai_matcher=ExplodingAi(),
            now=now,
        )

        run = scanner.run("parse-only")

        self.assertEqual(run.status, "succeeded")
        self.assertGreater(run.entries_seen, 0)


if __name__ == "__main__":
    unittest.main()