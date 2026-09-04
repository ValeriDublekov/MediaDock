import datetime
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .ids import (
    get_audit_event_id,
    get_rss_snapshot_id,
    get_source_item_id,
)
from .match_policy import (
    MatchDecision,
    evaluate_match,
    get_exclusion_reason as policy_get_exclusion_reason,
    normalize_source_type,
)
from .models import (
    ManualMapping,
    ParseLog,
    RssSnapshot,
    ScanRun,
    SourceContext,
)
from .scan_contracts import ScanPhaseOutcome
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
)
from .ai_matcher import AiMatcher
from .feed_fetcher import FeedFetcher
from .rss_snapshot import RssSnapshotCollector
from .scan_write_buffer import ScanWriteBuffer
from .rss_ingestion import RssIngestionService
from .existing_title_audit import ExistingTitleAuditService
from .reparse_service import ReparseService
from .proposal_application import ProposalApplicationService, ProposalApplicationResult
from .proposal_application_store import ProposalApplicationStore

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


@dataclass(frozen=True)
class ScannerRepositories:
    title_repo: TitleRepository
    occurrence_repo: OccurrenceRepository
    cache_repo: OmdbCacheRepository
    run_repo: ScanRunRepository
    parse_log_repo: Optional[ParseLogRepository] = None
    manual_mapping_repo: Optional[ManualMappingRepository] = None
    audit_proposal_repo: Optional[AuditProposalRepository] = None
    rss_snapshot_repo: Optional[RssSnapshotRepository] = None


@dataclass(frozen=True)
class ScannerServices:
    omdb_client: OmdbClient
    now: datetime.datetime
    feed_fetcher: FeedFetcher
    metadata_resolver: MetadataResolver
    ai_matcher: Optional[AiMatcher] = None
    application_store: Optional[ProposalApplicationStore] = None


@dataclass(frozen=True)
class _PhaseSelection:
    mode: str
    rss: bool
    recheck_existing: bool
    reparse_unfound: bool
    apply_proposals: bool
    exclude_rss_title_ids: bool
    exclude_rss_log_ids: bool


