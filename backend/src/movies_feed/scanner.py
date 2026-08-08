import datetime
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import feedparser

from .ids import get_cache_key, get_occurrence_id, get_title_id, normalize_title
from .models import Occurrence, OmdbCacheEntry, ParseLog, ScanRun, Title
from .omdb_client import (
    OmdbClient,
    OmdbLimitReachedError,
    OmdbNoMatchError,
    OmdbTransportError,
)
from .repository import (
    OccurrenceRepository,
    OmdbCacheRepository,
    ParseLogRepository,
    ScanRunRepository,
    TitleRepository,
    merge_occurrences,
    merge_titles,
)
from .rutracker_parser import iter_feed_definitions, parse_rutracker_title

logger = logging.getLogger(__name__)

@dataclass
class ScannerConfig:
    rss_feeds: Dict[str, Any]
    video_settings: Dict[str, Any]
    excluded_countries: List[str]
    excluded_genres: List[str]
    is_dry_run: bool = False
    is_parse_only: bool = False
    omdb_limit: int = 50
    cache_ttl_days: int = 30
    trigger: str = "manual"
    force_days: int = 0

def _get_entry_datetime(entry: Any) -> Optional[datetime.datetime]:
    parsed_time = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed_time:
        try:
            return datetime.datetime(*parsed_time[:6], tzinfo=datetime.timezone.utc)
        except Exception:
            return None
    return None

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
        now: Optional[datetime.datetime] = None,
    ):
        self.config = config
        self.omdb_client = omdb_client
        self.title_repo = title_repo
        self.occurrence_repo = occurrence_repo
        self.cache_repo = cache_repo
        self.run_repo = run_repo
        self.parse_log_repo = parse_log_repo
        self.now = now or datetime.datetime.now(datetime.timezone.utc)
        self._reset_session_caches()

    def _reset_session_caches(self) -> None:
        self._session_cache_entries: Dict[str, Optional[OmdbCacheEntry]] = {}
        self._session_titles: Dict[str, Optional[Title]] = {}
        self._session_occurrences: Dict[tuple, Optional[Occurrence]] = {}
        self._pending_parse_logs: List[ParseLog] = []
        self._pending_titles: Dict[str, Title] = {}
        self._pending_occurrences: Dict[tuple[str, str], Occurrence] = {}

    def _get_cache_entry(self, cache_key: str) -> Optional[OmdbCacheEntry]:
        if cache_key in self._session_cache_entries:
            return self._session_cache_entries[cache_key]
        entry = self.cache_repo.get(cache_key)
        self._session_cache_entries[cache_key] = entry
        return entry

    def _prefetch_cache_entries(
        self,
        cache_keys: List[str],
        section_timings: Optional[Dict[str, float]] = None,
    ) -> None:
        missing_keys = [k for k in set(cache_keys) if k not in self._session_cache_entries]
        if not missing_keys:
            return
        t0 = time.perf_counter()
        fetched = self.cache_repo.get_many(missing_keys)
        if section_timings is not None:
            section_timings["cache_lookup"] += (time.perf_counter() - t0)
        for k in missing_keys:
            self._session_cache_entries[k] = fetched.get(k)

    def _set_cache_entry(self, cache_key: str, entry: OmdbCacheEntry) -> None:
        self._session_cache_entries[cache_key] = entry
        if not self.config.is_dry_run:
            self.cache_repo.set(cache_key, entry)

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
            merged_title = merge_titles(existing_title, title_record)
        self._session_titles[title_id] = merged_title
        self._pending_titles[title_id] = merged_title

        existing_occ = self._get_occurrence(title_id, occurrence_id)
        if existing_occ is None:
            run.occurrences_created += 1
            merged_occ = occurrence_record
        else:
            merged_occ = merge_occurrences(existing_occ, occurrence_record)
        occ_key = (title_id, occurrence_id)
        self._session_occurrences[occ_key] = merged_occ
        self._pending_occurrences[occ_key] = merged_occ

    def _flush_parse_logs(self, section_timings: Optional[Dict[str, float]] = None) -> None:
        if not self._pending_parse_logs or not self.parse_log_repo or self.config.is_dry_run:
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

        if section_timings is not None:
            section_timings["db_upsert"] += (time.perf_counter() - t0)

    def is_excluded(self, countries: List[str], genres: List[str]) -> bool:
        excluded_country_set = {c.lower() for c in self.config.excluded_countries}
        if countries and all(c.lower() in excluded_country_set for c in countries):
            return True
        excluded_genre_set = {g.lower() for g in self.config.excluded_genres}
        if any(g.lower() in excluded_genre_set for g in genres):
            return True
        return False

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
        feed_entry_id: Optional[str] = None,
        torrent_url: Optional[str] = None,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> None:
        if not self.parse_log_repo or self.config.is_dry_run:
            return
        if feed_entry_id or torrent_url:
            log_id = get_occurrence_id(feed_entry_id, torrent_url)
        else:
            log_id = get_occurrence_id(None, raw_title + str(self.now.timestamp()))

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
        )
        self._pending_parse_logs.append(log)

    def run(self, run_id: str) -> ScanRun:
        self._reset_session_caches()
        run = ScanRun(
            started_at=self.now,
            finished_at=None,
            status="running",
            trigger=self.config.trigger,
        )
        if not self.config.is_dry_run and not self.config.is_parse_only:
            self.run_repo.upsert(run_id, run)

        section_timings = {
            "prune_logs": 0.0,
            "feed_fetch": 0.0,
            "title_parse": 0.0,
            "cache_lookup": 0.0,
            "omdb_api": 0.0,
            "db_upsert": 0.0,
            "parse_log_write": 0.0,
        }

        if self.parse_log_repo and not self.config.is_dry_run:
            t0 = time.perf_counter()
            cutoff = self.now - datetime.timedelta(days=7)
            self.parse_log_repo.prune_older_than(cutoff)
            t_prune = time.perf_counter() - t0
            section_timings["prune_logs"] += t_prune
            logger.info(f"Section [prune_logs]: completed in {t_prune:.4f}s")

        try:
            for feed_def in iter_feed_definitions(self.config.rss_feeds):
                run.feeds_processed += 1
                try:
                    t0_feed = time.perf_counter()
                    feed = feedparser.parse(feed_def["url"])
                    t_feed = time.perf_counter() - t0_feed
                    section_timings["feed_fetch"] += t_feed
                    entries = getattr(feed, "entries", [])
                    entries_cnt = len(entries)
                    logger.info(
                        f"Section [feed_fetch]: Feed '{feed_def['name']}' fetched in {t_feed:.4f}s ({entries_cnt} entries)"
                    )

                    # Bulk pre-fetch cache entries for this feed
                    cache_keys_to_prefetch = []
                    for entry in entries:
                        raw_title = getattr(entry, "title", "")
                        if raw_title:
                            parsed = parse_rutracker_title(
                                raw_title,
                                content_type=feed_def.get("type"),
                                video_settings=self.config.video_settings,
                            )
                            if parsed.title:
                                y = None
                                if parsed.year:
                                    try:
                                        y = int(parsed.year)
                                    except ValueError:
                                        pass
                                ck = get_cache_key(parsed.title, y)
                                cache_keys_to_prefetch.append(ck)
                    if cache_keys_to_prefetch:
                        self._prefetch_cache_entries(cache_keys_to_prefetch, section_timings)

                    for entry in entries:
                        run.entries_seen += 1
                        try:
                            self._process_entry(entry, feed_def, run, section_timings)
                        except OmdbLimitReachedError as e:
                            logger.warning(f"OMDb limit reached: {e}")
                            run.error_count += 1
                            if "OMDb API limit reached" not in run.error_summary:
                                run.error_summary.append("OMDb API limit reached")
                            break
                        except Exception as e:
                            logger.error(f"Error processing entry {getattr(entry, 'title', '')}: {e}")
                            run.error_count += 1
                            run.error_summary.append(f"Entry error: {e}")

                    # Flush batch parse logs and db upserts for feed
                    self._flush_parse_logs(section_timings)
                    self._flush_pending_db_upserts(section_timings)

                except Exception as e:
                    logger.error(f"Error processing feed {feed_def['name']}: {e}")
                    run.error_count += 1
                    run.error_summary.append(f"Feed error: {e}")
            run.status = "succeeded" if run.error_count == 0 else "partial"
        except Exception as e:
            logger.error(f"Fatal error during scan: {e}")
            run.status = "failed"
            run.error_count += 1
            run.error_summary.append(f"Fatal error: {e}")
        finally:
            self._flush_parse_logs(section_timings)
            self._flush_pending_db_upserts(section_timings)
            run.finished_at = datetime.datetime.now(datetime.timezone.utc)
            run.section_timings = {k: round(v, 4) for k, v in section_timings.items()}
            logger.info("Scan Section Timings Summary:")
            for sec_name, sec_time in run.section_timings.items():
                logger.info(f"  - Section '{sec_name}': {sec_time:.4f}s")
            if not self.config.is_dry_run and not self.config.is_parse_only:
                self.run_repo.upsert(run_id, run)

        return run

    def _process_entry(
        self,
        entry: Any,
        feed_def: Dict[str, Optional[str]],
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

        raw_title = getattr(entry, "title", "")
        feed_entry_id = getattr(entry, "id", None)
        torrent_url = getattr(entry, "link", "")
        feed_name = feed_def.get("name", "")

        if self.config.force_days > 0:
            entry_dt = _get_entry_datetime(entry)
            if entry_dt is not None:
                cutoff = self.now - datetime.timedelta(days=self.config.force_days)
                if entry_dt < cutoff:
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
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                section_timings=section_timings,
            )
            return

        t0_parse = time.perf_counter()
        parsed = parse_rutracker_title(
            raw_title,
            content_type=feed_def.get("type"),
            video_settings=self.config.video_settings,
        )
        section_timings["title_parse"] += (time.perf_counter() - t0_parse)

        if not parsed.title:
            run.ignored_entries += 1
            self._log_parse_entry(
                raw_title=raw_title,
                feed_name=feed_name,
                parsed_successfully=False,
                parsed_title=None,
                parsed_year=None,
                omdb_status="not_parsed",
                ignored=True,
                ignore_reason="no_title",
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                section_timings=section_timings,
            )
            return

        norm_lookup_title = normalize_title(parsed.title)
        lookup_year = None
        if parsed.year:
            try:
                lookup_year = int(parsed.year)
            except ValueError:
                pass

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
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                section_timings=section_timings,
            )
            return

        cache_key = get_cache_key(parsed.title, lookup_year)
        t0_cache = time.perf_counter()
        cache_entry = self._get_cache_entry(cache_key)
        section_timings["cache_lookup"] += (time.perf_counter() - t0_cache)

        omdb_payload = None
        omdb_result = None

        if cache_entry and cache_entry.expires_at > self.now:
            run.cache_hits += 1
            if cache_entry.status != "found" or not cache_entry.payload:
                run.ignored_entries += 1
                self._log_parse_entry(
                    raw_title=raw_title,
                    feed_name=feed_name,
                    parsed_successfully=True,
                    parsed_title=parsed.title,
                    parsed_year=lookup_year,
                    omdb_status="not_found",
                    ignored=True,
                    ignore_reason="omdb_not_found",
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    section_timings=section_timings,
                )
                return
            omdb_payload = cache_entry.payload
            omdb_result = self.omdb_client._normalize_payload(omdb_payload)
        else:
            if run.omdb_requests >= self.config.omdb_limit:
                logger.info("Soft limit reached for OMDb requests in this run.")
                run.ignored_entries += 1
                self._log_parse_entry(
                    raw_title=raw_title,
                    feed_name=feed_name,
                    parsed_successfully=True,
                    parsed_title=parsed.title,
                    parsed_year=lookup_year,
                    omdb_status="skipped",
                    ignored=True,
                    ignore_reason="omdb_limit_reached",
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    section_timings=section_timings,
                )
                return

            run.omdb_requests += 1
            status = "not_found"
            payload = None
            t0_omdb = time.perf_counter()
            try:
                media_type_hint = "series" if parsed.is_series else (feed_def.get("type") if feed_def.get("type") in ("movie", "series") else None)
                omdb_result = self.omdb_client.get_movie_info(parsed.title, parsed.year, media_type=media_type_hint)
                status = "found"
                payload = omdb_result.raw_payload
            except OmdbNoMatchError:
                pass
            except OmdbLimitReachedError:
                raise
            except OmdbTransportError as e:
                run.error_count += 1
                run.error_summary.append(f"OMDb Transport Error: {str(e)}")
                self._log_parse_entry(
                    raw_title=raw_title,
                    feed_name=feed_name,
                    parsed_successfully=True,
                    parsed_title=parsed.title,
                    parsed_year=lookup_year,
                    omdb_status="error",
                    ignored=True,
                    ignore_reason="omdb_error",
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    section_timings=section_timings,
                )
                return
            finally:
                section_timings["omdb_api"] += (time.perf_counter() - t0_omdb)
            
            new_cache = OmdbCacheEntry(
                lookup_title=parsed.title,
                lookup_year=lookup_year,
                status=status,
                payload=payload,
                fetched_at=self.now,
                expires_at=self.now + datetime.timedelta(days=self.config.cache_ttl_days),
            )
            t0_cache_write = time.perf_counter()
            self._set_cache_entry(cache_key, new_cache)
            section_timings["cache_lookup"] += (time.perf_counter() - t0_cache_write)

            if status != "found":
                run.ignored_entries += 1
                self._log_parse_entry(
                    raw_title=raw_title,
                    feed_name=feed_name,
                    parsed_successfully=True,
                    parsed_title=parsed.title,
                    parsed_year=lookup_year,
                    omdb_status="not_found",
                    ignored=True,
                    ignore_reason="omdb_not_found",
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    section_timings=section_timings,
                )
                return

        if not omdb_result:
            return

        if self.is_excluded(omdb_result.countries, omdb_result.genres):
            run.ignored_entries += 1
            self._log_parse_entry(
                raw_title=raw_title,
                feed_name=feed_name,
                parsed_successfully=True,
                parsed_title=parsed.title,
                parsed_year=lookup_year,
                omdb_status="found",
                ignored=True,
                ignore_reason="excluded_country_or_genre",
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                section_timings=section_timings,
            )
            return

        # Record success log entry
        self._log_parse_entry(
            raw_title=raw_title,
            feed_name=feed_name,
            parsed_successfully=True,
            parsed_title=parsed.title,
            parsed_year=lookup_year,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            feed_entry_id=feed_entry_id,
            torrent_url=torrent_url,
            section_timings=section_timings,
        )

        # Prepare records
        media_type = omdb_result.media_type
        imdb_id = omdb_result.imdb_id
        title_id = get_title_id(imdb_id, norm_lookup_title, lookup_year, media_type)

        title_record = Title(
            title=omdb_result.title,
            normalized_title=normalize_title(omdb_result.title),
            year=omdb_result.year,
            media_type=media_type,
            first_seen_at=self.now,
            last_seen_at=self.now,
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
        )

        occurrence_id = get_occurrence_id(feed_entry_id, torrent_url)

        occurrence_record = Occurrence(
            source_feed_id=feed_def["name"],  # use name as id for now or pass slug
            source_feed_name=feed_def["name"],
            feed_entry_id=feed_entry_id,
            torrent_url=torrent_url,
            raw_title=raw_title,
            quality=parsed.quality,
            rip_type=parsed.rip_type,
            first_seen_at=self.now,
            last_seen_at=self.now,
        )

        # Upsert
        if not self.config.is_dry_run:
            self._stage_title_and_occurrence(title_id, title_record, occurrence_id, occurrence_record, run)
        else:
            # Simulate creation tracking for dry run without storing
            run.titles_created += 1
            run.occurrences_created += 1
