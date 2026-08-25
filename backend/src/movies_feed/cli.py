import argparse
import datetime
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, Mapping, Optional, Sequence

from .firestore_repository import (
    FirestoreOccurrenceRepository,
    FirestoreOmdbCacheRepository,
    FirestoreParseLogRepository,
    FirestoreScanRunRepository,
    FirestoreTitleRepository,
    FirestoreManualMappingRepository,
    get_firestore_client,
)
from .omdb_client import OmdbClient
from .ai_matcher import AiMatcher
from .scanner import ScannerConfig, ScannerService
from .repository import (
    FakeOccurrenceRepository,
    FakeOmdbCacheRepository,
    FakeParseLogRepository,
    FakeScanRunRepository,
    FakeTitleRepository,
    FakeManualMappingRepository,
)

logger = logging.getLogger(__name__)

SUPPORTED_MODES = frozenset({"rss", "recheck-existing", "reparse-unfound", "all"})
AI_MODES = frozenset({"recheck-existing", "reparse-unfound", "all"})
OMDB_MODES = frozenset({"rss", "recheck-existing", "reparse-unfound", "all"})
MAX_SCANNER_DAYS = 30
MAX_SETTINGS_FEEDS = 20
MAX_SETTINGS_LIST_ITEMS = 100
MAX_SETTINGS_TEXT_LENGTH = 500

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_PARTIAL = 2
EXIT_CONFIGURATION_ERROR = EXIT_FAILURE


class ConfigurationError(ValueError):
    """Raised when scanner arguments or required runtime configuration are invalid."""


def _has_value(environment: Mapping[str, str], name: str) -> bool:
    return bool(environment.get(name, "").strip())


def _parse_bounded_days(value: Any, option_name: str) -> int:
    raw_value = str(value)
    if not re.fullmatch(r"[0-9]+", raw_value):
        raise ConfigurationError(
            f"{option_name} must be a decimal integer from 0 to {MAX_SCANNER_DAYS}"
        )
    try:
        parsed_value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{option_name} must be a decimal integer from 0 to {MAX_SCANNER_DAYS}"
        ) from exc
    if parsed_value > MAX_SCANNER_DAYS:
        raise ConfigurationError(
            f"{option_name} must be a decimal integer from 0 to {MAX_SCANNER_DAYS}"
        )
    return parsed_value


def validate_runtime_configuration(
    *,
    mode: str,
    force_days: Any,
    audit_days: Any,
    parse_only: bool = False,
    fake_repos: bool = False,
    environment: Optional[Mapping[str, str]] = None,
) -> tuple[int, int]:
    """Validate mode, bounded inputs, and secrets without exposing secret values."""
    if mode not in SUPPORTED_MODES:
        raise ConfigurationError("mode is not supported")
    if parse_only and mode != "rss":
        raise ConfigurationError("parse-only mode is supported only with --mode rss")

    parsed_force_days = _parse_bounded_days(force_days, "force_days")
    parsed_audit_days = _parse_bounded_days(audit_days, "audit_days")
    env = environment if environment is not None else os.environ

    missing: list[str] = []
    if not fake_repos and not parse_only and not (
        _has_value(env, "FIREBASE_SERVICE_ACCOUNT")
        or _has_value(env, "GOOGLE_APPLICATION_CREDENTIALS")
        or _has_value(env, "FIRESTORE_EMULATOR_HOST")
    ):
        missing.append("Firebase credentials")
    if mode in OMDB_MODES and not parse_only and not _has_value(env, "OMDB_API_KEY"):
        missing.append("OMDB_API_KEY")
    if mode in AI_MODES and not _has_value(env, "GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")

    if missing:
        raise ConfigurationError(
            "Missing required scanner configuration: " + ", ".join(missing)
        )
    return parsed_force_days, parsed_audit_days


def exit_code_for_status(status: str) -> int:
    """Map the persisted ScanRun status to the process result used by CI."""
    if status == "succeeded":
        return EXIT_SUCCESS
    if status == "partial":
        return EXIT_PARTIAL
    return EXIT_FAILURE


def _sanitize_diagnostic(message: Any, environment: Optional[Mapping[str, str]] = None) -> str:
    """Redact known secrets and URL-style API keys from CLI diagnostics."""
    env = environment if environment is not None else os.environ
    result = str(message)
    for name in ("OMDB_API_KEY", "GEMINI_API_KEY", "FIREBASE_SERVICE_ACCOUNT"):
        secret = env.get(name, "")
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return re.sub(r"([?&](?:key|apikey|api_key)=)[^&\s]+", r"\1[REDACTED]", result, flags=re.IGNORECASE)


