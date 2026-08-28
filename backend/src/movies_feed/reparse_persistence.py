import copy
import logging
from typing import Callable, Dict, Optional

from .ids import get_title_id_v2, normalize_title
from .match_policy import MatchDecision, effective_source_type
from .models import ManualMapping, Occurrence, ParseLog, ParseLogResolution, ScanRun, SourceContext, Title
from .omdb_client import OmdbMovieResult
from .repository import OccurrenceRepository, TitleRepository

logger = logging.getLogger(__name__)


class ReparsePersistence:
    """Persists reparse catalog records and source-log lifecycle updates."""

    def __init__(
        self,
        *,
        title_repo: TitleRepository,
        occurrence_repo: OccurrenceRepository,
        manual_mapping_consume: Callable[[ManualMapping], None],
        stored_source_type: Callable[[ParseLog], Optional[str]],
        write_log: Callable[[ParseLog, Optional[Dict[str, float]]], None],
        record_retry: Callable[..., None],
        record_phase_error: Callable[[Optional[ScanRun], str], None],
        now,
        is_dry_run: bool,
    ) -> None:
        self.title_repo = title_repo
        self.occurrence_repo = occurrence_repo
        self.manual_mapping_consume = manual_mapping_consume
        self.stored_source_type = stored_source_type
        self.write_log = write_log
        self.record_retry = record_retry
        self.record_phase_error = record_phase_error
        self.now = now
        self.is_dry_run = is_dry_run

    def persist(
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
        source_type = effective_source_type(omdb_result.media_type, omdb_result.source_type)
        title_id = get_title_id_v2(
            omdb_result.imdb_id,
            omdb_result.title,
            omdb_result.year,
            source_type,
        )
        occurrence_id = source_item_id
        observed_at = source_context.observed_at or log.processed_at or self.now
        title_record = Title(
            title=omdb_result.title,
            normalized_title=normalize_title(omdb_result.title),
            year=omdb_result.year,
            media_type=omdb_result.media_type,
            first_seen_at=observed_at,
            last_seen_at=self.now,
            updated_at=self.now,
            imdb_id=omdb_result.imdb_id,
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
        occurrence_record = Occurrence(
            source_feed_id=source_context.source_feed_id or "",
            source_feed_name=source_context.source_feed_name or log.feed_name or "",
            feed_entry_id=source_context.feed_entry_id,
            torrent_url=source_context.torrent_url or "",
            raw_title=source_context.raw_title or log.raw_title,
            quality="",
            rip_type="",
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            source_context=copy.deepcopy(source_context),
        )

        title_was_missing = True
        occurrence_was_missing = True
        try:
            if not self.is_dry_run:
                title_was_missing = self.title_repo.get(title_id) is None
                occurrence_was_missing = self.occurrence_repo.get(title_id, occurrence_id) is None
                self.title_repo.upsert(title_id, title_record)
                self.occurrence_repo.upsert(title_id, occurrence_id, occurrence_record)
                self.write_log(
                    self._resolved_log(
                        log,
                        title_id=title_id,
                        occurrence_id=occurrence_id,
                        lookup_title=lookup_title,
                        lookup_year=lookup_year,
                        match_decision=match_decision,
                    ),
                    section_timings,
                )
            else:
                title_was_missing = True
                occurrence_was_missing = True

            if run is not None:
                if title_was_missing:
                    run.titles_created += 1
                if occurrence_was_missing:
                    run.occurrences_created += 1
            stats["resolved"] += 1

            if manual_mapping is not None and not self.is_dry_run:
                try:
                    self.manual_mapping_consume(manual_mapping)
                except Exception as exc:
                    logger.warning("Manual mapping consumption failed (%s)", type(exc).__name__)
                    self.record_phase_error(run, "Manual mapping consumption failed")
                    stats["failed"] += 1
        except Exception as exc:
            logger.warning("Reparse persistence failed (%s)", type(exc).__name__)
            self.record_phase_error(run, "AI reparse catalog persistence failed")
            self.record_retry(
                log,
                stats,
                run=run,
                section_timings=section_timings,
                reason="catalog_persistence_error",
                parsed_title=lookup_title,
                parsed_year=lookup_year,
            )

    def _resolved_log(
        self,
        log: ParseLog,
        *,
        title_id: str,
        occurrence_id: str,
        lookup_title: str,
        lookup_year: Optional[int],
        match_decision: MatchDecision,
    ) -> ParseLog:
        context = copy.deepcopy(log.source_context)
        merged_trace = dict(log.trace_details) if isinstance(log.trace_details, dict) else {}
        merged_trace.update({
            "feedType": self.stored_source_type(log) or "unknown",
            "reparseOutcome": "resolved",
            "matchReasonCode": match_decision.reason_code,
            "titleId": title_id,
            "occurrenceId": occurrence_id,
        })
        return ParseLog(
            id=log.id,
            raw_title=log.raw_title or (context.raw_title if context else "") or "",
            feed_name=log.feed_name or (context.source_feed_name if context else "") or "",
            parsed_successfully=True,
            parsed_title=lookup_title or log.parsed_title,
            parsed_year=lookup_year if lookup_year is not None else log.parsed_year,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=self.now,
            error_message=None,
            trace_details=merged_trace,
            decision="resolved",
            source_context=context,
            event_kind="source",
            retry_state="resolved",
            attempt_count=log.attempt_count + 1,
            last_attempt_at=self.now,
            resolution=ParseLogResolution(
                resolved_at=self.now,
                outcome="matched",
                reason="catalog_match",
                title_id=title_id,
                occurrence_id=occurrence_id,
            ),
        )