class ScannerService:
    def __init__(
        self,
        config: ScannerConfig,
        repositories: ScannerRepositories,
        services: ScannerServices,
    ):
        self.config = config
        self.omdb_client = services.omdb_client
        self.title_repo = repositories.title_repo
        self.occurrence_repo = repositories.occurrence_repo
        self.cache_repo = repositories.cache_repo
        self.run_repo = repositories.run_repo
        self.parse_log_repo = repositories.parse_log_repo
        self.manual_mapping_repo = repositories.manual_mapping_repo
        self.audit_proposal_repo = repositories.audit_proposal_repo
        self.application_store = services.application_store
        self.rss_snapshot_repo = repositories.rss_snapshot_repo
        self.ai_matcher = services.ai_matcher
        self.now = services.now
        self.feed_fetcher = services.feed_fetcher
        self.metadata_resolver = services.metadata_resolver
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

    def _reset_session_caches(self) -> None:
        self.write_buffer = ScanWriteBuffer(
            title_repo=self.title_repo,
            occurrence_repo=self.occurrence_repo,
            parse_log_repo=self.parse_log_repo,
            manual_mapping_repo=self.manual_mapping_repo,
            is_dry_run=self.config.is_dry_run,
            is_parse_only=self.config.is_parse_only,
        )
        self._run_created_proposal_ids: Set[str] = set()
        self._rss_snapshot_collector = RssSnapshotCollector()
        self.rss_ingestion = RssIngestionService(
            config=self.config,
            feed_fetcher=self.feed_fetcher,
            metadata_resolver=self.metadata_resolver,
            write_buffer=self.write_buffer,
            snapshot_collector=self._rss_snapshot_collector,
            now=self.now,
        )

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

    def _select_phases(self) -> _PhaseSelection:
        mode = self.config.mode
        all_mode_without_chaining = mode == "all" and not self.config.allow_same_run_chaining
        return _PhaseSelection(
            mode=mode,
            rss=mode in ("rss", "all"),
            recheck_existing=mode in ("recheck-existing", "all"),
            reparse_unfound=mode in ("reparse-unfound", "all"),
            apply_proposals=mode == "apply-proposals",
            exclude_rss_title_ids=all_mode_without_chaining,
            exclude_rss_log_ids=all_mode_without_chaining,
        )

    def _publish_rss_snapshot(
        self,
        run_id: str,
        run: ScanRun,
        selection: Optional[_PhaseSelection] = None,
    ) -> None:
        if self.rss_snapshot_repo is None or self.config.is_dry_run or self.config.is_parse_only:
            return
        if selection is None:
            selection = self._select_phases()
        if not selection.rss:
            return

        rss_metrics = run.phase_metrics.get("rss", {})
        expected_feed_count = len(self.rss_ingestion.feed_definitions())
        if (
            expected_feed_count == 0
            or run.feeds_processed != expected_feed_count
            or rss_metrics.get("status") != "succeeded"
        ):
            return

        items = self._rss_snapshot_collector.build_items()
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
        self.write_buffer.load_manual_mappings()

    def _find_manual_mapping(
        self,
        *,
        source_item_id: Optional[str] = None,
        legacy_item_id: Optional[str] = None,
        raw_title: Optional[str] = None,
        parsed_title: Optional[str] = None,
    ) -> Optional[ManualMapping]:
        return self.write_buffer.find_manual_mapping(
            source_item_id=source_item_id,
            legacy_item_id=legacy_item_id,
            raw_title=raw_title,
            parsed_title=parsed_title,
        )

    def _consume_manual_mapping(self, manual_mapping: ManualMapping) -> None:
        self.write_buffer.consume_manual_mapping(manual_mapping)

    def _flush_parse_logs(self, section_timings: Optional[Dict[str, float]] = None) -> None:
        self.write_buffer.flush_parse_logs(section_timings)

    def _flush_pending_db_upserts(self, section_timings: Optional[Dict[str, float]] = None) -> None:
        self.write_buffer.flush_pending_db_upserts(section_timings)

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
        self.write_buffer.stage_parse_log(log)

    @staticmethod
    def _rss_skipped_outcome() -> ScanPhaseOutcome:
        return ScanPhaseOutcome(
            counters={
                "feeds_processed": 0,
                "entries_seen": 0,
                "titles_created": 0,
                "titles_updated": 0,
                "occurrences_created": 0,
                "occurrences_updated": 0,
                "cache_hits": 0,
                "omdb_requests": 0,
                "ignored_entries": 0,
            },
            errors=0,
        )

    def _run_rss_phase(
        self,
        run: ScanRun,
        section_timings: Dict[str, float],
        selection: _PhaseSelection,
    ) -> ScanPhaseOutcome:
        if selection.rss:
            outcome = self.rss_ingestion.run(run, section_timings)
        else:
            logger.info(
                f"--> [Phase 1/4] RSS feed processing SKIPPED (mode is '{selection.mode}')"
            )
            outcome = self._rss_skipped_outcome()
        run.phase_metrics["rss"] = outcome.to_dict()
        return outcome

    def _run_existing_title_audit_phase(
        self,
        run: ScanRun,
        section_timings: Dict[str, float],
        selection: _PhaseSelection,
    ) -> ScanPhaseOutcome:
        if not selection.recheck_existing:
            logger.info(
                f"--> [Phase 2/4] AI Database Audit SKIPPED (mode is '{selection.mode}')"
            )
            outcome = ScanPhaseOutcome()
        else:
            logger.info("--> [Phase 2/4] AI Audit & Repair of existing database titles...")
            phase_started = datetime.datetime.now(datetime.timezone.utc)
            initial_errors = run.error_count
            phase_t0 = time.perf_counter()
            excluded_title_ids = (
                set(self.write_buffer.written_title_ids)
                if selection.exclude_rss_title_ids
                else None
            )
            stats = self.recheck_existing_titles(
                run=run,
                section_timings=section_timings,
                excluded_title_ids=excluded_title_ids,
            )
            duration = time.perf_counter() - phase_t0
            section_timings["ai_recheck"] += duration
            phase_finished = datetime.datetime.now(datetime.timezone.utc)
            phase_errors = run.error_count - initial_errors
            if (
                phase_errors == 0
                and stats.get("ai_failures", 0) == 0
                and stats.get("omdb_failures", 0) == 0
            ):
                status = "succeeded"
            elif stats.get("titles_checked", 0) == 0 and phase_errors > 0:
                status = "failed"
            else:
                status = "partial"
            outcome = ScanPhaseOutcome(
                status=status,
                started_at=phase_started.isoformat(),
                finished_at=phase_finished.isoformat(),
                duration_seconds=round(duration, 4),
                counters=stats,
                errors=phase_errors,
            )
        run.phase_metrics["recheck_existing"] = outcome.to_dict()
        return outcome

    def _run_reparse_unfound_phase(
        self,
        run: ScanRun,
        section_timings: Dict[str, float],
        selection: _PhaseSelection,
    ) -> ScanPhaseOutcome:
        if not selection.reparse_unfound:
            logger.info(
                f"--> [Phase 3/4] AI Reparsing SKIPPED (mode is '{selection.mode}')"
            )
            outcome = ScanPhaseOutcome()
        else:
            logger.info("--> [Phase 3/4] AI Reparsing of unmapped/unfound titles...")
            phase_started = datetime.datetime.now(datetime.timezone.utc)
            initial_errors = run.error_count
            phase_t0 = time.perf_counter()
            excluded_log_ids = (
                set(self.write_buffer.written_parse_log_ids)
                if selection.exclude_rss_log_ids
                else None
            )
            stats = self.reparse_unfound_entries(
                run=run,
                section_timings=section_timings,
                excluded_log_ids=excluded_log_ids,
            )
            duration = time.perf_counter() - phase_t0
            section_timings["ai_reparse"] += duration
            phase_finished = datetime.datetime.now(datetime.timezone.utc)
            run.retries_attempted += stats.get("retryable_seen", 0)
            run.retries_resolved += stats.get("resolved", 0)
            run.retries_failed += stats.get("failed", 0)
            phase_errors = run.error_count - initial_errors
            if phase_errors == 0 and stats.get("failed", 0) == 0:
                status = "succeeded"
            elif stats.get("unmapped_seen", 0) == 0 and phase_errors > 0:
                status = "failed"
            else:
                status = "partial"
            outcome = ScanPhaseOutcome(
                status=status,
                started_at=phase_started.isoformat(),
                finished_at=phase_finished.isoformat(),
                duration_seconds=round(duration, 4),
                counters=stats,
                errors=phase_errors,
            )
        run.phase_metrics["reparse_unfound"] = outcome.to_dict()
        return outcome

    def _run_proposal_application_phase(
        self,
        run: ScanRun,
        section_timings: Dict[str, float],
        selection: _PhaseSelection,
    ) -> ScanPhaseOutcome:
        if not selection.apply_proposals:
            logger.info(
                f"--> [Phase 4/4] Proposal Application SKIPPED (mode is '{selection.mode}')"
            )
            outcome = ScanPhaseOutcome()
        else:
            logger.info("--> [Phase 4/4] Applying approved audit proposals...")
            phase_started = datetime.datetime.now(datetime.timezone.utc)
            initial_errors = run.error_count
            phase_t0 = time.perf_counter()
            stats = self._apply_proposals(
                run=run,
                section_timings=section_timings,
            )
            duration = time.perf_counter() - phase_t0
            section_timings["apply_proposals"] = (
                section_timings.get("apply_proposals", 0.0) + duration
            )
            phase_finished = datetime.datetime.now(datetime.timezone.utc)
            phase_errors = run.error_count - initial_errors
            if phase_errors == 0 and stats.get("proposals_failed", 0) == 0:
                status = "succeeded"
            elif stats.get("proposals_seen", 0) == 0 and phase_errors > 0:
                status = "failed"
            else:
                status = "partial"
            outcome = ScanPhaseOutcome(
                status=status,
                started_at=phase_started.isoformat(),
                finished_at=phase_finished.isoformat(),
                duration_seconds=round(duration, 4),
                counters=stats,
                errors=phase_errors,
            )
        run.phase_metrics["apply_proposals"] = outcome.to_dict()
        return outcome

    @staticmethod
    def _calculate_final_status(run: ScanRun, fatal: bool = False) -> str:
        if fatal:
            return "failed"
        phase_statuses = [
            metrics.get("status")
            for metrics in run.phase_metrics.values()
            if metrics.get("status") != "skipped"
        ]
        if any(status == "failed" for status in phase_statuses):
            return "failed"
        if any(status == "partial" for status in phase_statuses) or run.error_count > 0:
            return "partial"
        return "succeeded"

    def _persist_run(self, run_id: str, run: ScanRun) -> None:
        if not self.config.is_dry_run and not self.config.is_parse_only:
            self.run_repo.upsert(run_id, run)

    def _finalize_run(
        self,
        run_id: str,
        run: ScanRun,
        section_timings: Dict[str, float],
        selection: _PhaseSelection,
        fatal: bool,
    ) -> None:
        run.status = self._calculate_final_status(run, fatal=fatal)
        run.finished_at = datetime.datetime.now(datetime.timezone.utc)
        self._flush_parse_logs(section_timings)
        self._flush_pending_db_upserts(section_timings)
        try:
            self._publish_rss_snapshot(run_id, run, selection)
        except Exception as e:
            snapshot_error = f"RSS snapshot publication failed ({type(e).__name__})"
            logger.error(snapshot_error, exc_info=True)
            run.error_count += 1
            run.error_summary.append(snapshot_error)
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
        run.status = self._calculate_final_status(run, fatal=fatal)
        run.section_timings = {k: round(v, 4) for k, v in section_timings.items()}
        logger.info("Scan Section Timings Summary:")
        for sec_name, sec_time in run.section_timings.items():
            logger.info(f"  - Section '{sec_name}': {sec_time:.4f}s")
        self._persist_run(run_id, run)

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

        self._persist_run(run_id, run)

        logger.info(f"Starting scan run {run_id} [mode: '{self.config.mode}', trigger: '{self.config.trigger}']")

        selection = self._select_phases()

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

        fatal = False
        try:
            self._run_rss_phase(run, section_timings, selection)
            self._run_existing_title_audit_phase(run, section_timings, selection)
            self._run_reparse_unfound_phase(run, section_timings, selection)
            self._run_proposal_application_phase(run, section_timings, selection)
        except Exception as e:
            fatal_msg = f"Fatal error during scan ({type(e).__name__}): {e}"
            logger.error(fatal_msg, exc_info=True)
            fatal = True
            run.error_count += 1
            run.error_summary.append(fatal_msg)
        finally:
            self._finalize_run(run_id, run, section_timings, selection, fatal)

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