def validate_settings_document(data: Any) -> Dict[str, Any]:
    """Validate untrusted Firestore scanner settings before they affect a run."""
    if not isinstance(data, dict):
        raise ConfigurationError("Firestore settings must be an object")

    allowed_fields = {
        "rssFeeds",
        "excludedGenres",
        "excludedCountries",
        "minMovieRating",
        "minSeriesRating",
        "minImdbVotes",
        "updatedBy",
    }
    if set(data) - allowed_fields:
        raise ConfigurationError("Firestore settings contain unsupported fields")

    feeds = data.get("rssFeeds")
    if feeds is not None:
        if not isinstance(feeds, dict) or len(feeds) > MAX_SETTINGS_FEEDS:
            raise ConfigurationError("Firestore settings contain too many RSS feeds")
        for feed_name, feed in feeds.items():
            if (
                not isinstance(feed_name, str)
                or not feed_name.strip()
                or len(feed_name) > MAX_SETTINGS_TEXT_LENGTH
                or not isinstance(feed, dict)
                or set(feed) != {"url", "type"}
                or not isinstance(feed["url"], str)
                or not 1 <= len(feed["url"]) <= 2048
                or feed["type"] not in ("movie", "series")
            ):
                raise ConfigurationError("Firestore settings contain an invalid RSS feed")

    for field_name in ("excludedGenres", "excludedCountries"):
        values = data.get(field_name)
        if values is not None:
            if not isinstance(values, list) or len(values) > MAX_SETTINGS_LIST_ITEMS:
                raise ConfigurationError(f"Firestore settings contain an invalid {field_name} list")
            if any(
                not isinstance(value, str)
                or not value.strip()
                or len(value) > MAX_SETTINGS_TEXT_LENGTH
                for value in values
            ):
                raise ConfigurationError(f"Firestore settings contain an invalid {field_name} value")

    for field_name in ("minMovieRating", "minSeriesRating"):
        value = data.get(field_name)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value <= 10
        ):
            raise ConfigurationError(f"Firestore settings contain an invalid {field_name}")

    min_votes = data.get("minImdbVotes")
    if min_votes is not None and (
        isinstance(min_votes, bool)
        or not isinstance(min_votes, int)
        or not 0 <= min_votes <= 1_000_000_000
    ):
        raise ConfigurationError("Firestore settings contain an invalid minImdbVotes")

    updated_by = data.get("updatedBy")
    if updated_by is not None and (
        not isinstance(updated_by, str) or not 0 < len(updated_by) <= 128
    ):
        raise ConfigurationError("Firestore settings contain an invalid updatedBy")

    return dict(data)

