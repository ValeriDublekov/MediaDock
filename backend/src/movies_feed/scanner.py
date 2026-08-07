import datetime
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import feedparser

from .ids import get_cache_key, get_occurrence_id, get_title_id, normalize_title
from .models import Occurrence, OmdbCacheEntry, ScanRun, Title
from .omdb_client import (
    OmdbClient,
    OmdbLimitReachedError,
    OmdbNoMatchError,
    OmdbTransportError,
)
from .repository import (
    OccurrenceRepository,
    OmdbCacheRepository,
    ScanRunRepository,
    TitleRepository,
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

class ScannerService:
    def __init__(
        self,
        config: ScannerConfig,
        omdb_client: OmdbClient,
        title_repo: TitleRepository,
        occurrence_repo: OccurrenceRepository,
        cache_repo: OmdbCacheRepository,
        run_repo: ScanRunRepository,
        now: Optional[datetime.datetime] = None,
    ):
        self.config = config
        self.omdb_client = omdb_client
        self.title_repo = title_repo
        self.occurrence_repo = occurrence_repo
        self.cache_repo = cache_repo
        self.run_repo = run_repo
        self.now = now or datetime.datetime.now(datetime.timezone.utc)

    def is_excluded(self, countries: List[str], genres: List[str]) -> bool:
        excluded_country_set = {c.lower() for c in self.config.excluded_countries}
        if countries and all(c.lower() in excluded_country_set for c in countries):
            return True
        excluded_genre_set = {g.lower() for g in self.config.excluded_genres}
        if any(g.lower() in excluded_genre_set for g in genres):
            return True
        return False

    def run(self, run_id: str) -> ScanRun:
        run = ScanRun(
            started_at=self.now,
            finished_at=None,
            status="running",
            trigger=self.config.trigger,
        )
        if not self.config.is_dry_run and not self.config.is_parse_only:
            self.run_repo.upsert(run_id, run)

        try:
            for feed_def in iter_feed_definitions(self.config.rss_feeds):
                run.feeds_processed += 1
                try:
                    feed = feedparser.parse(feed_def["url"])
                    for entry in feed.entries:
                        run.entries_seen += 1
                        try:
                            self._process_entry(entry, feed_def, run)
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
            run.finished_at = datetime.datetime.now(datetime.timezone.utc)
            if not self.config.is_dry_run and not self.config.is_parse_only:
                self.run_repo.upsert(run_id, run)

        return run

    def _process_entry(self, entry: Any, feed_def: Dict[str, Optional[str]], run: ScanRun) -> None:
        raw_title = getattr(entry, "title", "")
        if not raw_title:
            run.ignored_entries += 1
            return

        parsed = parse_rutracker_title(
            raw_title,
            content_type=feed_def.get("type"),
            video_settings=self.config.video_settings,
        )

        if not parsed.title:
            run.ignored_entries += 1
            return

        if self.config.is_parse_only:
            return

        norm_lookup_title = normalize_title(parsed.title)
        lookup_year = None
        if parsed.year:
            try:
                lookup_year = int(parsed.year)
            except ValueError:
                pass

        cache_key = get_cache_key(parsed.title, lookup_year)
        cache_entry = self.cache_repo.get(cache_key)

        omdb_payload = None
        omdb_result = None

        if cache_entry and cache_entry.expires_at > self.now:
            run.cache_hits += 1
            if cache_entry.status != "found" or not cache_entry.payload:
                run.ignored_entries += 1
                return
            omdb_payload = cache_entry.payload
            omdb_result = self.omdb_client._normalize_payload(omdb_payload)
        else:
            if run.omdb_requests >= self.config.omdb_limit:
                logger.info("Soft limit reached for OMDb requests in this run.")
                run.ignored_entries += 1
                return

            run.omdb_requests += 1
            status = "not_found"
            payload = None
            try:
                omdb_result = self.omdb_client.get_movie_info(parsed.title, parsed.year)
                status = "found"
                payload = omdb_result.raw_payload
            except OmdbNoMatchError:
                pass
            except OmdbLimitReachedError:
                raise
            except OmdbTransportError as e:
                run.error_count += 1
                run.error_summary.append(f"OMDb Transport Error: {str(e)}")
                return
            
            new_cache = OmdbCacheEntry(
                lookup_title=parsed.title,
                lookup_year=lookup_year,
                status=status,
                payload=payload,
                fetched_at=self.now,
                expires_at=self.now + datetime.timedelta(days=self.config.cache_ttl_days),
            )
            if not self.config.is_dry_run:
                self.cache_repo.set(cache_key, new_cache)

            if status != "found":
                run.ignored_entries += 1
                return

        if not omdb_result:
            return

        if self.is_excluded(omdb_result.countries, omdb_result.genres):
            run.ignored_entries += 1
            return

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

        feed_entry_id = getattr(entry, "id", None)
        torrent_url = getattr(entry, "link", "")
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
            existing_title = self.title_repo.get(title_id)
            if not existing_title:
                run.titles_created += 1
            self.title_repo.upsert(title_id, title_record)

            existing_occ = self.occurrence_repo.get(title_id, occurrence_id)
            if not existing_occ:
                run.occurrences_created += 1
            self.occurrence_repo.upsert(title_id, occurrence_id, occurrence_record)
        else:
            # Simulate creation tracking for dry run without storing
            run.titles_created += 1
            run.occurrences_created += 1
