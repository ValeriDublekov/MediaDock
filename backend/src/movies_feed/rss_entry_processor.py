import datetime
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .ids import (
    get_occurrence_id_v1,
    get_source_item_id,
    get_title_id_v2,
    normalize_title,
)
from .match_policy import (
    MatchDecision,
    effective_source_type,
    evaluate_match,
)
from .metadata_resolver import MetadataOutcome, MetadataOutcomeStatus, MetadataResolver
from .models import Occurrence, ParseLog, ScanRun, SourceContext, Title
from .omdb_client import OmdbLimitReachedError, OmdbMovieResult
from .rss_snapshot import RssSnapshotCollector
from .scan_contracts import FeedDefinition
from .scan_write_buffer import ScanWriteBuffer
from .rutracker_parser import ParsedTitle

logger = logging.getLogger(__name__)


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


def _get_entry_datetime(entry: Any) -> Optional[datetime.datetime]:
    parsed_time = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed_time:
        try:
            return datetime.datetime(*parsed_time[:6], tzinfo=datetime.timezone.utc)
        except Exception:
            return None
    return None


class RssEntryProcessor:
    def __init__(
        self,
        *,
        config: Any,
        metadata_resolver: MetadataResolver,
        write_buffer: ScanWriteBuffer,
        snapshot_collector: RssSnapshotCollector,
        now: datetime.datetime,
    ) -> None:
        self.config = config
        self.metadata_resolver = metadata_resolver
        self.write_buffer = write_buffer
        self.snapshot_collector = snapshot_collector
        self.now = now

    def source_context_for_entry(
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

    def process_entry(
        self,
        context: ParsedEntryContext,
        feed_def: FeedDefinition,
        run: ScanRun,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> bool:
        try:
            self._process_entry(context, feed_def, run, section_timings)
        except OmdbLimitReachedError as error:
            logger.warning(f"OMDb limit reached: {error}")
            run.error_count += 1
            if "OMDb API limit reached" not in run.error_summary:
                run.error_summary.append("OMDb API limit reached")
            return False
        except Exception as error:
            error_text = f"Entry error ({type(error).__name__}): {error}"
            logger.error(
                f"Error processing entry {context.raw_title}: {error_text}",
                exc_info=True,
            )
            run.error_count += 1
            run.error_summary.append(error_text)
            try:
                self._log_parse_entry(
                    raw_title=context.raw_title,
                    feed_name=feed_def.name,
                    parsed_successfully=False,
                    parsed_title=None,
                    parsed_year=None,
                    omdb_status="error",
                    ignored=True,
                    ignore_reason="entry_error",
                    error_message=error_text,
                    feed_entry_id=getattr(context.entry, "id", None),
                    torrent_url=getattr(context.entry, "link", None),
                    source_feed_id=feed_def.id,
                    source_context=context.source_context,
                    section_timings=section_timings,
                )
            except Exception as log_error:
                logger.error(
                    f"Failed to log entry error to parse logs: {log_error}"
                )
        return True

    @staticmethod
    def _new_section_timings() -> Dict[str, float]:
        return {
            "prune_logs": 0.0,
            "feed_fetch": 0.0,
            "title_parse": 0.0,
            "cache_lookup": 0.0,
            "omdb_api": 0.0,
            "db_upsert": 0.0,
            "parse_log_write": 0.0,
        }

    def _record_phase_error(self, run: ScanRun, message: str) -> None:
        run.error_count += 1
        if message not in run.error_summary:
            run.error_summary.append(message)

    def _sync_omdb_attempts(self, run: ScanRun) -> None:
        resolver_attempts = getattr(self.metadata_resolver, "http_attempts", 0)
        run.omdb_requests = max(run.omdb_requests, resolver_attempts)

    def _record_metadata_outcome_failure(
        self,
        run: ScanRun,
        outcome: MetadataOutcome,
    ) -> None:
        if outcome.status in (
            MetadataOutcomeStatus.QUOTA_EXHAUSTED,
            MetadataOutcomeStatus.TRANSPORT_ERROR,
        ):
            self._record_phase_error(run, "OMDb phase incomplete during rss")
            if outcome.status is MetadataOutcomeStatus.TRANSPORT_ERROR and outcome.error_message:
                self._record_phase_error(
                    run,
                    f"OMDb Transport Error: {outcome.error_message}",
                )
        elif outcome.status is MetadataOutcomeStatus.UNEXPECTED_ERROR:
            self._record_phase_error(run, "OMDb phase failed during rss")
        elif outcome.status is MetadataOutcomeStatus.INVALID_REQUEST:
            self._record_phase_error(
                run,
                "OMDb phase rejected an invalid request during rss",
            )
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
    def _match_trace(
        decision: MatchDecision,
        omdb_result: OmdbMovieResult,
    ) -> Dict[str, Any]:
        trace: Dict[str, Any] = {
            "matchDecision": decision.status,
            "matchReasonCode": decision.reason_code,
            "matchReason": decision.message,
            "omdbSourceType": effective_source_type(
                omdb_result.media_type,
                omdb_result.source_type,
            ),
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

    def _log_parse_entry(
        self,
        *,
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
        source_feed_id: Optional[str] = None,
        source_context: Optional[SourceContext] = None,
    ) -> None:
        if source_feed_id is None:
            raise ValueError("source feed identity is required for an RSS parse log")
        log = ParseLog(
            id=get_source_item_id(source_feed_id, feed_entry_id, torrent_url),
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
            source_context=source_context,
            event_kind="source",
        )
        self.write_buffer.stage_parse_log(log)

    def _process_entry(
        self,
        context: ParsedEntryContext,
        feed_def: FeedDefinition,
        run: ScanRun,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> None:
        if section_timings is None:
            section_timings = self._new_section_timings()

        raw_title = context.raw_title
        feed_entry_id = getattr(context.entry, "id", None)
        torrent_url = getattr(context.entry, "link", "")
        feed_name = feed_def.name
        source_feed_id = feed_def.id
        source_context = context.source_context

        if context.is_ignored_by_date:
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

        parsed = context.parsed
        if not parsed or not parsed.title or parsed.confidence < 0.7:
            self._handle_parse_rejection(context, feed_def, run, section_timings)
            return

        lookup_year = context.lookup_year
        expected_source_type = context.expected_source_type
        base_trace = self._base_trace(
            context,
            feed_def,
            parsed,
            lookup_year,
            expected_source_type,
        )

        logger.info(
            f"[Scanner:Parse] Feed '{feed_name}' | '{raw_title}' -> Title: "
            f"'{parsed.title}', Year: {lookup_year}, Quality: '{parsed.quality}', "
            f"Rip: '{parsed.rip_type}', IsSeries: {parsed.is_series}"
        )

        if self.config.is_parse_only:
            self._handle_parse_only(
                context,
                feed_def,
                parsed.title,
                lookup_year,
                base_trace,
                section_timings,
            )
            return

        manual_mapping = self._select_manual_mapping(
            source_feed_id=source_feed_id,
            feed_entry_id=feed_entry_id,
            torrent_url=torrent_url,
            raw_title=raw_title,
            parsed_title=parsed.title,
        )
        resolver_outcome = self._resolve_metadata(
            manual_mapping,
            parsed.title,
            lookup_year,
            expected_source_type,
            section_timings,
        )

        self._sync_omdb_attempts(run)
        if resolver_outcome.cache_hit:
            run.cache_hits += 1

        if resolver_outcome.status is not MetadataOutcomeStatus.FOUND:
            self._handle_metadata_failure(
                context,
                feed_def,
                run,
                resolver_outcome,
                parsed.title,
                lookup_year,
                expected_source_type,
                base_trace,
                section_timings,
            )
            return

        omdb_result = resolver_outcome.result
        if not omdb_result:
            return

        used_manual_mapping = manual_mapping is not None and bool(manual_mapping.imdb_id)
        omdb_trace_info = self._omdb_trace_info(omdb_result)
        match_decision = self._evaluate_match(
            expected_source_type=expected_source_type,
            omdb_result=omdb_result,
            source_year=lookup_year,
            manual_mapping=used_manual_mapping,
        )
        omdb_trace_info.update(self._match_trace(match_decision, omdb_result))
        if not match_decision.is_accepted:
            self._handle_match_rejection(
                context,
                feed_def,
                run,
                parsed.title,
                lookup_year,
                expected_source_type,
                base_trace,
                omdb_trace_info,
                match_decision,
                omdb_result,
                section_timings,
            )
            return

        self._persist_accepted_entry(
            context,
            feed_def,
            run,
            parsed,
            lookup_year,
            base_trace,
            omdb_trace_info,
            omdb_result,
            manual_mapping,
            used_manual_mapping,
            section_timings,
        )

    def _handle_parse_rejection(
        self,
        context: ParsedEntryContext,
        feed_def: FeedDefinition,
        run: ScanRun,
        section_timings: Dict[str, float],
    ) -> None:
        raw_title = context.raw_title
        parsed = context.parsed
        parse_error = context.parse_error
        run.ignored_entries += 1
        if parse_error:
            run.error_count += 1
            run.error_summary.append(f"Parse error for '{raw_title}': {parse_error}")

        if not parsed or not parsed.title:
            ignore_reason = "parse_error" if parse_error else "no_title"
            error_message = parse_error
        else:
            primary_reason = parsed.reasons[0] if parsed.reasons else "ambiguous"
            ignore_reason = f"low_confidence_parse:{primary_reason}"
            error_message = (
                f"Low parse confidence ({parsed.confidence:.2f}): "
                f"{', '.join(parsed.reasons)}"
            )

        trace_details = {
            "rawTitle": raw_title,
            "feedName": feed_def.name,
            "feedType": feed_def.type,
            "parseConfidence": parsed.confidence if parsed else 0.0,
            "parseReasons": list(parsed.reasons) if parsed else ["parse_error"],
        }
        if parsed and parsed.title:
            trace_details["parsedTitle"] = parsed.title
            trace_details["parsedYear"] = context.lookup_year

        self._log_parse_entry(
            raw_title=raw_title,
            feed_name=feed_def.name,
            parsed_successfully=False,
            parsed_title=parsed.title if (parsed and parsed.title) else None,
            parsed_year=context.lookup_year if parsed else None,
            omdb_status="not_parsed",
            ignored=True,
            ignore_reason=ignore_reason,
            error_message=error_message,
            feed_entry_id=getattr(context.entry, "id", None),
            torrent_url=getattr(context.entry, "link", ""),
            source_feed_id=feed_def.id,
            source_context=context.source_context,
            section_timings=section_timings,
            trace_details=trace_details,
        )

    def _base_trace(
        self,
        context: ParsedEntryContext,
        feed_def: FeedDefinition,
        parsed: ParsedTitle,
        lookup_year: Optional[int],
        expected_source_type: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "parsedTitle": parsed.title,
            "parsedYear": lookup_year,
            "parsedQuality": parsed.quality or None,
            "parsedRipType": parsed.rip_type or None,
            "parsedIsSeries": parsed.is_series,
            "parseConfidence": parsed.confidence,
            "parseReasons": list(parsed.reasons),
            "feedName": feed_def.name,
            "feedType": feed_def.type,
            "expectedSourceType": expected_source_type,
        }

    def _handle_parse_only(
        self,
        context: ParsedEntryContext,
        feed_def: FeedDefinition,
        parsed_title: str,
        lookup_year: Optional[int],
        base_trace: Dict[str, Any],
        section_timings: Dict[str, float],
    ) -> None:
        self._log_parse_entry(
            raw_title=context.raw_title,
            feed_name=feed_def.name,
            parsed_successfully=True,
            parsed_title=parsed_title,
            parsed_year=lookup_year,
            omdb_status="skipped",
            ignored=True,
            ignore_reason="parse_only",
            error_message="Режим само парсване (OMDb заявките са изключени)",
            feed_entry_id=getattr(context.entry, "id", None),
            torrent_url=getattr(context.entry, "link", ""),
            source_feed_id=feed_def.id,
            source_context=context.source_context,
            section_timings=section_timings,
            trace_details={
                **base_trace,
                "decision": "ignored_parse_only",
                "decisionDetails": "Parse only mode",
            },
        )

    def _select_manual_mapping(
        self,
        *,
        source_feed_id: str,
        feed_entry_id: Optional[str],
        torrent_url: Optional[str],
        raw_title: str,
        parsed_title: str,
    ) -> Any:
        return self.write_buffer.find_manual_mapping(
            source_item_id=get_source_item_id(source_feed_id, feed_entry_id, torrent_url),
            legacy_item_id=get_occurrence_id_v1(feed_entry_id, torrent_url or ""),
            raw_title=raw_title,
            parsed_title=parsed_title,
        )

    def _resolve_metadata(
        self,
        manual_mapping: Any,
        parsed_title: str,
        lookup_year: Optional[int],
        expected_source_type: Optional[str],
        section_timings: Dict[str, float],
    ) -> MetadataOutcome:
        if manual_mapping and manual_mapping.imdb_id:
            return self.metadata_resolver.resolve_by_imdb_id(
                manual_mapping.imdb_id,
                lookup_title=parsed_title,
                lookup_year=lookup_year,
                media_type=expected_source_type,
                section_timings=section_timings,
            )
        return self.metadata_resolver.resolve_title(
            parsed_title,
            lookup_year,
            media_type=expected_source_type,
            section_timings=section_timings,
        )

    def _handle_metadata_failure(
        self,
        context: ParsedEntryContext,
        feed_def: FeedDefinition,
        run: ScanRun,
        outcome: MetadataOutcome,
        parsed_title: str,
        lookup_year: Optional[int],
        expected_source_type: Optional[str],
        base_trace: Dict[str, Any],
        section_timings: Dict[str, float],
    ) -> None:
        run.ignored_entries += 1
        self._record_metadata_outcome_failure(run, outcome)
        status = (
            "not_found"
            if outcome.status is MetadataOutcomeStatus.CONFIRMED_NOT_FOUND
            else "skipped"
            if outcome.status is MetadataOutcomeStatus.QUOTA_EXHAUSTED
            else "error"
        )
        ignore_reason = (
            "omdb_not_found"
            if outcome.status is MetadataOutcomeStatus.CONFIRMED_NOT_FOUND
            else "omdb_limit_reached"
            if outcome.status is MetadataOutcomeStatus.QUOTA_EXHAUSTED
            else "omdb_error"
        )
        if outcome.status is MetadataOutcomeStatus.CONFIRMED_NOT_FOUND:
            error_message = (
                f"OMDb не намери заглавие '{parsed_title}' (търсено с година: "
                f"{lookup_year}, тип: {expected_source_type or 'всички'})"
            )
        elif outcome.status is MetadataOutcomeStatus.QUOTA_EXHAUSTED:
            error_message = "Достигнат лимит на OMDb заявки за това сканиране"
        else:
            error_message = outcome.error_message or "OMDb lookup failed"
        trace_details = {
            **base_trace,
            "cacheKey": outcome.cache_key,
            "cacheHit": outcome.cache_hit,
            "metadataOutcome": outcome.status.value,
            "decision": f"ignored_{outcome.status.value}",
            "decisionDetails": error_message,
        }
        self._log_parse_entry(
            raw_title=context.raw_title,
            feed_name=feed_def.name,
            parsed_successfully=True,
            parsed_title=parsed_title,
            parsed_year=lookup_year,
            omdb_status=status,
            ignored=True,
            ignore_reason=ignore_reason,
            error_message=error_message,
            feed_entry_id=getattr(context.entry, "id", None),
            torrent_url=getattr(context.entry, "link", ""),
            source_feed_id=feed_def.id,
            source_context=context.source_context,
            section_timings=section_timings,
            trace_details=trace_details,
        )
        if outcome.status is MetadataOutcomeStatus.QUOTA_EXHAUSTED:
            raise OmdbLimitReachedError("OMDb quota exhausted for this run")

    @staticmethod
    def _omdb_trace_info(omdb_result: OmdbMovieResult) -> Dict[str, Any]:
        return {
            "omdbFoundTitle": omdb_result.title,
            "omdbFoundYear": omdb_result.year,
            "omdbFoundType": omdb_result.media_type,
            "omdbSourceType": effective_source_type(
                omdb_result.media_type,
                omdb_result.source_type,
            ),
            "omdbContentKind": omdb_result.content_kind,
            "omdbImdbId": omdb_result.imdb_id,
            "omdbGenres": omdb_result.genres,
            "omdbCountries": omdb_result.countries,
            "omdbRating": omdb_result.rating,
        }

    def _handle_match_rejection(
        self,
        context: ParsedEntryContext,
        feed_def: FeedDefinition,
        run: ScanRun,
        parsed_title: str,
        lookup_year: Optional[int],
        expected_source_type: Optional[str],
        base_trace: Dict[str, Any],
        omdb_trace_info: Dict[str, Any],
        decision: MatchDecision,
        omdb_result: OmdbMovieResult,
        section_timings: Dict[str, float],
    ) -> None:
        run.ignored_entries += 1
        if decision.reason_code in ("excluded_country", "excluded_genre"):
            error_message = f"Филтрирано по конфигурация: {decision.message}"
        elif decision.reason_code == "type_mismatch":
            actual_type = effective_source_type(
                omdb_result.media_type,
                omdb_result.source_type,
            )
            error_message = (
                f"Разминаване в типа медия: RSS каналът очаква '{expected_source_type}', "
                f"а OMDb върна '{actual_type}'"
            )
        elif decision.reason_code == "series_season_year_out_of_range":
            range_text = (
                omdb_result.broadcast_range.raw
                if omdb_result.broadcast_range
                else "неизвестен диапазон"
            )
            error_message = (
                f"Разминаване в годината на сезона: търсена {lookup_year}, "
                f"OMDb диапазон '{range_text}'"
            )
        elif decision.reason_code == "movie_release_year_mismatch":
            error_message = (
                f"Разминаване в годината: търсена {lookup_year}, OMDb върна "
                f"{omdb_result.year} (> 1 г. разлика)"
            )
        else:
            error_message = decision.message or "Съвпадението изисква преглед"
        logger.info(f"[Scanner:Validate] '{parsed_title}' -> {error_message}")
        self._log_parse_entry(
            raw_title=context.raw_title,
            feed_name=feed_def.name,
            parsed_successfully=True,
            parsed_title=parsed_title,
            parsed_year=lookup_year,
            omdb_status="found",
            ignored=True,
            ignore_reason=self._match_ignore_reason(decision),
            error_message=error_message,
            feed_entry_id=getattr(context.entry, "id", None),
            torrent_url=getattr(context.entry, "link", ""),
            source_feed_id=feed_def.id,
            source_context=context.source_context,
            section_timings=section_timings,
            trace_details={
                **base_trace,
                **omdb_trace_info,
                "decision": f"{decision.status}_{decision.reason_code}",
                "decisionDetails": error_message,
            },
        )

    def _persist_accepted_entry(
        self,
        context: ParsedEntryContext,
        feed_def: FeedDefinition,
        run: ScanRun,
        parsed: ParsedTitle,
        lookup_year: Optional[int],
        base_trace: Dict[str, Any],
        omdb_trace_info: Dict[str, Any],
        omdb_result: OmdbMovieResult,
        manual_mapping: Any,
        used_manual_mapping: bool,
        section_timings: Dict[str, float],
    ) -> None:
        success_message = (
            f"Успешно съвпадение в OMDb ({omdb_result.imdb_id}) и преминати всички филтри"
        )
        logger.info(
            f"[Scanner:Success] '{omdb_result.title}' ({omdb_result.year}) "
            f"[{omdb_result.imdb_id}] -> Добавено в каталога"
        )
        self._log_parse_entry(
            raw_title=context.raw_title,
            feed_name=feed_def.name,
            parsed_successfully=True,
            parsed_title=parsed.title,
            parsed_year=lookup_year,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            error_message=None,
            feed_entry_id=getattr(context.entry, "id", None),
            torrent_url=getattr(context.entry, "link", ""),
            source_feed_id=feed_def.id,
            source_context=context.source_context,
            section_timings=section_timings,
            trace_details={
                **base_trace,
                **omdb_trace_info,
                "decision": "added_to_catalog",
                "decisionDetails": success_message,
            },
        )

        source_context = context.source_context
        item_time = source_context.observed_at or self.now
        media_type = omdb_result.media_type
        source_type = effective_source_type(
            omdb_result.media_type,
            omdb_result.source_type,
        )
        title_id = get_title_id_v2(
            omdb_result.imdb_id,
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
        feed_entry_id = getattr(context.entry, "id", None)
        torrent_url = getattr(context.entry, "link", "")
        occurrence_id = get_source_item_id(feed_def.id, feed_entry_id, torrent_url)
        occurrence_record = Occurrence(
            source_feed_id=feed_def.id,
            source_feed_name=feed_def.name,
            feed_entry_id=feed_entry_id,
            torrent_url=torrent_url,
            raw_title=context.raw_title,
            quality=parsed.quality,
            rip_type=parsed.rip_type,
            first_seen_at=item_time,
            last_seen_at=item_time,
            source_context=source_context,
        )

        if not self.config.is_dry_run:
            self.write_buffer.stage_title_and_occurrence(
                title_id,
                title_record,
                occurrence_id,
                occurrence_record,
                run,
            )
        else:
            run.titles_created += 1
            run.occurrences_created += 1

        self.snapshot_collector.record_candidate(
            title_id=title_id,
            source_type=source_type,
            feed_order=context.feed_order,
            entry_order=context.entry_order,
        )

        if used_manual_mapping and manual_mapping is not None and not self.config.is_dry_run:
            self.write_buffer.stage_manual_mapping(manual_mapping)