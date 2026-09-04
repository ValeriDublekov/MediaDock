import datetime
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import feedparser
except ImportError:
    feedparser = None

from .ids import (
    get_audit_event_id,
    get_occurrence_id_v1,
    get_rss_snapshot_id,
    get_source_item_id,
    get_title_id_v2,
    normalize_title,
)
from .match_policy import (
    MatchDecision,
    effective_source_type,
    evaluate_match,
    get_exclusion_reason as policy_get_exclusion_reason,
    normalize_source_type,
)
from .models import (
    ManualMapping,
    Occurrence,
    ParseLog,
    RssSnapshot,
    RssSnapshotItem,
    ScanRun,
    SourceContext,
    Title,
)
from .metadata_resolver import MetadataOutcome, MetadataOutcomeStatus, MetadataResolver, OmdbResolver
from .omdb_client import (
    OmdbClient,
    OmdbLimitReachedError,
    OmdbMovieResult,
)
from .repository import (
    ManualMappingRepository,
    OccurrenceRepository,
    OmdbCacheRepository,
    ParseLogRepository,
    RssSnapshotRepository,
    ScanRunRepository,
    TitleRepository,
    AuditProposalRepository,
    merge_occurrences,
    merge_titles,
    occurrence_validation_fingerprint,
)
from .rutracker_parser import ParsedTitle, iter_feed_definitions, parse_rutracker_title
from .ai_matcher import AiMatcher
from .feed_fetcher import FeedFetcher
from .scan_contracts import FeedDefinition
from .existing_title_audit import ExistingTitleAuditService
from .reparse_service import ReparseService
from .proposal_application import ProposalApplicationService, ProposalApplicationResult
from .proposal_application_store import (
    ProposalApplicationStore,
    RepositoryProposalApplicationStore,
)

logger = logging.getLogger(__name__)

@dataclass
class ScannerConfig:
    rss_feeds: Dict[str, Any] = field(default_factory=dict)
    video_settings: Dict[str, Any] = field(default_factory=dict)
    excluded_countries: List[str] = field(default_factory=list)
    excluded_genres: List[str] = field(default_factory=list)
    is_dry_run: bool = False
    is_parse_only: bool = False
    omdb_limit: int = 50
    cache_ttl_days: int = 30
    trigger: str = "manual"
    force_days: int = 0
    audit_days: int = 0  # 0 = unlimited
    mode: str = "rss"  # "rss", "recheck-existing", "reparse-unfound", "apply-proposals", "all"
    feed_file: Optional[str] = None
    feed_file_name: str = "fixture"
    feed_file_type: Optional[str] = "movie"
    proposal_id: Optional[str] = None
    reject_proposal: bool = False
    allow_same_run_chaining: bool = False


def _get_entry_datetime(entry: Any) -> Optional[datetime.datetime]:
    parsed_time = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed_time:
        try:
            return datetime.datetime(*parsed_time[:6], tzinfo=datetime.timezone.utc)
        except Exception:
            return None
    return None

@dataclass
class ParsedEntryContext:
    entry: Any
    source_context: SourceContext
    is_ignored_by_date: bool = False
    raw_title: str = ""
    parsed: Optional[ParsedTitle] = None
    lookup_year: Optional[int] = None
    expected_source_type: Optional[str] = None
    parse_error: Optional[str] = None
    feed_order: int = 0
    entry_order: int = 0

