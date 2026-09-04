import datetime
import importlib
import logging
import time
from typing import Any, Dict, List, Optional, Protocol, Tuple, cast


class _FeedParser(Protocol):
    def parse(self, source: bytes) -> Any:
        ...


try:
    _feedparser_module = importlib.import_module("feedparser")
except ImportError:
    _feedparser_module = None

feedparser: Optional[_FeedParser] = cast(Optional[_FeedParser], _feedparser_module)

from .feed_fetcher import FeedFetcher
from .match_policy import normalize_source_type
from .metadata_resolver import MetadataResolver
from .models import ScanRun
from .rutracker_parser import ParsedTitle, iter_feed_definitions, parse_rutracker_title
from .scan_contracts import FeedDefinition, ScanPhaseOutcome
from .scan_write_buffer import ScanWriteBuffer
from .rss_snapshot import RssSnapshotCollector
from .rss_entry_processor import ParsedEntryContext, RssEntryProcessor

logger = logging.getLogger(__name__)


RssPhaseResult = ScanPhaseOutcome


class RssIngestionService:
    def __init__(
        self,
        *,
        config: Any,
        feed_fetcher: FeedFetcher,
        metadata_resolver: MetadataResolver,
        write_buffer: ScanWriteBuffer,
        snapshot_collector: RssSnapshotCollector,
        now: datetime.datetime,
    ) -> None:
        self.config = config
        self.feed_fetcher = feed_fetcher
        self.metadata_resolver = metadata_resolver
        self.write_buffer = write_buffer
        self.snapshot_collector = snapshot_collector
        self.now = now
        self.entry_processor = RssEntryProcessor(
            config=config,
            metadata_resolver=metadata_resolver,
            write_buffer=write_buffer,
            snapshot_collector=snapshot_collector,
            now=now,
        )

    def feed_definitions(self) -> List[FeedDefinition]:
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

    def run(
        self,
        run: ScanRun,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> RssPhaseResult:
        if section_timings is None:
            section_timings = self._new_section_timings()

        logger.info("--> [Phase 1/4] Processing RSS feeds...")
        phase_started = datetime.datetime.now(datetime.timezone.utc)
        initial_errors = run.error_count
        phase_t0 = time.perf_counter()

        for feed_order, feed_def in enumerate(self.feed_definitions()):
            run.feeds_processed += 1
            try:
                feed_t0 = time.perf_counter()
                if self.config.feed_file:
                    feed_bytes = self.feed_fetcher.fetch_file(self.config.feed_file)
                else:
                    feed_bytes = self.feed_fetcher.fetch(feed_def.require_url())
                if feedparser is None:
                    raise RuntimeError("feedparser is required for RSS ingestion")
                feed = feedparser.parse(feed_bytes)
                feed_duration = time.perf_counter() - feed_t0
                section_timings["feed_fetch"] += feed_duration
                entries = self.feed_fetcher.validate_parsed_feed(feed)
                logger.info(
                    f"Section [feed_fetch]: Feed '{feed_def.name}' fetched in "
                    f"{feed_duration:.4f}s ({len(entries)} entries)"
                )

                parsed_contexts: List[ParsedEntryContext] = []
                cache_requests_to_prefetch: List[
                    Tuple[str, Optional[int], Optional[str], Optional[str]]
                ] = []
                cutoff = None
                if self.config.force_days > 0:
                    cutoff = self.now - datetime.timedelta(days=self.config.force_days)

                for entry_order, entry in enumerate(entries):
                    source_context = self.entry_processor.source_context_for_entry(
                        entry,
                        feed_def,
                    )
                    raw_title = getattr(entry, "title", "") or ""
                    is_ignored = False
                    if cutoff is not None and source_context.source_published_at is not None:
                        if source_context.source_published_at < cutoff:
                            is_ignored = True

                    context = ParsedEntryContext(
                        entry=entry,
                        source_context=source_context,
                        is_ignored_by_date=is_ignored,
                        raw_title=raw_title,
                        feed_order=feed_order,
                        entry_order=entry_order,
                    )

                    if not is_ignored and raw_title:
                        parse_t0 = time.perf_counter()
                        try:
                            context.parsed = parse_rutracker_title(
                                raw_title,
                                content_type=feed_def.type,
                                video_settings=self.config.video_settings,
                            )
                            section_timings["title_parse"] += time.perf_counter() - parse_t0
                            if context.parsed and context.parsed.title:
                                if context.parsed.year:
                                    try:
                                        context.lookup_year = int(context.parsed.year)
                                    except ValueError:
                                        pass
                                context.expected_source_type = self._expected_source_type(
                                    feed_def.type,
                                    context.parsed.is_series,
                                )
                                cache_requests_to_prefetch.append(
                                    (
                                        context.parsed.title,
                                        context.lookup_year,
                                        context.expected_source_type,
                                        None,
                                    )
                                )
                        except Exception as error:
                            section_timings["title_parse"] += time.perf_counter() - parse_t0
                            logger.error(
                                f"Error parsing rutracker title '{raw_title}': {error}",
                                exc_info=True,
                            )
                            context.parsed = ParsedTitle(
                                title="",
                                year=None,
                                is_series=False,
                                quality="",
                                rip_type="",
                            )
                            context.parse_error = f"Грешка при парсване: {error}"

                    parsed_contexts.append(context)

                if cache_requests_to_prefetch:
                    self.metadata_resolver.prefetch(
                        cache_requests_to_prefetch,
                        section_timings,
                    )

                for context in parsed_contexts:
                    run.entries_seen += 1
                    should_continue = self.entry_processor.process_entry(
                        context,
                        feed_def,
                        run,
                        section_timings,
                    )
                    if not should_continue:
                        break

                self.write_buffer.flush_parse_logs(section_timings)
                self.write_buffer.flush_pending_db_upserts(section_timings)
            except Exception as error:
                error_text = (
                    f"Feed error for '{feed_def.name}' ({type(error).__name__}): {error}"
                )
                logger.error(error_text, exc_info=True)
                run.error_count += 1
                run.error_summary.append(error_text)

        phase_finished = datetime.datetime.now(datetime.timezone.utc)
        phase_duration = time.perf_counter() - phase_t0
        phase_errors = run.error_count - initial_errors
        status = (
            "succeeded"
            if phase_errors == 0
            else "failed"
            if run.feeds_processed == 0 and phase_errors > 0
            else "partial"
        )
        return RssPhaseResult(
            status=status,
            started_at=phase_started.isoformat(),
            finished_at=phase_finished.isoformat(),
            duration_seconds=round(phase_duration, 4),
            counters={
                "feeds_processed": run.feeds_processed,
                "entries_seen": run.entries_seen,
                "titles_created": run.titles_created,
                "titles_updated": run.titles_updated,
                "occurrences_created": run.occurrences_created,
                "occurrences_updated": run.occurrences_updated,
                "cache_hits": run.cache_hits,
                "omdb_requests": run.omdb_requests,
                "ignored_entries": run.ignored_entries,
            },
            errors=phase_errors,
        )

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

    @staticmethod
    def _expected_source_type(
        feed_type: Optional[str],
        series_marker: bool = False,
    ) -> Optional[str]:
        normalized = normalize_source_type(feed_type)
        if normalized != "unknown":
            return normalized
        return "series" if series_marker else None

