import argparse
import datetime
import json
import logging
import os
import uuid
from typing import Any, Dict

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

def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    parser = argparse.ArgumentParser(description="MediaDock movies feed scanner")
    parser.add_argument("--config", type=str, default="legacy/config.json", help="Path to config.json")
    parser.add_argument("--dry-run", action="store_true", help="Parse and fetch, but do not write to Firestore")
    parser.add_argument("--parse-only", action="store_true", help="Only parse RSS and titles, no OMDb requests or Firestore writes")
    parser.add_argument("--fake-repos", action="store_true", help="Use in-memory repositories instead of Firestore")
    parser.add_argument("--force-days", type=int, default=0, help="Force scan entries N days back")
    
    parser.add_argument("--trigger", type=str, default=None, choices=["schedule", "manual", "local"], help="Trigger type (schedule, manual, local)")
    
    args = parser.parse_args()

    config_data = load_config(args.config)
    
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
                logger.info("Loaded custom configuration from Firestore 'titles/settings_config'.")
                if "rssFeeds" in data:
                    rss_feeds = data["rssFeeds"]
                if "excludedCountries" in data:
                    excluded_countries = data["excludedCountries"]
                if "excludedGenres" in data:
                    excluded_genres = data["excludedGenres"]
        except Exception as e:
            logger.warning(f"Could not load custom settings from Firestore titles/settings_config (falling back to legacy/config.json): {e}")

    omdb_api_key = os.environ.get("OMDB_API_KEY", "")
    if not args.parse_only and not omdb_api_key:
        logger.warning("OMDB_API_KEY environment variable is not set. OMDb lookups will fail if attempted.")

    omdb_client = OmdbClient(api_key=omdb_api_key if omdb_api_key else "dummy")

    trigger = args.trigger or os.environ.get("SCANNER_TRIGGER")
    if not trigger:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            event_name = os.environ.get("GITHUB_EVENT_NAME", "")
            trigger = "schedule" if event_name == "schedule" else "manual"
        else:
            trigger = "local"

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

    scanner = ScannerService(
        config=config,
        omdb_client=omdb_client,
        title_repo=title_repo,
        occurrence_repo=occ_repo,
        cache_repo=cache_repo,
        run_repo=run_repo,
        parse_log_repo=parse_log_repo,
        manual_mapping_repo=manual_mapping_repo,
    )

    run_id = str(uuid.uuid4())
    logger.info(f"Starting scan run {run_id}")
    
    run = scanner.run(run_id)

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
            logger.warning(f"  - {err}")

if __name__ == "__main__":
    main()