class ScannerService:
    def __init__(
        self,
        config: ScannerConfig,
        omdb_client: OmdbClient,
        title_repo: TitleRepository,
        occurrence_repo: OccurrenceRepository,
        cache_repo: OmdbCacheRepository,
        run_repo: ScanRunRepository,
        parse_log_repo: Optional[ParseLogRepository] = None,
        manual_mapping_repo: Optional[ManualMappingRepository] = None,
        audit_proposal_repo: Optional[AuditProposalRepository] = None,
        ai_matcher: Optional[AiMatcher] = None,
        now: Optional[datetime.datetime] = None,
        feed_fetcher: Optional[FeedFetcher] = None,
        metadata_resolver: Optional[MetadataResolver] = None,
        application_store: Optional[ProposalApplicationStore] = None,
        rss_snapshot_repo: Optional[RssSnapshotRepository] = None,
    ):
        self.config = config
        self.omdb_client = omdb_client
        self.title_repo = title_repo
        self.occurrence_repo = occurrence_repo
        self.cache_repo = cache_repo
        self.run_repo = run_repo
        self.parse_log_repo = parse_log_repo
        self.manual_mapping_repo = manual_mapping_repo
        self.audit_proposal_repo = audit_proposal_repo
        self.application_store = application_store
        self.rss_snapshot_repo = rss_snapshot_repo
        if self.application_store is None and self.audit_proposal_repo is not None:
            self.application_store = RepositoryProposalApplicationStore(
                self.audit_proposal_repo,
                self.title_repo,
                self.occurrence_repo,
            )
        self.ai_matcher = ai_matcher
        self.now = now or datetime.datetime.now(datetime.timezone.utc)
        self.feed_fetcher = feed_fetcher or FeedFetcher()
        self.metadata_resolver = metadata_resolver or OmdbResolver(
            omdb_client,
            cache_repo,
            cache_ttl_days=config.cache_ttl_days,
            request_limit=config.omdb_limit,
            is_dry_run=config.is_dry_run,
            now=self.now,
        )
        self._reset_session_caches()
        self.existing_title_audit = ExistingTitleAuditService(
            config=self.config,
            title_repo=self.title_repo,
            occurrence_repo=self.occurrence_repo,
            audit_proposal_repo=self.audit_proposal_repo,
            get_ai_matcher=lambda: self.ai_matcher,
            metadata_resolver=self.metadata_resolver,
            clock=lambda: self.now,
            flush_parse_logs=self._flush_parse_logs,
            log_parse_entry=self._log_parse_entry,
            record_phase_error=self._record_phase_error,
            record_metadata_outcome_failure=self._record_metadata_outcome_failure,
            sync_omdb_attempts=self._sync_omdb_attempts,
            evaluate_match_callback=self._evaluate_match,
            on_proposal_created=self._run_created_proposal_ids.add,
        )

    def _iter_scan_feed_definitions(self) -> List[FeedDefinition]:
        if self.config.feed_file:
            return [
                FeedDefinition(
                    id=self.config.feed_file_name,
                    name=self.config.feed_file_name,
                    url=None,
                    type=self.config.feed_file_type,
                )
            ]
        return list(iter_feed_definitions(self.config.rss_feeds))

    def _reset_session_caches(self) -> None:
        self._session_titles: Dict[str, Optional[Title]] = {}
        self._session_occurrences: Dict[tuple, Optional[Occurrence]] = {}
        self._pending_parse_logs: List[ParseLog] = []
        self._pending_titles: Dict[str, Title] = {}
        self._pending_occurrences: Dict[tuple[str, str], Occurrence] = {}
        self._pending_manual_mappings: Dict[str, ManualMapping] = {}
        self._manual_mappings_by_id: Dict[str, ManualMapping] = {}
        self._manual_mappings_by_raw_title: Dict[str, ManualMapping] = {}
        self._manual_mappings_by_parsed_title: Dict[str, ManualMapping] = {}
        self._run_written_title_ids: Set[str] = set()
        self._run_written_occurrence_keys: Set[Tuple[str, str]] = set()
        self._run_written_parse_log_ids: Set[str] = set()
        self._run_created_proposal_ids: Set[str] = set()
        self._rss_snapshot_candidates: Dict[str, RssSnapshotItem] = {}

    @staticmethod
    def _record_phase_error(run: Optional[ScanRun], message: str) -> None:
        if run is None:
            return
        run.error_count += 1
        if message not in run.error_summary:
            run.error_summary.append(message)

    def _sync_omdb_attempts(self, run: Optional[ScanRun]) -> None:
        if run is None:
            return
        resolver_attempts = getattr(self.metadata_resolver, "http_attempts", 0)
        run.omdb_requests = max(run.omdb_requests, resolver_attempts)

    def _record_rss_snapshot_candidate(
        self,
        title_id: str,
        source_type: str,
        feed_order: int,
        entry_order: int,
    ) -> None:
        if source_type not in ("movie", "series"):
            return
        candidate = RssSnapshotItem(
            title_id=title_id,
            source_type=source_type,
            group_order=0 if source_type == "movie" else 1,
            feed_order=feed_order,
            entry_order=entry_order,
            rss_position=-1,
        )
        existing = self._rss_snapshot_candidates.get(title_id)
        if existing is None or (
            candidate.group_order,
            candidate.feed_order,
            candidate.entry_order,
        ) < (
            existing.group_order,
            existing.feed_order,
            existing.entry_order,
        ):
            self._rss_snapshot_candidates[title_id] = candidate

    def _build_rss_snapshot_items(self) -> List[RssSnapshotItem]:
        ordered_candidates = sorted(
            self._rss_snapshot_candidates.values(),
            key=lambda item: (
                item.group_order,
                item.feed_order,
                item.entry_order,
                item.title_id,
            ),
        )
        return [
            RssSnapshotItem(
                title_id=item.title_id,
                source_type=item.source_type,
                group_order=item.group_order,
                feed_order=item.feed_order,
                entry_order=item.entry_order,
                rss_position=position,
            )
            for position, item in enumerate(ordered_candidates)
        ]

    def _publish_rss_snapshot(self, run_id: str, run: ScanRun) -> None:
        if self.rss_snapshot_repo is None or self.config.is_dry_run or self.config.is_parse_only:
            return
        if self.config.mode not in ("rss", "all"):
            return

        rss_metrics = run.phase_metrics.get("rss", {})
        expected_feed_count = len(self._iter_scan_feed_definitions())
        if (
            expected_feed_count == 0
            or run.feeds_processed != expected_feed_count
            or rss_metrics.get("status") != "succeeded"
        ):
            return

        items = self._build_rss_snapshot_items()
        snapshot = RssSnapshot(
            id=get_rss_snapshot_id(run_id),
            run_id=run_id,
            created_at=run.finished_at or self.now,
            item_count=len(items),
        )
        self.rss_snapshot_repo.publish(snapshot.id, snapshot, items)
        rss_metrics["snapshotStatus"] = "published"

    def _record_metadata_outcome_failure(
        self,
        run: Optional[ScanRun],
        outcome: MetadataOutcome,
        phase: str,
    ) -> None:
        if outcome.status in (
            MetadataOutcomeStatus.QUOTA_EXHAUSTED,
            MetadataOutcomeStatus.TRANSPORT_ERROR,
        ):
            self._record_phase_error(run, f"OMDb phase incomplete during {phase}")
            if outcome.status is MetadataOutcomeStatus.TRANSPORT_ERROR and outcome.error_message:
                self._record_phase_error(run, f"OMDb Transport Error: {outcome.error_message}")
        elif outcome.status is MetadataOutcomeStatus.UNEXPECTED_ERROR:
            self._record_phase_error(run, f"OMDb phase failed during {phase}")
        elif outcome.status is MetadataOutcomeStatus.INVALID_REQUEST:
            self._record_phase_error(run, f"OMDb phase rejected an invalid request during {phase}")
        self._sync_omdb_attempts(run)

    @staticmethod
    def _expected_source_type(feed_type: Optional[str], series_marker: bool = False) -> Optional[str]:
        normalized = normalize_source_type(feed_type)
        if normalized != "unknown":
            return normalized
        return "series" if series_marker else None

    def _evaluate_match(
        self,
        *,
        expected_source_type: Optional[str],
        omdb_result: OmdbMovieResult,
        source_year: Optional[int],
        manual_mapping: bool = False,
    ) -> MatchDecision:
        return evaluate_match(
            expected_source_type=expected_source_type,
            actual_source_type=omdb_result.source_type,
            actual_media_type=omdb_result.media_type,
            source_year=source_year,
            resolved_year=omdb_result.year,
            broadcast_range=omdb_result.broadcast_range,
            countries=omdb_result.countries,
            genres=omdb_result.genres,
            excluded_countries=self.config.excluded_countries,
            excluded_genres=self.config.excluded_genres,
            manual_mapping=manual_mapping,
        )

    @staticmethod
    def _match_trace(decision: MatchDecision, omdb_result: OmdbMovieResult) -> Dict[str, Any]:
        trace: Dict[str, Any] = {
            "matchDecision": decision.status,
            "matchReasonCode": decision.reason_code,
            "matchReason": decision.message,
            "omdbSourceType": effective_source_type(omdb_result.media_type, omdb_result.source_type),
            "omdbContentKind": omdb_result.content_kind,
        }
        if omdb_result.broadcast_range is not None:
            trace["omdbBroadcastRange"] = omdb_result.broadcast_range.to_dict()
        return trace

    @staticmethod
    def _match_ignore_reason(decision: MatchDecision) -> str:
        if decision.reason_code in ("excluded_country", "excluded_genre"):
            return "excluded_country_or_genre"
        if decision.reason_code == "type_mismatch":
            return "media_type_mismatch"
        if "year" in decision.reason_code:
            return "year_mismatch"
        return "match_ambiguous"

    @staticmethod
    def _parse_log_feed_type(log: ParseLog) -> Optional[str]:
        details = log.trace_details if isinstance(log.trace_details, dict) else {}
        for key in ("feedType", "sourceType", "feed_type"):
            normalized = normalize_source_type(details.get(key))
            if normalized != "unknown":
                return normalized
        return None

    def _load_manual_mappings(self) -> None:
        if not self.manual_mapping_repo:
            return
        mappings = self.manual_mapping_repo.get_all()
        for m in mappings:
            self._manual_mappings_by_id[m.id] = m
            if m.raw_title:
                self._manual_mappings_by_raw_title[m.raw_title.strip().lower()] = m
            if m.parsed_title:
                self._manual_mappings_by_parsed_title[normalize_title(m.parsed_title)] = m

    def _find_manual_mapping(
        self,
        *,
        source_item_id: Optional[str] = None,
        legacy_item_id: Optional[str] = None,
        raw_title: Optional[str] = None,
        parsed_title: Optional[str] = None,
    ) -> Optional[ManualMapping]:
        mapping = (
            self._manual_mappings_by_id.get(source_item_id or "")
            or self._manual_mappings_by_id.get(legacy_item_id or "")
        )
        if mapping is not None and mapping.id not in self._pending_manual_mappings:
            return mapping
        if mapping is not None:
            return None
        if raw_title:
            mapping = self._manual_mappings_by_raw_title.get(raw_title.strip().lower())
            if mapping is not None and mapping.id not in self._pending_manual_mappings:
                return mapping
            if mapping is not None:
                return None
        if parsed_title:
            mapping = self._manual_mappings_by_parsed_title.get(normalize_title(parsed_title))
            if mapping is not None and mapping.id not in self._pending_manual_mappings:
                return mapping
        return None

    def _consume_manual_mapping(self, manual_mapping: ManualMapping) -> None:
        if self.config.is_dry_run or not self.manual_mapping_repo:
            return
        self.manual_mapping_repo.delete(manual_mapping.id)
        if self._manual_mappings_by_id.get(manual_mapping.id) == manual_mapping:
            self._manual_mappings_by_id.pop(manual_mapping.id, None)
        if manual_mapping.raw_title:
            raw_key = manual_mapping.raw_title.strip().lower()
            if self._manual_mappings_by_raw_title.get(raw_key) == manual_mapping:
                self._manual_mappings_by_raw_title.pop(raw_key, None)
        if manual_mapping.parsed_title:
            parsed_key = normalize_title(manual_mapping.parsed_title)
            if self._manual_mappings_by_parsed_title.get(parsed_key) == manual_mapping:
                self._manual_mappings_by_parsed_title.pop(parsed_key, None)

    def _get_title(self, title_id: str) -> Optional[Title]:
        if title_id in self._session_titles:
            return self._session_titles[title_id]
        title = self.title_repo.get(title_id)
        self._session_titles[title_id] = title
        return title

    def _get_occurrence(self, title_id: str, occurrence_id: str) -> Optional[Occurrence]:
        key = (title_id, occurrence_id)
        if key in self._session_occurrences:
            return self._session_occurrences[key]
        occ = self.occurrence_repo.get(title_id, occurrence_id)
        self._session_occurrences[key] = occ
        return occ

    def _stage_title_and_occurrence(
        self,
        title_id: str,
        title_record: Title,
        occurrence_id: str,
        occurrence_record: Occurrence,
        run: ScanRun,
    ) -> None:
        existing_title = self._get_title(title_id)
        if existing_title is None:
            run.titles_created += 1
            merged_title = title_record
        else:
            run.titles_updated += 1
            merged_title = merge_titles(existing_title, title_record)
        self._session_titles[title_id] = merged_title
        self._pending_titles[title_id] = merged_title
        self._run_written_title_ids.add(title_id)

        existing_occ = self._get_occurrence(title_id, occurrence_id)
        if existing_occ is None:
            run.occurrences_created += 1
            merged_occ = occurrence_record
            merged_title.ai_validated = False
            merged_title.ai_checked_at = None
        else:
            run.occurrences_updated += 1
            merged_occ = merge_occurrences(existing_occ, occurrence_record)
            if (
                occurrence_validation_fingerprint(existing_occ, existing_title)
                != occurrence_validation_fingerprint(occurrence_record, merged_title)
            ):
                merged_occ.validation_status = None
                merged_occ.validation_policy_version = None
                merged_occ.validation_reason = None
                merged_occ.validated_at = None
            if existing_occ.validation_status is not None and merged_occ.validation_status is None:
                merged_title.ai_validated = False
                merged_title.ai_checked_at = None
        occ_key = (title_id, occurrence_id)
        self._session_occurrences[occ_key] = merged_occ
        self._pending_occurrences[occ_key] = merged_occ
        self._run_written_occurrence_keys.add(occ_key)

    def _flush_parse_logs(self, section_timings: Optional[Dict[str, float]] = None) -> None:
        if (
            not self._pending_parse_logs
            or not self.parse_log_repo
            or self.config.is_dry_run
            or self.config.is_parse_only
        ):
            return
        t0 = time.perf_counter()
        self.parse_log_repo.add_many(self._pending_parse_logs)
        if section_timings is not None:
            section_timings["parse_log_write"] += (time.perf_counter() - t0)
        self._pending_parse_logs.clear()

    def _flush_pending_db_upserts(self, section_timings: Optional[Dict[str, float]] = None) -> None:
        if self.config.is_dry_run:
            self._pending_titles.clear()
            self._pending_occurrences.clear()
            return

        t0 = time.perf_counter()
        if self._pending_titles:
            titles_to_upsert = [(tid, t) for tid, t in self._pending_titles.items()]
            self.title_repo.upsert_many(titles_to_upsert)
            self._pending_titles.clear()

        if self._pending_occurrences:
            occs_to_upsert = [(tid, oid, occ) for (tid, oid), occ in self._pending_occurrences.items()]
            self.occurrence_repo.upsert_many(occs_to_upsert)
            self._pending_occurrences.clear()

        pending_mappings = list(self._pending_manual_mappings.values())
        self._pending_manual_mappings.clear()
        for manual_mapping in pending_mappings:
            self._consume_manual_mapping(manual_mapping)

        if section_timings is not None:
            section_timings["db_upsert"] += (time.perf_counter() - t0)

    def get_exclusion_reason(self, countries: List[str], genres: List[str]) -> Optional[str]:
        return policy_get_exclusion_reason(
            countries,
            genres,
            self.config.excluded_countries,
            self.config.excluded_genres,
        )

    def is_excluded(self, countries: List[str], genres: List[str]) -> bool:
        return self.get_exclusion_reason(countries, genres) is not None

    def _log_parse_entry(
        self,
        raw_title: str,
        feed_name: str,
        parsed_successfully: bool,
        parsed_title: Optional[str],
        parsed_year: Optional[int],
        omdb_status: str,
        ignored: bool,
        ignore_reason: Optional[str],
        error_message: Optional[str] = None,
        feed_entry_id: Optional[str] = None,
        torrent_url: Optional[str] = None,
        section_timings: Optional[Dict[str, float]] = None,
        trace_details: Optional[Dict[str, Any]] = None,
        decision: Optional[str] = None,
        source_feed_id: Optional[str] = None,
        source_log_id: Optional[str] = None,
        audit_event_identity: Optional[str] = None,
        source_context: Optional[SourceContext] = None,
    ) -> None:
        if source_log_id is not None:
            log_id = source_log_id
            event_kind = "source"
        elif audit_event_identity is not None:
            log_id = get_audit_event_id(audit_event_identity)
            event_kind = "audit_review"
        elif source_feed_id is not None:
            log_id = get_source_item_id(source_feed_id, feed_entry_id, torrent_url)
            event_kind = "source"
        else:
            raise ValueError("source or audit identity is required for a parse log")

        self._run_written_parse_log_ids.add(log_id)

        if not self.parse_log_repo or self.config.is_dry_run:
            return

        log = ParseLog(
            id=log_id,
            raw_title=raw_title,
            feed_name=feed_name,
            parsed_successfully=parsed_successfully,
            parsed_title=parsed_title,
            parsed_year=parsed_year,
            omdb_status=omdb_status,
            ignored=ignored,
            ignore_reason=ignore_reason,
            processed_at=self.now,
            error_message=error_message,
            trace_details=trace_details,
            decision=decision,
            source_context=source_context,
            event_kind=event_kind,
        )
        self._pending_parse_logs.append(log)

    def run(self, run_id: str) -> ScanRun:
        self._reset_session_caches()
        self.metadata_resolver.start_run(
            now=self.now,
            request_limit=self.config.omdb_limit,
            is_dry_run=self.config.is_dry_run,
        )
        run = ScanRun(
            started_at=self.now,
            finished_at=None,
            status="running",
            trigger=self.config.trigger,
        )
        if self.config.is_parse_only and self.config.mode != "rss":
            run.status = "failed"
            run.error_count = 1
            run.error_summary.append("Parse-only mode supports only rss mode")
            run.finished_at = datetime.datetime.now(datetime.timezone.utc)
            return run

        if not self.config.is_parse_only:
            self._load_manual_mappings()

        if not self.config.is_dry_run and not self.config.is_parse_only:
            self.run_repo.upsert(run_id, run)

        logger.info(f"Starting scan run {run_id} [mode: '{self.config.mode}', trigger: '{self.config.trigger}']")

        section_timings = {
            "prune_logs": 0.0,
            "feed_fetch": 0.0,
            "title_parse": 0.0,
            "cache_lookup": 0.0,
            "omdb_api": 0.0,
            "db_upsert": 0.0,
            "parse_log_write": 0.0,
            "ai_recheck": 0.0,
            "ai_reparse": 0.0,
        }

        if self.parse_log_repo and not self.config.is_dry_run and not self.config.is_parse_only:
            t0 = time.perf_counter()
            cutoff = self.now - datetime.timedelta(days=7)
            self.parse_log_repo.prune_older_than(cutoff)
            t_prune = time.perf_counter() - t0
            section_timings["prune_logs"] += t_prune
            logger.info(f"Section [prune_logs]: completed in {t_prune:.4f}s")

        try:
            # 1. RSS Feed Processing (if mode is "rss" or "all")
            phase_1_metrics: Dict[str, Any] = {
                "status": "skipped",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": 0.0,
                "feeds_processed": 0,
                "entries_seen": 0,
                "titles_created": 0,
                "titles_updated": 0,
                "occurrences_created": 0,
                "occurrences_updated": 0,
                "cache_hits": 0,
                "omdb_requests": 0,
                "ignored_entries": 0,
                "errors": 0,
            }
            if self.config.mode in ("rss", "all"):
                logger.info("--> [Phase 1/4] Processing RSS feeds...")
                p1_start = datetime.datetime.now(datetime.timezone.utc)
                phase_1_metrics["started_at"] = p1_start.isoformat()
                p1_initial_errors = run.error_count
                p1_t0 = time.perf_counter()
                for feed_order, feed_def in enumerate(self._iter_scan_feed_definitions()):
                    run.feeds_processed += 1
                    try:
                        t0_feed = time.perf_counter()
                        if self.config.feed_file:
                            feed_bytes = self.feed_fetcher.fetch_file(self.config.feed_file)
                        else:
                            feed_bytes = self.feed_fetcher.fetch(feed_def.require_url())
                        feed = feedparser.parse(feed_bytes)
                        t_feed = time.perf_counter() - t0_feed
                        section_timings["feed_fetch"] += t_feed
                        entries = self.feed_fetcher.validate_parsed_feed(feed)
                        entries_cnt = len(entries)
                        logger.info(
                            f"Section [feed_fetch]: Feed '{feed_def.name}' fetched in {t_feed:.4f}s ({entries_cnt} entries)"
                        )

                        # Parse entries once, filtering by date early
                        parsed_contexts: List[ParsedEntryContext] = []
                        cache_requests_to_prefetch = []

                        cutoff = None
                        if self.config.force_days > 0:
                            cutoff = self.now - datetime.timedelta(days=self.config.force_days)

                        for entry_order, entry in enumerate(entries):
                            source_context = self._source_context_for_entry(entry, feed_def)
                            raw_title = getattr(entry, "title", "") or ""
                            
                            is_ignored = False
                            if cutoff is not None and source_context.source_published_at is not None:
                                if source_context.source_published_at < cutoff:
                                    is_ignored = True
                                    
                            ctx = ParsedEntryContext(
                                entry=entry,
                                source_context=source_context,
                                is_ignored_by_date=is_ignored,
                                raw_title=raw_title,
                                feed_order=feed_order,
                                entry_order=entry_order,
                            )
                            
                            if not is_ignored and raw_title:
                                t0_parse = time.perf_counter()
                                try:
                                    ctx.parsed = parse_rutracker_title(
                                        raw_title,
                                        content_type=feed_def.type,
                                        video_settings=self.config.video_settings,
                                    )
                                    section_timings["title_parse"] += (time.perf_counter() - t0_parse)
                                    
                                    if ctx.parsed and ctx.parsed.title:
                                        if ctx.parsed.year:
                                            try:
                                                ctx.lookup_year = int(ctx.parsed.year)
                                            except ValueError:
                                                pass
                                        ctx.expected_source_type = self._expected_source_type(
                                            feed_def.type,
                                             ctx.parsed.is_series,
                                        )
                                        cache_requests_to_prefetch.append(
                                            (ctx.parsed.title, ctx.lookup_year, ctx.expected_source_type, None)
                                        )
                                except Exception as e:
                                    section_timings["title_parse"] += (time.perf_counter() - t0_parse)
                                    logger.error(f"Error parsing rutracker title '{raw_title}': {e}", exc_info=True)
                                    ctx.parsed = ParsedTitle(title="", year=None, is_series=False, quality="", rip_type="")
                                    ctx.parse_error = f"Грешка при парсване: {e}"
                            
                            parsed_contexts.append(ctx)

                        if cache_requests_to_prefetch:
                            self.metadata_resolver.prefetch(
                                cache_requests_to_prefetch,
                                section_timings,
                            )

                        for ctx in parsed_contexts:
                            run.entries_seen += 1
                            try:
                                self._process_entry(ctx, feed_def, run, section_timings)
                            except OmdbLimitReachedError as e:
                                logger.warning(f"OMDb limit reached: {e}")
                                run.error_count += 1
                                if "OMDb API limit reached" not in run.error_summary:
                                    run.error_summary.append("OMDb API limit reached")
                                break
                            except Exception as e:
                                err_text = f"Entry error ({type(e).__name__}): {e}"
                                logger.error(f"Error processing entry {ctx.raw_title}: {err_text}", exc_info=True)
                                run.error_count += 1
                                run.error_summary.append(err_text)
                                try:
                                    self._log_parse_entry(
                                        raw_title=ctx.raw_title,
                                        feed_name=feed_def.name,
                                        parsed_successfully=False,
                                        parsed_title=None,
                                        parsed_year=None,
                                        omdb_status="error",
                                        ignored=True,
                                        ignore_reason="entry_error",
                                        error_message=err_text,
                                        feed_entry_id=getattr(ctx.entry, "id", None),
                                        torrent_url=getattr(ctx.entry, "link", None),
                                        source_feed_id=feed_def.id,
                                        source_context=ctx.source_context,
                                        section_timings=section_timings,
                                    )
                                except Exception as log_ex:
                                    logger.error(f"Failed to log entry error to parse logs: {log_ex}")

                        # Flush batch parse logs and db upserts for feed
                        self._flush_parse_logs(section_timings)
                        self._flush_pending_db_upserts(section_timings)

                    except Exception as e:
                        err_text = f"Feed error for '{feed_def.name}' ({type(e).__name__}): {e}"
                        logger.error(err_text, exc_info=True)
                        run.error_count += 1
                        run.error_summary.append(err_text)

                p1_finish = datetime.datetime.now(datetime.timezone.utc)
                p1_duration = time.perf_counter() - p1_t0
                phase_1_metrics["finished_at"] = p1_finish.isoformat()
                phase_1_metrics["duration_seconds"] = round(p1_duration, 4)
                phase_1_metrics["feeds_processed"] = run.feeds_processed
                phase_1_metrics["entries_seen"] = run.entries_seen
                phase_1_metrics["titles_created"] = run.titles_created
                phase_1_metrics["titles_updated"] = run.titles_updated
                phase_1_metrics["occurrences_created"] = run.occurrences_created
                phase_1_metrics["occurrences_updated"] = run.occurrences_updated
                phase_1_metrics["cache_hits"] = run.cache_hits
                phase_1_metrics["omdb_requests"] = run.omdb_requests
                phase_1_metrics["ignored_entries"] = run.ignored_entries
                p1_errors = run.error_count - p1_initial_errors
                phase_1_metrics["errors"] = p1_errors
                phase_1_metrics["status"] = "succeeded" if p1_errors == 0 else ("failed" if run.feeds_processed == 0 and p1_errors > 0 else "partial")
            else:
                logger.info(f"--> [Phase 1/4] RSS feed processing SKIPPED (mode is '{self.config.mode}')")
            run.phase_metrics["rss"] = phase_1_metrics

            if self.config.is_parse_only:
                logger.info("--> [Phase 2/4] AI Database Audit SKIPPED (parse-only mode)")
                logger.info("--> [Phase 3/4] AI Unmapped Reparsing SKIPPED (parse-only mode)")
                logger.info("--> [Phase 4/4] Proposal Application SKIPPED (parse-only mode)")
                run.phase_metrics["recheck_existing"] = {"status": "skipped", "started_at": None, "finished_at": None, "duration_seconds": 0.0}
                run.phase_metrics["reparse_unfound"] = {"status": "skipped", "started_at": None, "finished_at": None, "duration_seconds": 0.0}
                run.phase_metrics["apply_proposals"] = {"status": "skipped", "started_at": None, "finished_at": None, "duration_seconds": 0.0}
            else:
                # 2. AI Database Recheck & Fix (if mode is "recheck-existing" or "all")
                phase_2_metrics: Dict[str, Any] = {
                    "status": "skipped",
                    "started_at": None,
                    "finished_at": None,
                    "duration_seconds": 0.0,
                }
                if self.config.mode in ("recheck-existing", "all"):
                    logger.info("--> [Phase 2/4] AI Audit & Repair of existing database titles...")
                    p2_start = datetime.datetime.now(datetime.timezone.utc)
                    phase_2_metrics["started_at"] = p2_start.isoformat()
                    p2_initial_errors = run.error_count
                    p2_t0 = time.perf_counter()
                    excluded_titles = None
                    if not self.config.allow_same_run_chaining and self.config.mode == "all":
                        excluded_titles = set(self._run_written_title_ids)

                    recheck_stats = self.recheck_existing_titles(
                        run=run,
                        section_timings=section_timings,
                        excluded_title_ids=excluded_titles,
                    )
                    p2_duration = time.perf_counter() - p2_t0
                    section_timings["ai_recheck"] += p2_duration
                    p2_finish = datetime.datetime.now(datetime.timezone.utc)
                    phase_2_metrics["finished_at"] = p2_finish.isoformat()
                    phase_2_metrics["duration_seconds"] = round(p2_duration, 4)
                    phase_2_metrics.update(recheck_stats)
                    p2_errors = run.error_count - p2_initial_errors
                    phase_2_metrics["errors"] = p2_errors
                    if p2_errors == 0 and recheck_stats.get("ai_failures", 0) == 0 and recheck_stats.get("omdb_failures", 0) == 0:
                        phase_2_metrics["status"] = "succeeded"
                    elif recheck_stats.get("titles_checked", 0) == 0 and p2_errors > 0:
                        phase_2_metrics["status"] = "failed"
                    else:
                        phase_2_metrics["status"] = "partial"
                else:
                    logger.info(f"--> [Phase 2/4] AI Database Audit SKIPPED (mode is '{self.config.mode}')")
                run.phase_metrics["recheck_existing"] = phase_2_metrics

                # 3. AI Reparse Unfound Titles (if mode is "reparse-unfound" or "all")
                phase_3_metrics: Dict[str, Any] = {
                    "status": "skipped",
                    "started_at": None,
                    "finished_at": None,
                    "duration_seconds": 0.0,
                }
                if self.config.mode in ("reparse-unfound", "all"):
                    logger.info("--> [Phase 3/4] AI Reparsing of unmapped/unfound titles...")
                    p3_start = datetime.datetime.now(datetime.timezone.utc)
                    phase_3_metrics["started_at"] = p3_start.isoformat()
                    p3_initial_errors = run.error_count
                    p3_t0 = time.perf_counter()
                    excluded_logs = None
                    if not self.config.allow_same_run_chaining and self.config.mode == "all":
                        excluded_logs = set(self._run_written_parse_log_ids)

                    reparse_stats = self.reparse_unfound_entries(
                        run=run,
                        section_timings=section_timings,
                        excluded_log_ids=excluded_logs,
                    )
                    p3_duration = time.perf_counter() - p3_t0
                    section_timings["ai_reparse"] += p3_duration
                    p3_finish = datetime.datetime.now(datetime.timezone.utc)
                    phase_3_metrics["finished_at"] = p3_finish.isoformat()
                    phase_3_metrics["duration_seconds"] = round(p3_duration, 4)
                    phase_3_metrics.update(reparse_stats)
                    run.retries_attempted += reparse_stats.get("retryable_seen", 0)
                    run.retries_resolved += reparse_stats.get("resolved", 0)
                    run.retries_failed += reparse_stats.get("failed", 0)
                    p3_errors = run.error_count - p3_initial_errors
                    phase_3_metrics["errors"] = p3_errors
                    if p3_errors == 0 and reparse_stats.get("failed", 0) == 0:
                        phase_3_metrics["status"] = "succeeded"
                    elif reparse_stats.get("unmapped_seen", 0) == 0 and p3_errors > 0:
                        phase_3_metrics["status"] = "failed"
                    else:
                        phase_3_metrics["status"] = "partial"
                else:
                    logger.info(f"--> [Phase 3/4] AI Reparsing SKIPPED (mode is '{self.config.mode}')")
                run.phase_metrics["reparse_unfound"] = phase_3_metrics

                # 4. Apply proposals only in the explicit proposal mode.
                phase_4_metrics: Dict[str, Any] = {
                    "status": "skipped",
                    "started_at": None,
                    "finished_at": None,
                    "duration_seconds": 0.0,
                }
                if self.config.mode == "apply-proposals":
                    logger.info("--> [Phase 4/4] Applying approved audit proposals...")
                    p4_start = datetime.datetime.now(datetime.timezone.utc)
                    phase_4_metrics["started_at"] = p4_start.isoformat()
                    p4_initial_errors = run.error_count
                    p4_t0 = time.perf_counter()
                    proposal_stats = self._apply_proposals(
                        run=run,
                        section_timings=section_timings,
                    )
                    p4_duration = time.perf_counter() - p4_t0
                    section_timings["apply_proposals"] = section_timings.get("apply_proposals", 0.0) + p4_duration
                    p4_finish = datetime.datetime.now(datetime.timezone.utc)
                    phase_4_metrics["finished_at"] = p4_finish.isoformat()
                    phase_4_metrics["duration_seconds"] = round(p4_duration, 4)
                    phase_4_metrics.update(proposal_stats)
                    p4_errors = run.error_count - p4_initial_errors
                    phase_4_metrics["errors"] = p4_errors
                    if p4_errors == 0 and proposal_stats.get("proposals_failed", 0) == 0:
                        phase_4_metrics["status"] = "succeeded"
                    elif proposal_stats.get("proposals_seen", 0) == 0 and p4_errors > 0:
                        phase_4_metrics["status"] = "failed"
                    else:
                        phase_4_metrics["status"] = "partial"
                else:
                    logger.info(f"--> [Phase 4/4] Proposal Application SKIPPED (mode is '{self.config.mode}')")
                run.phase_metrics["apply_proposals"] = phase_4_metrics

            phase_statuses = [
                m.get("status") for m in run.phase_metrics.values()
                if m.get("status") != "skipped"
            ]
            if any(s == "failed" for s in phase_statuses):
                run.status = "failed"
            elif any(s == "partial" for s in phase_statuses) or run.error_count > 0:
                run.status = "partial"
            else:
                run.status = "succeeded"
        except Exception as e:
            fatal_msg = f"Fatal error during scan ({type(e).__name__}): {e}"
            logger.error(fatal_msg, exc_info=True)
            run.status = "failed"
            run.error_count += 1
            run.error_summary.append(fatal_msg)
        finally:
            run.finished_at = datetime.datetime.now(datetime.timezone.utc)
            self._flush_parse_logs(section_timings)
            self._flush_pending_db_upserts(section_timings)
            try:
                self._publish_rss_snapshot(run_id, run)
            except Exception as e:
                snapshot_error = f"RSS snapshot publication failed ({type(e).__name__})"
                logger.error(snapshot_error, exc_info=True)
                run.error_count += 1
                run.error_summary.append(snapshot_error)
                if run.status == "succeeded":
                    run.status = "partial"
            self._sync_omdb_attempts(run)
            if self.ai_matcher and self.ai_matcher.is_available:
                ai_stats = self.ai_matcher.get_stats()
                run.ai_calls = ai_stats.get("total_calls", 0)
                run.ai_items_processed = ai_stats.get("total_items_processed", 0)
                run.ai_failures = ai_stats.get("failed_calls", 0)
                logger.info(
                    f"AI Matcher Execution Summary: Calls Total={ai_stats['total_calls']} "
                    f"(Success={ai_stats['successful_calls']}, Failed={ai_stats['failed_calls']}), "
                    f"Items Processed={ai_stats['total_items_processed']}"
                )
            run.section_timings = {k: round(v, 4) for k, v in section_timings.items()}
            logger.info("Scan Section Timings Summary:")
            for sec_name, sec_time in run.section_timings.items():
                logger.info(f"  - Section '{sec_name}': {sec_time:.4f}s")
            if not self.config.is_dry_run and not self.config.is_parse_only:
                self.run_repo.upsert(run_id, run)

        return run

    def recheck_existing_titles(
        self,
        run: Optional[ScanRun] = None,
        section_timings: Optional[Dict[str, float]] = None,
        audit_days: Optional[int] = None,
        excluded_title_ids: Optional[Set[str]] = None,
    ) -> Dict[str, int]:
        stats = self.existing_title_audit.recheck_existing_titles(
            run=run,
            section_timings=section_timings,
            audit_days=audit_days,
            excluded_title_ids=excluded_title_ids,
        )
        if run:
            run.proposals_created += stats["proposals"]
        return stats

    def _recheck_existing_titles(
        self,
        run: Optional[ScanRun] = None,
        section_timings: Optional[Dict[str, float]] = None,
        excluded_title_ids: Optional[Set[str]] = None,
    ) -> Dict[str, int]:
        return self.recheck_existing_titles(
            run=run,
            section_timings=section_timings,
            excluded_title_ids=excluded_title_ids,
        )

    def reparse_unfound_entries(
        self,
        run: Optional[ScanRun] = None,
        section_timings: Optional[Dict[str, float]] = None,
        excluded_log_ids: Optional[Set[str]] = None,
    ) -> Dict[str, int]:
        if not self.parse_log_repo:
            return {
                "unmapped_seen": 0,
                "retryable_seen": 0,
                "resolved": 0,
                "retried": 0,
                "skipped": 0,
                "failed": 0,
                "reparsed_succeeded": 0,
                "reparsed_failed": 0,
            }

        self._load_manual_mappings()
        reparse_service = ReparseService(
            parse_log_repo=self.parse_log_repo,
            title_repo=self.title_repo,
            occurrence_repo=self.occurrence_repo,
            metadata_resolver=self.metadata_resolver,
            ai_matcher=self.ai_matcher,
            now=self.now,
            is_dry_run=self.config.is_dry_run,
            manual_mapping_lookup=self._find_manual_mapping,
            manual_mapping_consume=self._consume_manual_mapping,
            parse_log_feed_type=self._parse_log_feed_type,
            evaluate_match=self._evaluate_match,
            match_ignore_reason=self._match_ignore_reason,
            record_phase_error=self._record_phase_error,
            record_metadata_outcome_failure=self._record_metadata_outcome_failure,
            sync_omdb_attempts=self._sync_omdb_attempts,
        )
        return reparse_service.run(
            run=run,
            section_timings=section_timings,
            excluded_log_ids=excluded_log_ids,
        )

    def _apply_proposals(
        self,
        run: Optional[ScanRun] = None,
        section_timings: Optional[Dict[str, float]] = None,
        excluded_proposal_ids: Optional[Set[str]] = None,
    ) -> Dict[str, int]:
        stats = {
            "proposals_seen": 0,
            "proposals_applied": 0,
            "proposals_failed": 0,
            "proposals_rejected": 0,
            "proposals_skipped": 0,
        }
        if not self.application_store:
            return stats

        app_service = ProposalApplicationService(
            store=self.application_store,
            now=self.now,
        )

        proposal_id = self.config.proposal_id
        if not proposal_id:
            self._record_phase_error(run, "Proposal application requires an explicit proposal ID")
            stats["proposals_failed"] += 1
            if run:
                run.proposals_failed += 1
            return stats

        logger.info(f"Applying explicit proposal {proposal_id}")
        stats["proposals_seen"] += 1
        if excluded_proposal_ids and proposal_id in excluded_proposal_ids:
            stats["proposals_skipped"] += 1
            return stats
        res = app_service.apply_proposal(
            proposal_id,
            dry_run=self.config.is_dry_run,
            reject=self.config.reject_proposal,
        )
        logger.info(f"Proposal {proposal_id} outcome: {res.outcome} ({res.reason})")
        if res.outcome == "applied":
            stats["proposals_applied"] += 1
            if run:
                run.proposals_applied += 1
        elif res.outcome in ("failed", "ineligible", "stale"):
            stats["proposals_failed"] += 1
            if run:
                run.proposals_failed += 1
                self._record_phase_error(
                    run,
                    f"Proposal {proposal_id} failed ({res.reason_code or res.outcome})",
                )
        else:
            stats["proposals_skipped"] += 1
        return stats

    def _source_context_for_entry(
        self,
        entry: Any,
        feed_def: FeedDefinition,
    ) -> SourceContext:
        return SourceContext(
            source_feed_id=feed_def.id,
            source_feed_name=feed_def.name,
            feed_type=feed_def.type or "unknown",
            feed_entry_id=getattr(entry, "id", None),
            torrent_url=getattr(entry, "link", None),
            raw_title=getattr(entry, "title", "") or "",
            source_published_at=_get_entry_datetime(entry),
            observed_at=self.now,
        )

    def _process_entry(
        self,
        ctx: ParsedEntryContext,
        feed_def: FeedDefinition,
        run: ScanRun,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> None:
        if section_timings is None:
            section_timings = {
                "prune_logs": 0.0,
                "feed_fetch": 0.0,
                "title_parse": 0.0,
                "cache_lookup": 0.0,
                "omdb_api": 0.0,
                "db_upsert": 0.0,
                "parse_log_write": 0.0,
            }

        raw_title = ctx.raw_title
        feed_entry_id = getattr(ctx.entry, "id", None)
        torrent_url = getattr(ctx.entry, "link", "")
        feed_name = feed_def.name
        source_feed_id = feed_def.id
        source_context = ctx.source_context
        item_time = source_context.observed_at or self.now

        if ctx.is_ignored_by_date:
            run.ignored_entries += 1
            return

        if not raw_title:
            run.ignored_entries += 1
            self._log_parse_entry(
                raw_title="",
                feed_name=feed_name,
                parsed_successfully=False,
                parsed_title=None,
                parsed_year=None,
                omdb_status="not_parsed",
                ignored=True,
                ignore_reason="empty_title",
                error_message=None,
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                source_feed_id=source_feed_id,
                source_context=source_context,
                section_timings=section_timings,
            )
            return

        parsed = ctx.parsed
        parse_error = ctx.parse_error

        if not parsed or not parsed.title or parsed.confidence < 0.7:
            run.ignored_entries += 1
            if parse_error:
                run.error_count += 1
                run.error_summary.append(f"Parse error for '{raw_title}': {parse_error}")

            if not parsed or not parsed.title:
                ignore_reason = "parse_error" if parse_error else "no_title"
                error_msg = parse_error
            else:
                primary_reason = parsed.reasons[0] if parsed.reasons else "ambiguous"
                ignore_reason = f"low_confidence_parse:{primary_reason}"
                error_msg = f"Low parse confidence ({parsed.confidence:.2f}): {', '.join(parsed.reasons)}"

            trace_details = {
                "rawTitle": raw_title,
                "feedName": feed_name,
                "feedType": feed_def.type,
                "parseConfidence": parsed.confidence if parsed else 0.0,
                "parseReasons": list(parsed.reasons) if parsed else ["parse_error"],
            }
            if parsed and parsed.title:
                trace_details["parsedTitle"] = parsed.title
                trace_details["parsedYear"] = ctx.lookup_year

            self._log_parse_entry(
                raw_title=raw_title,
                feed_name=feed_name,
                parsed_successfully=False,
                parsed_title=parsed.title if (parsed and parsed.title) else None,
                parsed_year=ctx.lookup_year if parsed else None,
                omdb_status="not_parsed",
                ignored=True,
                ignore_reason=ignore_reason,
                error_message=error_msg,
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                source_feed_id=source_feed_id,
                source_context=source_context,
                section_timings=section_timings,
                trace_details=trace_details,
            )
            return

        norm_lookup_title = normalize_title(parsed.title)
        lookup_year = ctx.lookup_year

        base_trace = {
            "parsedTitle": parsed.title,
            "parsedYear": lookup_year,
            "parsedQuality": parsed.quality or None,
            "parsedRipType": parsed.rip_type or None,
            "parsedIsSeries": parsed.is_series,
            "parseConfidence": parsed.confidence,
            "parseReasons": list(parsed.reasons),
            "feedName": feed_name,
            "feedType": feed_def.type,
        }
        expected_source_type = ctx.expected_source_type
        base_trace["expectedSourceType"] = expected_source_type

        logger.info(f"[Scanner:Parse] Feed '{feed_name}' | '{raw_title}' -> Title: '{parsed.title}', Year: {lookup_year}, Quality: '{parsed.quality}', Rip: '{parsed.rip_type}', IsSeries: {parsed.is_series}")

        if self.config.is_parse_only:
            self._log_parse_entry(
                raw_title=raw_title,
                feed_name=feed_name,
                parsed_successfully=True,
                parsed_title=parsed.title,
                parsed_year=lookup_year,
                omdb_status="skipped",
                ignored=True,
                ignore_reason="parse_only",
                error_message="Режим само парсване (OMDb заявките са изключени)",
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                source_feed_id=source_feed_id,
                source_context=source_context,
                section_timings=section_timings,
                trace_details={**base_trace, "decision": "ignored_parse_only", "decisionDetails": "Parse only mode"},
            )
            return

        used_manual_mapping = False

        # Check if there is a manual IMDb mapping provided for this title
        entry_log_id = get_source_item_id(source_feed_id, feed_entry_id, torrent_url)
        legacy_entry_log_id = get_occurrence_id_v1(feed_entry_id, torrent_url)
        manual_mapping = self._find_manual_mapping(
            source_item_id=entry_log_id,
            legacy_item_id=legacy_entry_log_id,
            raw_title=raw_title,
            parsed_title=parsed.title,
        )

        if manual_mapping and manual_mapping.imdb_id:
            resolver_outcome = self.metadata_resolver.resolve_by_imdb_id(
                manual_mapping.imdb_id,
                lookup_title=parsed.title,
                lookup_year=lookup_year,
                media_type=expected_source_type,
                section_timings=section_timings,
            )
        else:
            resolver_outcome = self.metadata_resolver.resolve_title(
                parsed.title,
                lookup_year,
                media_type=expected_source_type,
                section_timings=section_timings,
            )

        self._sync_omdb_attempts(run)
        if resolver_outcome.cache_hit:
            run.cache_hits += 1

        if resolver_outcome.status is MetadataOutcomeStatus.FOUND:
            omdb_result = resolver_outcome.result
            used_manual_mapping = manual_mapping is not None and bool(manual_mapping.imdb_id)
        else:
            run.ignored_entries += 1
            self._record_metadata_outcome_failure(run, resolver_outcome, "rss")
            status = (
                "not_found"
                if resolver_outcome.status is MetadataOutcomeStatus.CONFIRMED_NOT_FOUND
                else "skipped"
                if resolver_outcome.status is MetadataOutcomeStatus.QUOTA_EXHAUSTED
                else "error"
            )
            ignore_reason = (
                "omdb_not_found"
                if resolver_outcome.status is MetadataOutcomeStatus.CONFIRMED_NOT_FOUND
                else "omdb_limit_reached"
                if resolver_outcome.status is MetadataOutcomeStatus.QUOTA_EXHAUSTED
                else "omdb_error"
            )
            if resolver_outcome.status is MetadataOutcomeStatus.CONFIRMED_NOT_FOUND:
                err_msg = (
                    f"OMDb не намери заглавие '{parsed.title}' (търсено с година: {lookup_year}, "
                    f"тип: {expected_source_type or 'всички'})"
                )
            elif resolver_outcome.status is MetadataOutcomeStatus.QUOTA_EXHAUSTED:
                err_msg = "Достигнат лимит на OMDb заявки за това сканиране"
            else:
                err_msg = resolver_outcome.error_message or "OMDb lookup failed"
            trace_details = {
                **base_trace,
                "cacheKey": resolver_outcome.cache_key,
                "cacheHit": resolver_outcome.cache_hit,
                "metadataOutcome": resolver_outcome.status.value,
                "decision": f"ignored_{resolver_outcome.status.value}",
                "decisionDetails": err_msg,
            }
            self._log_parse_entry(
                raw_title=raw_title,
                feed_name=feed_name,
                parsed_successfully=True,
                parsed_title=parsed.title,
                parsed_year=lookup_year,
                omdb_status=status,
                ignored=True,
                ignore_reason=ignore_reason,
                error_message=err_msg,
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                source_feed_id=source_feed_id,
                source_context=source_context,
                section_timings=section_timings,
                trace_details=trace_details,
            )
            if resolver_outcome.status is MetadataOutcomeStatus.QUOTA_EXHAUSTED:
                raise OmdbLimitReachedError("OMDb quota exhausted for this run")
            return

        if not omdb_result:
            return

        omdb_trace_info = {
            "omdbFoundTitle": omdb_result.title,
            "omdbFoundYear": omdb_result.year,
            "omdbFoundType": omdb_result.media_type,
            "omdbSourceType": effective_source_type(omdb_result.media_type, omdb_result.source_type),
            "omdbContentKind": omdb_result.content_kind,
            "omdbImdbId": omdb_result.imdb_id,
            "omdbGenres": omdb_result.genres,
            "omdbCountries": omdb_result.countries,
            "omdbRating": omdb_result.rating,
        }

        match_decision = self._evaluate_match(
            expected_source_type=expected_source_type,
            omdb_result=omdb_result,
            source_year=lookup_year,
            manual_mapping=used_manual_mapping,
        )
        match_trace = self._match_trace(match_decision, omdb_result)
        omdb_trace_info.update(match_trace)
        if not match_decision.is_accepted:
            run.ignored_entries += 1
            if match_decision.reason_code in ("excluded_country", "excluded_genre"):
                err_msg = f"Филтрирано по конфигурация: {match_decision.message}"
            elif match_decision.reason_code == "type_mismatch":
                actual_type = effective_source_type(omdb_result.media_type, omdb_result.source_type)
                err_msg = (
                    f"Разминаване в типа медия: RSS каналът очаква '{expected_source_type}', "
                    f"а OMDb върна '{actual_type}'"
                )
            elif match_decision.reason_code == "series_season_year_out_of_range":
                range_text = omdb_result.broadcast_range.raw if omdb_result.broadcast_range else "неизвестен диапазон"
                err_msg = (
                    f"Разминаване в годината на сезона: търсена {lookup_year}, "
                    f"OMDb диапазон '{range_text}'"
                )
            elif match_decision.reason_code == "movie_release_year_mismatch":
                err_msg = f"Разминаване в годината: търсена {lookup_year}, OMDb върна {omdb_result.year} (> 1 г. разлика)"
            else:
                err_msg = match_decision.message or "Съвпадението изисква преглед"
            logger.info(f"[Scanner:Validate] '{parsed.title}' -> {err_msg}")
            self._log_parse_entry(
                raw_title=raw_title,
                feed_name=feed_name,
                parsed_successfully=True,
                parsed_title=parsed.title,
                parsed_year=lookup_year,
                omdb_status="found",
                ignored=True,
                ignore_reason=self._match_ignore_reason(match_decision),
                error_message=err_msg,
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                source_feed_id=source_feed_id,
                source_context=source_context,
                section_timings=section_timings,
                trace_details={
                    **base_trace,
                    **omdb_trace_info,
                    "decision": f"{match_decision.status}_{match_decision.reason_code}",
                    "decisionDetails": err_msg,
                },
            )
            return

        # Record success log entry
        success_msg = f"Успешно съвпадение в OMDb ({omdb_result.imdb_id}) и преминати всички филтри"
        logger.info(f"[Scanner:Success] '{omdb_result.title}' ({omdb_result.year}) [{omdb_result.imdb_id}] -> Добавено в каталога")
        self._log_parse_entry(
            raw_title=raw_title,
            feed_name=feed_name,
            parsed_successfully=True,
            parsed_title=parsed.title,
            parsed_year=lookup_year,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            error_message=None,
            feed_entry_id=feed_entry_id,
            torrent_url=torrent_url,
            source_feed_id=source_feed_id,
            source_context=source_context,
            section_timings=section_timings,
            trace_details={
                **base_trace,
                **omdb_trace_info,
                "decision": "added_to_catalog",
                "decisionDetails": success_msg,
            },
        )

        # Prepare records
        media_type = omdb_result.media_type
        imdb_id = omdb_result.imdb_id
        source_type = effective_source_type(omdb_result.media_type, omdb_result.source_type)
        title_id = get_title_id_v2(
            imdb_id,
            omdb_result.title,
            omdb_result.year,
            source_type,
        )

        title_record = Title(
            title=omdb_result.title,
            normalized_title=normalize_title(omdb_result.title),
            year=omdb_result.year,
            media_type=media_type,
            first_seen_at=item_time,
            last_seen_at=item_time,
            updated_at=self.now,
            imdb_id=imdb_id,
            imdb_rating=omdb_result.rating,
            imdb_votes=omdb_result.votes,
            metascore=omdb_result.metascore,
            genres=omdb_result.genres,
            countries=omdb_result.countries,
            director=omdb_result.director,
            plot=omdb_result.plot,
            poster_url=omdb_result.poster_url,
            runtime=omdb_result.runtime,
            awards=omdb_result.awards,
            box_office=omdb_result.box_office,
            ratings=omdb_result.ratings,
            source_type=source_type,
            content_kind=omdb_result.content_kind,
            broadcast_range=omdb_result.broadcast_range,
        )

        occurrence_id = get_source_item_id(source_feed_id, feed_entry_id, torrent_url)

        occurrence_record = Occurrence(
            source_feed_id=source_feed_id,
            source_feed_name=feed_def.name,
            feed_entry_id=feed_entry_id,
            torrent_url=torrent_url,
            raw_title=raw_title,
            quality=parsed.quality,
            rip_type=parsed.rip_type,
            first_seen_at=item_time,
            last_seen_at=item_time,
            source_context=source_context,
        )

        # Upsert
        if not self.config.is_dry_run:
            self._stage_title_and_occurrence(title_id, title_record, occurrence_id, occurrence_record, run)
        else:
            # Simulate creation tracking for dry run without storing
            run.titles_created += 1
            run.occurrences_created += 1

        self._record_rss_snapshot_candidate(
            title_id=title_id,
            source_type=source_type,
            feed_order=ctx.feed_order,
            entry_order=ctx.entry_order,
        )

        if used_manual_mapping and manual_mapping is not None and not self.config.is_dry_run:
            self._pending_manual_mappings[manual_mapping.id] = manual_mapping
