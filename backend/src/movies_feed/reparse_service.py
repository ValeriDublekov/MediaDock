import datetime
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .ids import (
    clean_title_for_comparison,
    get_occurrence_id_v1,
    get_source_item_id,
)
from .match_policy import MatchDecision, normalize_source_type
from .metadata_resolver import MetadataOutcome, MetadataOutcomeStatus, MetadataResolver
from .models import ManualMapping, ParseLog, ScanRun, SourceContext
from .omdb_client import OmdbMovieResult
from .repository import OccurrenceRepository, ParseLogRepository, TitleRepository
from .reparse_lifecycle import ReparseLogLifecycle
from .reparse_persistence import ReparsePersistence

logger = logging.getLogger(__name__)


class ReparseService:
    """Retries retained source logs without inventing new source identities."""

    def __init__(
        self,
        *,
        parse_log_repo: ParseLogRepository,
        title_repo: TitleRepository,
        occurrence_repo: OccurrenceRepository,
        metadata_resolver: MetadataResolver,
        ai_matcher: Optional[Any],
        now: datetime.datetime,
        is_dry_run: bool,
        manual_mapping_lookup: Callable[..., Optional[ManualMapping]],
        manual_mapping_consume: Callable[[ManualMapping], None],
        parse_log_feed_type: Callable[[ParseLog], Optional[str]],
        evaluate_match: Callable[..., MatchDecision],
        match_ignore_reason: Callable[[MatchDecision], str],
        record_phase_error: Callable[[Optional[ScanRun], str], None],
        record_metadata_outcome_failure: Callable[[Optional[ScanRun], MetadataOutcome, str], None],
        sync_omdb_attempts: Callable[[Optional[ScanRun]], None],
        page_size: int = 200,
        batch_size: int = 15,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.parse_log_repo = parse_log_repo
        self.title_repo = title_repo
        self.occurrence_repo = occurrence_repo
        self.metadata_resolver = metadata_resolver
        self.ai_matcher = ai_matcher
        self.now = now
        self.is_dry_run = is_dry_run
        self.manual_mapping_lookup = manual_mapping_lookup
        self.manual_mapping_consume = manual_mapping_consume
        self.parse_log_feed_type = parse_log_feed_type
        self.evaluate_match = evaluate_match
        self.match_ignore_reason = match_ignore_reason
        self.record_phase_error = record_phase_error
        self.record_metadata_outcome_failure = record_metadata_outcome_failure
        self.sync_omdb_attempts = sync_omdb_attempts
        self.page_size = page_size
        self.batch_size = batch_size
        self.sleep = sleep or time.sleep
        self.lifecycle = ReparseLogLifecycle(
            parse_log_repo=parse_log_repo,
            stored_source_type=self._stored_source_type,
            record_phase_error=record_phase_error,
            now=now,
            is_dry_run=is_dry_run,
        )
        self.persistence = ReparsePersistence(
            title_repo=title_repo,
            occurrence_repo=occurrence_repo,
            manual_mapping_consume=manual_mapping_consume,
            stored_source_type=self._stored_source_type,
            write_log=self.lifecycle.write,
            record_retry=self.lifecycle.record_retry,
            record_phase_error=record_phase_error,
            now=now,
            is_dry_run=is_dry_run,
        )

    def run(
        self,
        *,
        run: Optional[ScanRun] = None,
        section_timings: Optional[Dict[str, float]] = None,
        excluded_log_ids: Optional[Set[str]] = None,
    ) -> Dict[str, int]:
        stats = self._new_stats()
        cursor = None
        seen_log_ids = set()
        seen_source_ids = set()

        while True:
            try:
                page = self.parse_log_repo.list_retryable(
                    limit=self.page_size,
                    cursor=cursor,
                )
            except Exception as exc:
                logger.warning("Could not load reparse retry page (%s)", type(exc).__name__)
                self.record_phase_error(run, "AI reparse retry page failed")
                stats["failed"] += 1
                break

            if not page.items:
                break

            stats["unmapped_seen"] += len(page.items)
            stats["retryable_seen"] += len(page.items)
            ai_items: List[Tuple[int, ParseLog, SourceContext, str]] = []

            for log in page.items:
                if excluded_log_ids and log.id in excluded_log_ids:
                    stats["skipped"] += 1
                    continue
                if log.id in seen_log_ids:
                    stats["skipped"] += 1
                    continue
                seen_log_ids.add(log.id)

                source_identity = self._source_identity(log)
                if source_identity is None:
                    self._record_retry(
                        log,
                        stats,
                        run=run,
                        section_timings=section_timings,
                        reason="source_context_missing",
                        counted_as_skipped=True,
                    )
                    continue

                source_context, source_item_id, legacy_item_id = source_identity
                if source_item_id in seen_source_ids:
                    stats["skipped"] += 1
                    continue
                seen_source_ids.add(source_item_id)
                raw_title = source_context.raw_title or log.raw_title
                mapping = self.manual_mapping_lookup(
                    source_item_id=source_item_id,
                    legacy_item_id=legacy_item_id,
                    raw_title=raw_title,
                    parsed_title=log.parsed_title,
                )
                if mapping is not None and mapping.imdb_id:
                    self._process_manual_mapping(
                        log,
                        source_context,
                        source_item_id,
                        mapping,
                        stats,
                        run=run,
                        section_timings=section_timings,
                    )
                    continue

                ai_items.append((len(ai_items), log, source_context, source_item_id))

            batch_starts = list(range(0, len(ai_items), self.batch_size))
            for batch_index, start in enumerate(batch_starts):
                self._process_ai_batch(
                    ai_items[start : start + self.batch_size],
                    stats,
                    run=run,
                    section_timings=section_timings,
                )
                has_more_batches = batch_index < len(batch_starts) - 1
                if (
                    not has_more_batches
                    and page.next_cursor is None
                ):
                    continue
                if self.ai_matcher and self.ai_matcher.is_available:
                    self.sleep(5.0)

            if page.next_cursor is None:
                break
            cursor = page.next_cursor

        self._finalize_stats(stats)
        logger.info("AI re-parsing completed: %s", stats)
        return stats

    @staticmethod
    def _new_stats() -> Dict[str, int]:
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

    @staticmethod
    def _finalize_stats(stats: Dict[str, int]) -> None:
        stats["reparsed_succeeded"] = stats["resolved"]
        stats["reparsed_failed"] = (
            stats["retried"] + stats["skipped"] + stats["failed"]
        )

    @staticmethod
    def _source_identity(
        log: ParseLog,
    ) -> Optional[Tuple[SourceContext, str, Optional[str]]]:
        context = log.source_context
        if context is None or not context.source_feed_id:
            return None
        if not context.feed_entry_id and not context.torrent_url:
            return None
        try:
            source_item_id = get_source_item_id(
                context.source_feed_id,
                context.feed_entry_id,
                context.torrent_url,
            )
        except ValueError:
            return None

        legacy_item_id = None
        if context.feed_entry_id or context.torrent_url:
            legacy_item_id = get_occurrence_id_v1(
                context.feed_entry_id,
                context.torrent_url or "",
            )
        return context, source_item_id, legacy_item_id

    def _process_manual_mapping(
        self,
        log: ParseLog,
        source_context: SourceContext,
        source_item_id: str,
        mapping: ManualMapping,
        stats: Dict[str, int],
        *,
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
    ) -> None:
        lookup_title = mapping.parsed_title or log.parsed_title or source_context.raw_title or log.raw_title
        lookup_year = (
            mapping.parsed_year
            if type(mapping.parsed_year) is int
            else log.parsed_year
            if type(log.parsed_year) is int
            else None
        )
        expected_source_type = self._stored_source_type(log)
        try:
            outcome = self.metadata_resolver.resolve_by_imdb_id(
                mapping.imdb_id,
                lookup_title=lookup_title,
                lookup_year=lookup_year,
                media_type=expected_source_type or "unknown",
                section_timings=section_timings,
            )
            self.sync_omdb_attempts(run)
            self._record_cache_hit(run, outcome)
            if outcome.status is not MetadataOutcomeStatus.FOUND or outcome.result is None:
                self._record_metadata_failure(outcome, log, stats, run, section_timings, lookup_title, lookup_year)
                return
            self._process_candidate(
                log,
                source_context,
                source_item_id,
                outcome.result,
                lookup_title,
                lookup_year,
                expected_source_type,
                mapping,
                stats,
                run=run,
                section_timings=section_timings,
            )
        except Exception as exc:
            logger.warning("Retained manual mapping processing failed (%s)", type(exc).__name__)
            self.record_phase_error(run, "AI reparse manual mapping failed")
            self._record_retry(
                log,
                stats,
                run=run,
                section_timings=section_timings,
                reason="manual_mapping_error",
            )

    def _process_ai_batch(
        self,
        items: List[Tuple[int, ParseLog, SourceContext, str]],
        stats: Dict[str, int],
        *,
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
    ) -> None:
        if not items:
            return

        extraction_items = [
            {
                "id": item_id,
                "raw_title": context.raw_title or log.raw_title,
                "feed_type": self._stored_source_type(log) or "unknown",
            }
            for item_id, log, context, _ in items
        ]
        extracted_results: Dict[int, Dict[str, Any]] = {}
        if self.ai_matcher and self.ai_matcher.is_available:
            try:
                result = self.ai_matcher.batch_extract_titles(extraction_items)
                if isinstance(result, dict):
                    extracted_results = result
            except Exception as exc:
                logger.warning("AI batch_extract_titles failed (%s)", type(exc).__name__)
                self.record_phase_error(run, "AI reparse extraction failed")
        else:
            self.record_phase_error(run, "AI reparse matcher unavailable")

        if len(extracted_results) < len(items):
            self.record_phase_error(run, "AI reparse phase returned incomplete results")

        for item_id, log, source_context, source_item_id in items:
            ai_data = extracted_results.get(item_id)
            if not isinstance(ai_data, dict):
                self._record_retry(
                    log,
                    stats,
                    run=run,
                    section_timings=section_timings,
                    reason="ai_result_missing",
                )
                continue
            try:
                self._process_ai_result(
                    log,
                    source_context,
                    source_item_id,
                    ai_data,
                    stats,
                    run=run,
                    section_timings=section_timings,
                )
            except Exception as exc:
                logger.warning("AI reparse item processing failed (%s)", type(exc).__name__)
                self.record_phase_error(run, "AI reparse item processing failed")
                self._record_retry(
                    log,
                    stats,
                    run=run,
                    section_timings=section_timings,
                    reason="reparse_processing_error",
                )

    def _process_ai_result(
        self,
        log: ParseLog,
        source_context: SourceContext,
        source_item_id: str,
        ai_data: Dict[str, Any],
        stats: Dict[str, int],
        *,
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
    ) -> None:
        title = ai_data.get("title")
        if not isinstance(title, str) or not title.strip():
            self._record_retry(
                log,
                stats,
                run=run,
                section_timings=section_timings,
                reason="ai_title_missing",
            )
            return

        year = ai_data.get("year")
        if year is not None and type(year) is not int:
            self._record_retry(
                log,
                stats,
                run=run,
                section_timings=section_timings,
                reason="ai_year_invalid",
                parsed_title=title,
            )
            return

        ai_source_type = normalize_source_type(ai_data.get("media_type"))
        stored_source_type = self._stored_source_type(log)
        if stored_source_type is None and ai_source_type == "unknown":
            self._record_retry(
                log,
                stats,
                run=run,
                section_timings=section_timings,
                reason="ai_media_type_missing",
                parsed_title=title,
                parsed_year=year,
            )
            return
        expected_source_type = stored_source_type or (
            ai_source_type if ai_source_type != "unknown" else None
        )

        outcome = self.metadata_resolver.resolve_title(
            title,
            year,
            media_type=expected_source_type or "unknown",
            section_timings=section_timings,
        )
        self.sync_omdb_attempts(run)
        self._record_cache_hit(run, outcome)
        if outcome.status is not MetadataOutcomeStatus.FOUND or outcome.result is None:
            self._record_metadata_failure(
                outcome,
                log,
                stats,
                run,
                section_timings,
                title,
                year,
                parsed_title=title,
                parsed_year=year,
            )
            return

        self._process_candidate(
            log,
            source_context,
            source_item_id,
            outcome.result,
            title,
            year,
            expected_source_type,
            None,
            stats,
            run=run,
            section_timings=section_timings,
        )

    def _process_candidate(
        self,
        log: ParseLog,
        source_context: SourceContext,
        source_item_id: str,
        omdb_result: OmdbMovieResult,
        lookup_title: str,
        lookup_year: Optional[int],
        expected_source_type: Optional[str],
        manual_mapping: Optional[ManualMapping],
        stats: Dict[str, int],
        *,
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
    ) -> None:
        match_decision = self.evaluate_match(
            expected_source_type=expected_source_type,
            omdb_result=omdb_result,
            source_year=lookup_year,
            manual_mapping=manual_mapping is not None,
        )
        if not match_decision.is_accepted:
            self._record_terminal(
                log,
                stats,
                run=run,
                section_timings=section_timings,
                reason=self._match_reason(match_decision),
                ignore_reason=self.match_ignore_reason(match_decision),
                parsed_title=lookup_title,
                parsed_year=lookup_year,
            )
            return

        if manual_mapping is None and self.ai_matcher and self.ai_matcher.is_available:
            clean_lookup = clean_title_for_comparison(lookup_title)
            clean_candidate = clean_title_for_comparison(omdb_result.title)
            if clean_lookup != clean_candidate:
                try:
                    validation = self.ai_matcher.batch_validate_omdb_matches([{
                        "id": 0,
                        "raw_title": source_context.raw_title or log.raw_title,
                        "feed_type": expected_source_type or "unknown",
                        "omdb_title": omdb_result.title,
                        "omdb_year": omdb_result.year,
                        "omdb_type": omdb_result.media_type,
                    }])
                    validation_result = validation.get(0) if isinstance(validation, dict) else None
                    if validation_result and not validation_result.get("is_match", True):
                        self._record_terminal(
                            log,
                            stats,
                            run=run,
                            section_timings=section_timings,
                            reason="candidate_not_match",
                            ignore_reason="match_ambiguous",
                            parsed_title=lookup_title,
                            parsed_year=lookup_year,
                        )
                        return
                except Exception as exc:
                    logger.warning("AI candidate validation failed (%s)", type(exc).__name__)

        self._persist_success(
            log,
            source_context,
            source_item_id,
            omdb_result,
            lookup_title,
            lookup_year,
            match_decision,
            manual_mapping,
            stats,
            run=run,
            section_timings=section_timings,
        )

    def _persist_success(
        self,
        log: ParseLog,
        source_context: SourceContext,
        source_item_id: str,
        omdb_result: OmdbMovieResult,
        lookup_title: str,
        lookup_year: Optional[int],
        match_decision: MatchDecision,
        manual_mapping: Optional[ManualMapping],
        stats: Dict[str, int],
        *,
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
    ) -> None:
        self.persistence.persist(
            log,
            source_context,
            source_item_id,
            omdb_result,
            lookup_title,
            lookup_year,
            match_decision,
            manual_mapping,
            stats,
            run=run,
            section_timings=section_timings,
        )

    def _record_metadata_failure(
        self,
        outcome: MetadataOutcome,
        log: ParseLog,
        stats: Dict[str, int],
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
        lookup_title: str,
        lookup_year: Optional[int],
        *,
        parsed_title: Optional[str] = None,
        parsed_year: Optional[int] = None,
    ) -> None:
        self.sync_omdb_attempts(run)
        if outcome.status not in (
            MetadataOutcomeStatus.FOUND,
            MetadataOutcomeStatus.CONFIRMED_NOT_FOUND,
        ):
            self.record_metadata_outcome_failure(run, outcome, "reparse")
        if outcome.status is MetadataOutcomeStatus.CONFIRMED_NOT_FOUND:
            reason = "omdb_not_found"
        elif outcome.status is MetadataOutcomeStatus.QUOTA_EXHAUSTED:
            reason = "omdb_limit_reached"
        else:
            reason = "omdb_error"
        self._record_retry(
            log,
            stats,
            run=run,
            section_timings=section_timings,
            reason=reason,
            parsed_title=parsed_title or lookup_title,
            parsed_year=parsed_year if parsed_year is not None else lookup_year,
        )

    def _record_retry(
        self,
        log: ParseLog,
        stats: Dict[str, int],
        *,
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
        reason: str,
        parsed_title: Optional[str] = None,
        parsed_year: Optional[int] = None,
        counted_as_skipped: bool = False,
    ) -> None:
        self.lifecycle.record_retry(
            log,
            stats,
            run=run,
            section_timings=section_timings,
            reason=reason,
            parsed_title=parsed_title,
            parsed_year=parsed_year,
            counted_as_skipped=counted_as_skipped,
        )

    def _record_terminal(
        self,
        log: ParseLog,
        stats: Dict[str, int],
        *,
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
        reason: str,
        ignore_reason: str,
        parsed_title: Optional[str],
        parsed_year: Optional[int],
    ) -> None:
        self.lifecycle.record_terminal(
            log,
            stats,
            run=run,
            section_timings=section_timings,
            reason=reason,
            ignore_reason=ignore_reason,
            parsed_title=parsed_title,
            parsed_year=parsed_year,
        )

    def _stored_source_type(self, log: ParseLog) -> Optional[str]:
        context_type = normalize_source_type(
            log.source_context.feed_type if log.source_context else None
        )
        if context_type != "unknown":
            return context_type
        trace_type = normalize_source_type(self.parse_log_feed_type(log))
        if trace_type != "unknown":
            return trace_type
        return None

    @staticmethod
    def _record_cache_hit(run: Optional[ScanRun], outcome: MetadataOutcome) -> None:
        if run is not None and outcome.cache_hit:
            run.cache_hits += 1

    @staticmethod
    def _match_reason(decision: MatchDecision) -> str:
        reason = decision.reason_code or "match_rejected"
        return reason[:128]