def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    parser = argparse.ArgumentParser(description="MediaDock movies feed scanner")
    parser.add_argument("--config", type=str, default="legacy/config.json", help="Path to config.json")
    parser.add_argument("--dry-run", action="store_true", help="Parse and fetch, but do not write to Firestore")
    parser.add_argument("--parse-only", action="store_true", help="Only parse RSS and titles, no OMDb requests or Firestore writes")
    parser.add_argument("--fake-repos", action="store_true", help="Use in-memory repositories instead of Firestore")
    parser.add_argument("--force-days", type=str, default="0", help="Force scan entries N days back")
    parser.add_argument("--audit-days", type=str, default="0", help="Audit existing records N days back (0 = unlimited)")
    parser.add_argument("--mode", type=str, default="rss", choices=["rss", "recheck-existing", "reparse-unfound", "all"], help="Scan mode: 'rss' (feed scan), 'recheck-existing' (AI check stored titles), 'reparse-unfound' (AI reparse unmapped titles), or 'all'")
    
    parser.add_argument("--trigger", type=str, default=None, choices=["schedule", "manual", "local"], help="Trigger type (schedule, manual, local)")
    
    args = parser.parse_args(argv)

    try:
        args.force_days, args.audit_days = validate_runtime_configuration(
            mode=args.mode,
            force_days=args.force_days,
            audit_days=args.audit_days,
            parse_only=args.parse_only,
            fake_repos=args.fake_repos,
        )
    except ConfigurationError as exc:
        logger.error("Configuration error: %s", _sanitize_diagnostic(exc))
        return EXIT_CONFIGURATION_ERROR

    try:
        config_data = load_config(args.config)
    except (OSError, ValueError, TypeError) as exc:
        logger.error("Configuration file could not be loaded (%s)", type(exc).__name__)
        return EXIT_CONFIGURATION_ERROR
    
    rss_feeds = config_data.get("rss_feeds", {})
    video_settings = config_data.get("video_settings", {})
    filters = config_data.get("filters", {})
    excluded_countries = filters.get("excluded_countries", [])
    excluded_genres = filters.get("excluded_genres", [])

    # Override with custom settings from Firestore if available
    if not args.fake_repos and not args.parse_only:
        try:
            db = get_firestore_client()
            doc_ref = db.collection("titles").document("settings_config")
            doc_snap = doc_ref.get()
            if doc_snap.exists:
                data = doc_snap.to_dict()
                try:
                    validated_settings = validate_settings_document(data)
                except ConfigurationError as exc:
                    logger.warning(
                        "Ignoring invalid Firestore settings (%s); using local configuration",
                        type(exc).__name__,
                    )
                else:
                    logger.info("Loaded custom configuration from Firestore 'titles/settings_config'.")
                    if "rssFeeds" in validated_settings:
                        rss_feeds = validated_settings["rssFeeds"]
                    if "excludedCountries" in validated_settings:
                        excluded_countries = validated_settings["excludedCountries"]
                    if "excludedGenres" in validated_settings:
                        excluded_genres = validated_settings["excludedGenres"]
        except Exception as e:
            logger.warning(
                "Could not load custom settings from Firestore titles/settings_config "
                "(falling back to legacy/config.json): %s",
                type(e).__name__,
            )

    omdb_api_key = os.environ.get("OMDB_API_KEY", "")
    omdb_client = OmdbClient(api_key=omdb_api_key or "parse-only-disabled")

    trigger = args.trigger or os.environ.get("SCANNER_TRIGGER")
    if not trigger:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            event_name = os.environ.get("GITHUB_EVENT_NAME", "")
            trigger = "schedule" if event_name == "schedule" else "manual"
        else:
            trigger = "local"

    logger.info("==================================================")
    logger.info("  MediaDock Movies Feed Scanner - Startup Log     ")
    logger.info("==================================================")
    logger.info(f" Execution Mode : '{args.mode}'")
    logger.info(f" Trigger Source : '{trigger}'")
    logger.info(f" Dry Run        : {args.dry_run}")
    logger.info(f" Parse Only     : {args.parse_only}")
    logger.info(f" Force Days     : {args.force_days}")
    logger.info(f" Audit Days     : {args.audit_days if args.audit_days > 0 else 'Unlimited (0)'}")
    logger.info(f" Fake Repos     : {args.fake_repos}")

    mode_descriptions = {
        "rss": "Standard RSS feed scan: Reads feeds, parses titles, queries OMDb, updates catalog.",
        "recheck-existing": "AI Audit & Repair mode: Audits existing DB titles with AI and fixes/prunes mismatches.",
        "reparse-unfound": "AI Reparse mode: Uses AI to re-extract and match unmapped titles from parse logs.",
        "all": "Full run: Executes RSS scan -> AI Audit & Repair -> AI Reparse sequentially.",
    }
    logger.info(f" Mode Info     : {mode_descriptions.get(args.mode, 'Unknown mode')}")
    logger.info("--------------------------------------------------")

    config = ScannerConfig(
        rss_feeds=rss_feeds,
        video_settings=video_settings,
        excluded_countries=excluded_countries,
        excluded_genres=excluded_genres,
        is_dry_run=args.dry_run,
        is_parse_only=args.parse_only,
        omdb_limit=50,  # can be configurable
        cache_ttl_days=30,
        trigger=trigger,
        force_days=args.force_days,
        audit_days=args.audit_days,
        mode=args.mode,
    )

    if args.fake_repos or args.parse_only:
        title_repo = FakeTitleRepository()
        occ_repo = FakeOccurrenceRepository()
        cache_repo = FakeOmdbCacheRepository()
        run_repo = FakeScanRunRepository()
        parse_log_repo = FakeParseLogRepository()
        manual_mapping_repo = FakeManualMappingRepository()
    else:
        db = get_firestore_client()
        title_repo = FirestoreTitleRepository(db)
        occ_repo = FirestoreOccurrenceRepository(db)
        cache_repo = FirestoreOmdbCacheRepository(db)
        run_repo = FirestoreScanRunRepository(db)
        parse_log_repo = FirestoreParseLogRepository(db)
        manual_mapping_repo = FirestoreManualMappingRepository(db)

    ai_matcher = AiMatcher()
    if ai_matcher.is_available:
        logger.info("AI matching and validation enabled via GEMINI_API_KEY.")

    scanner = ScannerService(
        config=config,
        omdb_client=omdb_client,
        title_repo=title_repo,
        occurrence_repo=occ_repo,
        cache_repo=cache_repo,
        run_repo=run_repo,
        parse_log_repo=parse_log_repo,
        manual_mapping_repo=manual_mapping_repo,
        ai_matcher=ai_matcher,
    )

    run_id = str(uuid.uuid4())
    logger.info(f"Starting scan run {run_id}")
    
    try:
        run = scanner.run(run_id)
    except Exception as exc:
        logger.error("Scanner execution failed (%s)", type(exc).__name__)
        return EXIT_FAILURE

    logger.info(f"Scan finished with status: {run.status}")
    logger.info(f"Feeds processed: {run.feeds_processed}")
    logger.info(f"Entries seen: {run.entries_seen}")
    logger.info(f"Cache hits: {run.cache_hits}")
    logger.info(f"OMDb requests: {run.omdb_requests}")
    logger.info(f"Ignored entries: {run.ignored_entries}")
    logger.info(f"Titles created: {run.titles_created}")
    logger.info(f"Occurrences created: {run.occurrences_created}")
    if run.section_timings:
        logger.info("Section Timings (seconds):")
        for sec_name, duration in run.section_timings.items():
            logger.info(f"  - {sec_name}: {duration:.4f}s")
    if run.error_count > 0:
        logger.warning(f"Errors: {run.error_count}")
        for err in run.error_summary:
            logger.warning("  - %s", _sanitize_diagnostic(err))

    return exit_code_for_status(run.status)

if __name__ == "__main__":
    raise SystemExit(main())
