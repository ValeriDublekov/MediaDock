import copy
import datetime
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import feedparser

from .ids import clean_title_for_comparison, get_cache_key, get_occurrence_id, get_title_id, normalize_title
from .match_policy import (
    MatchDecision,
    effective_source_type,
    evaluate_match,
    get_exclusion_reason as policy_get_exclusion_reason,
    normalize_source_type,
)
from .models import ManualMapping, Occurrence, OmdbCacheEntry, ParseLog, ScanRun, Title
from .omdb_client import (
    OmdbClient,
    OmdbLimitReachedError,
    OmdbMovieResult,
    OmdbNoMatchError,
    OmdbTransportError,
)
from .repository import (
    ManualMappingRepository,
    OccurrenceRepository,
    OmdbCacheRepository,
    ParseLogRepository,
    ScanRunRepository,
    TitleRepository,
    merge_occurrences,
    merge_titles,
)
from .rutracker_parser import ParsedTitle, iter_feed_definitions, parse_rutracker_title
from .ai_matcher import AiMatcher
from .feed_fetcher import FeedFetcher

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
    mode: str = "rss"  # "rss", "recheck-existing", "reparse-unfound", "all"
    feed_file: Optional[str] = None
    feed_file_name: str = "fixture"
    feed_file_type: Optional[str] = "movie"


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
        manual_mapping_repo: Optional[ManualMappingRepository] = None,
        ai_matcher: Optional[AiMatcher] = None,
        now: Optional[datetime.datetime] = None,
        feed_fetcher: Optional[FeedFetcher] = None,
    ):
        self.config = config
        self.omdb_client = omdb_client
        self.title_repo = title_repo
        self.occurrence_repo = occurrence_repo
        self.cache_repo = cache_repo
        self.run_repo = run_repo
        self.parse_log_repo = parse_log_repo
        self.manual_mapping_repo = manual_mapping_repo
        self.ai_matcher = ai_matcher
        self.now = now or datetime.datetime.now(datetime.timezone.utc)
        self.feed_fetcher = feed_fetcher or FeedFetcher()
        self._reset_session_caches()

    def _iter_scan_feed_definitions(self) -> List[Dict[str, Optional[str]]]:
        if self.config.feed_file:
            return [{
                "name": self.config.feed_file_name,
                "url": None,
                "type": self.config.feed_file_type,
            }]
        return list(iter_feed_definitions(self.config.rss_feeds))

    def _reset_session_caches(self) -> None:
        self._session_cache_entries: Dict[str, Optional[OmdbCacheEntry]] = {}
        self._session_titles: Dict[str, Optional[Title]] = {}
        self._session_occurrences: Dict[tuple, Optional[Occurrence]] = {}
        self._pending_parse_logs: List[ParseLog] = []
        self._pending_titles: Dict[str, Title] = {}
        self._pending_occurrences: Dict[tuple[str, str], Occurrence] = {}
        self._manual_mappings_by_id: Dict[str, ManualMapping] = {}
        self._manual_mappings_by_raw_title: Dict[str, ManualMapping] = {}
        self._manual_mappings_by_parsed_title: Dict[str, ManualMapping] = {}

    @staticmethod
    def _record_phase_error(run: Optional[ScanRun], message: str) -> None:
        if run is None:
            return
        run.error_count += 1
        if message not in run.error_summary:
            run.error_summary.append(message)

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

    def _evaluate_existing_title_match(self, title_record: Title, raw_title: str) -> MatchDecision:
        expected_source_type = effective_source_type(title_record.media_type, title_record.source_type)
        parsed_year: Optional[int] = None
        try:
            parsed = parse_rutracker_title(
                raw_title,
                content_type=expected_source_type if expected_source_type != "unknown" else None,
                video_settings=self.config.video_settings,
            )
            if parsed.year:
                parsed_year = int(parsed.year)
        except (TypeError, ValueError):
            return MatchDecision(
                "ambiguous",
                "source_year_unparseable",
                "The occurrence year could not be parsed for deterministic audit validation.",
            )

        return evaluate_match(
            expected_source_type=expected_source_type,
            actual_source_type=title_record.source_type,
            actual_media_type=title_record.media_type,
            source_year=parsed_year,
            resolved_year=title_record.year,
            broadcast_range=title_record.broadcast_range,
            countries=title_record.countries,
            genres=title_record.genres,
            excluded_countries=self.config.excluded_countries,
            excluded_genres=self.config.excluded_genres,
        )

    @staticmethod
    def _is_valid_recheck_result(result: Any, expected_id: int) -> bool:
        if not isinstance(result, dict):
            return False
        if "id" in result and (type(result["id"]) is not int or result["id"] != expected_id):
            return False
        if type(result.get("is_valid_match")) is not bool:
            return False

        confidence = result.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                return False
            confidence_value = float(confidence)
            if not math.isfinite(confidence_value) or not 0.0 <= confidence_value <= 1.0:
                return False
            if confidence_value < 0.7:
                return False

        if "reason" in result and result["reason"] is not None and not isinstance(result["reason"], str):
            return False

        for field_name in ("corrected_title", "corrected_media_type"):
            value = result.get(field_name)
            if value is not None and not isinstance(value, str):
                return False
        corrected_title = result.get("corrected_title")
        if corrected_title is not None and not corrected_title.strip():
            return False

        corrected_year = result.get("corrected_year")
        if corrected_year is not None and type(corrected_year) is not int:
            return False
        corrected_media_type = result.get("corrected_media_type")
        if corrected_media_type is not None and corrected_media_type not in ("movie", "series"):
            return False

        if result["is_valid_match"] and any(
            result.get(field_name) is not None
            for field_name in ("corrected_title", "corrected_year", "corrected_media_type")
        ):
            return False
        return True

    def _validate_recheck_batch(
        self,
        items: List[Dict[str, Any]],
        results: Any,
    ) -> bool:
        if not isinstance(results, dict):
            return False
        expected_ids = {item["id"] for item in items}
        if set(results.keys()) != expected_ids:
            return False

        embedded_ids = [result.get("id") for result in results.values() if isinstance(result, dict) and "id" in result]
        if embedded_ids and (
            len(embedded_ids) != len(results)
            or len(set(embedded_ids)) != len(embedded_ids)
            or set(embedded_ids) != expected_ids
        ):
            return False

        return all(
            self._is_valid_recheck_result(results[item_id], item_id)
            for item_id in expected_ids
        )

    def _record_recheck_needs_review(
        self,
        title_id: str,
        title_record: Title,
        occurrences: List[Occurrence],
        raw_title: str,
        feed_name: str,
        audit_outcome: str,
        reason: str,
        omdb_status: str = "skipped",
        parsed_title: Optional[str] = None,
        parsed_year: Optional[int] = None,
        trace_details: Optional[Dict[str, Any]] = None,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> None:
        details: Dict[str, Any] = {
            "titleId": title_id,
            "occurrenceCount": len(occurrences),
            "auditOutcome": audit_outcome,
        }
        if trace_details:
            details.update(copy.deepcopy(trace_details))
        self._log_parse_entry(
            raw_title=raw_title,
            feed_name=feed_name,
            parsed_successfully=bool(occurrences),
            parsed_title=parsed_title,
            parsed_year=parsed_year,
            omdb_status=omdb_status,
            ignored=True,
            ignore_reason="audit_needs_review",
            error_message=f"Audit needs review: {reason}",
            section_timings=section_timings,
            trace_details=details,
            decision="needs_review",
            log_key=f"recheck:{title_id}:{audit_outcome}",
        )

    def _inspect_recheck_suggestion(
        self,
        raw_title: str,
        corrected_title: Optional[str],
        corrected_year: Optional[int],
        corrected_media_type: Optional[str],
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
        expected_source_type: Optional[str] = None,
        manual_mapping: bool = False,
    ) -> Dict[str, Any]:
        outcome: Dict[str, Any] = {
            "omdb_status": "skipped",
            "omdb_outcome": "missing_corrected_title",
            "candidate_outcome": "not_evaluated",
            "retryable": False,
        }
        if not corrected_title:
            return outcome

        lookup_title = corrected_title.strip()
        if not lookup_title:
            outcome["omdb_outcome"] = "invalid_request"
            outcome["candidate_outcome"] = "not_evaluated"
            return outcome

        t0 = time.perf_counter()
        try:
            omdb_result = self.omdb_client.get_movie_info(
                lookup_title,
                str(corrected_year) if corrected_year is not None else None,
                media_type=corrected_media_type,
            )
        except OmdbNoMatchError:
            outcome["omdb_status"] = "not_found"
            outcome["omdb_outcome"] = "confirmed_not_found"
            return outcome
        except OmdbLimitReachedError:
            outcome["omdb_status"] = "error"
            outcome["omdb_outcome"] = "quota_exhausted"
            outcome["retryable"] = True
            self._record_phase_error(run, "OMDb phase incomplete during recheck")
            return outcome
        except OmdbTransportError:
            outcome["omdb_status"] = "error"
            outcome["omdb_outcome"] = "transport_error"
            outcome["retryable"] = True
            self._record_phase_error(run, "OMDb phase incomplete during recheck")
            return outcome
        except ValueError:
            outcome["omdb_status"] = "error"
            outcome["omdb_outcome"] = "invalid_request"
            outcome["retryable"] = False
            self._record_phase_error(run, "OMDb phase failed during recheck")
            return outcome
        except Exception:
            outcome["omdb_status"] = "error"
            outcome["omdb_outcome"] = "unexpected_error"
            outcome["retryable"] = True
            self._record_phase_error(run, "OMDb phase incomplete during recheck")
            return outcome
        finally:
            if section_timings is not None:
                section_timings.setdefault("omdb_api", 0.0)
                section_timings["omdb_api"] += time.perf_counter() - t0

        if (
            not isinstance(omdb_result, OmdbMovieResult)
            or not isinstance(omdb_result.title, str)
            or not omdb_result.title.strip()
            or omdb_result.year is not None and type(omdb_result.year) is not int
            or omdb_result.media_type not in ("movie", "series", "documentary", "short")
            or not isinstance(omdb_result.countries, list)
            or not isinstance(omdb_result.genres, list)
        ):
            outcome["omdb_status"] = "error"
            outcome["omdb_outcome"] = "malformed_result"
            outcome["retryable"] = True
            self._record_phase_error(run, "OMDb phase incomplete during recheck")
            return outcome

        outcome["omdb_status"] = "found"
        match_decision = self._evaluate_match(
            expected_source_type=expected_source_type or corrected_media_type,
            omdb_result=omdb_result,
            source_year=corrected_year,
            manual_mapping=manual_mapping,
        )
        outcome["match_decision"] = match_decision.status
        outcome["match_reason_code"] = match_decision.reason_code
        if not match_decision.is_accepted:
            if match_decision.reason_code in ("excluded_country", "excluded_genre"):
                outcome["candidate_outcome"] = "excluded"
            elif match_decision.reason_code == "type_mismatch":
                outcome["candidate_outcome"] = "type_mismatch"
            elif "year" in match_decision.reason_code:
                outcome["candidate_outcome"] = "year_mismatch"
            else:
                outcome["candidate_outcome"] = "ambiguous"
            outcome["retryable"] = match_decision.is_ambiguous
            return outcome

        outcome["candidate_outcome"] = "valid_suggestion"
        if not (
            self.ai_matcher
            and self.ai_matcher.is_available
            and clean_title_for_comparison(lookup_title)
            != clean_title_for_comparison(omdb_result.title)
        ):
            return outcome

        try:
            validation_results = self.ai_matcher.batch_validate_omdb_matches([{
                "id": 0,
                "raw_title": raw_title,
                "feed_type": expected_source_type or corrected_media_type or "unknown",
                "omdb_title": omdb_result.title,
                "omdb_year": omdb_result.year,
                "omdb_type": omdb_result.media_type,
            }])
        except Exception:
            validation_results = None

        candidate_validation = (
            validation_results.get(0)
            if isinstance(validation_results, dict)
            and set(validation_results.keys()) == {0}
            else None
        )
        if not isinstance(candidate_validation, dict) or type(candidate_validation.get("is_match")) is not bool:
            outcome["candidate_outcome"] = "ai_validation_incomplete"
            outcome["retryable"] = True
            self._record_phase_error(run, "AI candidate validation incomplete during recheck")
            return outcome

        confidence = candidate_validation.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                outcome["candidate_outcome"] = "ai_validation_incomplete"
                outcome["retryable"] = True
                self._record_phase_error(run, "AI candidate validation incomplete during recheck")
                return outcome
            confidence_value = float(confidence)
            if not math.isfinite(confidence_value) or not 0.0 <= confidence_value <= 1.0 or confidence_value < 0.7:
                outcome["candidate_outcome"] = "ai_validation_low_confidence"
                outcome["retryable"] = True
                self._record_phase_error(run, "AI candidate validation incomplete during recheck")
                return outcome

        if not candidate_validation["is_match"]:
            outcome["candidate_outcome"] = "ai_rejected"
        return outcome

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
        log_key: Optional[str] = None,
    ) -> None:
        if not self.parse_log_repo or self.config.is_dry_run:
            return
        if log_key is not None:
            log_id = get_occurrence_id(None, log_key)
        elif feed_entry_id or torrent_url:
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
            error_message=error_message,
            trace_details=trace_details,
            decision=decision,
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
            if self.config.mode in ("rss", "all"):
                logger.info("--> [Phase 1/3] Processing RSS feeds...")
                for feed_def in self._iter_scan_feed_definitions():
                    run.feeds_processed += 1
                    try:
                        t0_feed = time.perf_counter()
                        if self.config.feed_file:
                            feed_bytes = self.feed_fetcher.fetch_file(self.config.feed_file)
                        else:
                            feed_url = feed_def.get("url")
                            if not isinstance(feed_url, str):
                                raise ValueError("configured feed URL is missing")
                            feed_bytes = self.feed_fetcher.fetch(feed_url)
                        feed = feedparser.parse(feed_bytes)
                        t_feed = time.perf_counter() - t0_feed
                        section_timings["feed_fetch"] += t_feed
                        entries = self.feed_fetcher.validate_parsed_feed(feed)
                        entries_cnt = len(entries)
                        logger.info(
                            f"Section [feed_fetch]: Feed '{feed_def['name']}' fetched in {t_feed:.4f}s ({entries_cnt} entries)"
                        )

                        # Bulk pre-fetch cache entries for this feed
                        cache_keys_to_prefetch = []
                        for entry in entries:
                            raw_title = getattr(entry, "title", "")
                            if raw_title:
                                try:
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
                                except Exception as e:
                                    logger.warning(f"Error during cache key prefetch for '{raw_title}': {e}")
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
                                err_text = f"Entry error ({type(e).__name__}): {e}"
                                logger.error(f"Error processing entry {getattr(entry, 'title', '')}: {err_text}", exc_info=True)
                                run.error_count += 1
                                run.error_summary.append(err_text)
                                try:
                                    self._log_parse_entry(
                                        raw_title=getattr(entry, "title", "") or "",
                                        feed_name=feed_def.get("name", ""),
                                        parsed_successfully=False,
                                        parsed_title=None,
                                        parsed_year=None,
                                        omdb_status="error",
                                        ignored=True,
                                        ignore_reason="entry_error",
                                        error_message=err_text,
                                        feed_entry_id=getattr(entry, "id", None),
                                        torrent_url=getattr(entry, "link", None),
                                        section_timings=section_timings,
                                    )
                                except Exception as log_ex:
                                    logger.error(f"Failed to log entry error to parse logs: {log_ex}")

                        # Flush batch parse logs and db upserts for feed
                        self._flush_parse_logs(section_timings)
                        self._flush_pending_db_upserts(section_timings)

                    except Exception as e:
                        err_text = f"Feed error for '{feed_def['name']}' ({type(e).__name__}): {e}"
                        logger.error(err_text, exc_info=True)
                        run.error_count += 1
                        run.error_summary.append(err_text)
            else:
                logger.info(f"--> [Phase 1/3] RSS feed processing SKIPPED (mode is '{self.config.mode}')")

            if self.config.is_parse_only:
                logger.info("--> [Phase 2/3] AI Database Audit SKIPPED (parse-only mode)")
                logger.info("--> [Phase 3/3] AI Unmapped Reparsing SKIPPED (parse-only mode)")
            else:
                # 2. AI Database Recheck & Fix (if mode is "recheck-existing" or "all")
                if self.config.mode in ("recheck-existing", "all"):
                    logger.info("--> [Phase 2/3] AI Audit & Repair of existing database titles...")
                    t0_recheck = time.perf_counter()
                    self.recheck_existing_titles(run=run, section_timings=section_timings)
                    section_timings["ai_recheck"] += (time.perf_counter() - t0_recheck)
                else:
                    logger.info(f"--> [Phase 2/3] AI Database Audit SKIPPED (mode is '{self.config.mode}')")

                # 3. AI Reparse Unfound Titles (if mode is "reparse-unfound" or "all")
                if self.config.mode in ("reparse-unfound", "all"):
                    logger.info("--> [Phase 3/3] AI Reparsing of unmapped/unfound titles...")
                    t0_reparse = time.perf_counter()
                    self.reparse_unfound_entries(run=run, section_timings=section_timings)
                    section_timings["ai_reparse"] += (time.perf_counter() - t0_reparse)
                else:
                    logger.info(f"--> [Phase 3/3] AI Unmapped Reparsing SKIPPED (mode is '{self.config.mode}')")

            run.status = "succeeded" if run.error_count == 0 else "partial"
        except Exception as e:
            fatal_msg = f"Fatal error during scan ({type(e).__name__}): {e}"
            logger.error(fatal_msg, exc_info=True)
            run.status = "failed"
            run.error_count += 1
            run.error_summary.append(fatal_msg)
        finally:
            self._flush_parse_logs(section_timings)
            self._flush_pending_db_upserts(section_timings)
            run.finished_at = datetime.datetime.now(datetime.timezone.utc)
            run.section_timings = {k: round(v, 4) for k, v in section_timings.items()}
            logger.info("Scan Section Timings Summary:")
            for sec_name, sec_time in run.section_timings.items():
                logger.info(f"  - Section '{sec_name}': {sec_time:.4f}s")
            if self.ai_matcher and self.ai_matcher.is_available:
                ai_stats = self.ai_matcher.get_stats()
                logger.info(
                    f"AI Matcher Execution Summary: Calls Total={ai_stats['total_calls']} "
                    f"(Success={ai_stats['successful_calls']}, Failed={ai_stats['failed_calls']}), "
                    f"Items Processed={ai_stats['total_items_processed']}"
                )
            if not self.config.is_dry_run and not self.config.is_parse_only:
                self.run_repo.upsert(run_id, run)

        return run

    def recheck_existing_titles(
        self,
        run: Optional[ScanRun] = None,
        section_timings: Optional[Dict[str, float]] = None,
        audit_days: Optional[int] = None,
    ) -> Dict[str, int]:
        """Audit existing titles without applying replacement or deletion decisions."""
        if audit_days is None:
            audit_days = self.config.audit_days

        stats = {
            "titles_checked": 0,
            "mismatches_found": 0,
            "repaired": 0,
            "removed": 0,
            "validated": 0,
            "needs_review": 0,
            "ai_failures": 0,
            "omdb_failures": 0,
        }

        all_titles = self.title_repo.list_all_ids_and_titles()
        if not all_titles:
            logger.info("No titles found in database to recheck.")
            return stats

        # Filter out already AI-validated titles
        unvalidated_titles = [
            (tid, trec) for (tid, trec) in all_titles if not trec.ai_validated
        ]

        if audit_days and audit_days > 0:
            cutoff = self.now - datetime.timedelta(days=audit_days)
            unvalidated_titles = [
                (tid, trec) for (tid, trec) in unvalidated_titles
                if (trec.last_seen_at or trec.updated_at or trec.first_seen_at or datetime.datetime.min) >= cutoff
            ]
            logger.info(
                f"AI recheck status: {len(all_titles)} total in DB, "
                f"filtered to last {audit_days} days (cutoff {cutoff.isoformat()}). "
                f"{len(unvalidated_titles)} remaining unvalidated titles to audit."
            )
        else:
            logger.info(
                f"AI recheck status: {len(all_titles)} total in DB (unlimited date range), "
                f"{len(all_titles) - len(unvalidated_titles)} already AI-validated. "
                f"{len(unvalidated_titles)} remaining to audit."
            )

        if not unvalidated_titles:
            logger.info("All existing database titles are already AI-validated. Skipping recheck.")
            return stats

        # Sort newest first by last_seen_at or updated_at or first_seen_at
        def _get_sort_key(item: tuple[str, Title]) -> datetime.datetime:
            t = item[1]
            return t.last_seen_at or t.updated_at or t.first_seen_at or datetime.datetime.min

        unvalidated_titles.sort(key=_get_sort_key, reverse=True)

        batch_size = 15
        total_batches = (len(unvalidated_titles) + batch_size - 1) // batch_size
        logger.info(
            f"Starting AI recheck of {len(unvalidated_titles)} unvalidated titles in database "
            f"(newest first, {total_batches} batches of up to {batch_size})..."
        )

        for batch_idx, i in enumerate(range(0, len(unvalidated_titles), batch_size), start=1):
            chunk = unvalidated_titles[i : i + batch_size]
            items_to_audit = []
            chunk_context = []

            logger.info(
                f"[AI Recheck] Batch {batch_idx}/{total_batches}: auditing {len(chunk)} titles "
                f"(items {i + 1}-{i + len(chunk)} of {len(unvalidated_titles)})..."
            )

            for idx, (title_id, title_record) in enumerate(chunk):
                occs = self.occurrence_repo.list_by_title(title_id)
                if not occs:
                    stats["needs_review"] += 1
                    self._record_recheck_needs_review(
                        title_id=title_id,
                        title_record=title_record,
                        occurrences=occs,
                        raw_title=title_record.title,
                        feed_name="database",
                        audit_outcome="orphan",
                        reason="Title has no occurrences to audit",
                        section_timings=section_timings,
                    )
                    continue

                raw_title = occs[0].raw_title
                feed_name = occs[0].source_feed_name
                ai_id = len(items_to_audit)
                items_to_audit.append({
                    "id": ai_id,
                    "raw_title": raw_title,
                    "feed_name": feed_name,
                    "current_omdb_title": title_record.title,
                    "current_omdb_year": title_record.year,
                    "current_omdb_type": title_record.media_type,
                    "current_omdb_source_type": effective_source_type(title_record.media_type, title_record.source_type),
                    "current_content_kind": title_record.content_kind,
                    "current_broadcast_range": (
                        title_record.broadcast_range.to_dict()
                        if title_record.broadcast_range is not None
                        else None
                    ),
                    "current_imdb_id": title_record.imdb_id,
                })
                chunk_context.append((ai_id, title_id, title_record, occs, raw_title, feed_name))

            stats["titles_checked"] += len(chunk)

            if not items_to_audit:
                self._flush_parse_logs(section_timings)
                continue

            audit_results: Any = {}
            batch_failure_reason = "AI matcher is unavailable"
            if self.ai_matcher and self.ai_matcher.is_available:
                try:
                    audit_results = self.ai_matcher.batch_recheck_matches(items_to_audit)
                    batch_failure_reason = "AI response was empty, incomplete, or malformed"
                except Exception as e:
                    batch_failure_reason = f"AI matcher call failed ({type(e).__name__})"
                    logger.warning(f"AI batch_recheck_matches failed: {type(e).__name__}")

            if not self._validate_recheck_batch(items_to_audit, audit_results):
                stats["ai_failures"] += 1
                self._record_phase_error(run, "AI recheck phase incomplete")
                logger.error(
                    f"[AI Recheck] {batch_failure_reason} on batch {batch_idx}/{total_batches}. "
                    "Stopping remaining recheck processing immediately."
                )
                for _, title_id, title_record, occs, raw_title, feed_name in chunk_context:
                    stats["needs_review"] += 1
                    self._record_recheck_needs_review(
                        title_id=title_id,
                        title_record=title_record,
                        occurrences=occs,
                        raw_title=raw_title,
                        feed_name=feed_name,
                        audit_outcome="ai_batch_incomplete",
                        reason=batch_failure_reason,
                        section_timings=section_timings,
                    )
                self._flush_parse_logs(section_timings)
                break

            for ai_id, title_id, title_record, occs, raw_title, feed_name in chunk_context:
                ai_res = audit_results[ai_id]
                deterministic_decision = self._evaluate_existing_title_match(title_record, raw_title)
                if ai_res["is_valid_match"] is True and not deterministic_decision.is_rejected:
                    validated_title = copy.deepcopy(title_record)
                    validated_title.ai_validated = True
                    validated_title.ai_checked_at = self.now
                    if not self.config.is_dry_run:
                        self.title_repo.upsert(title_id, validated_title)
                    stats["validated"] += 1
                else:
                    stats["mismatches_found"] += 1
                    stats["needs_review"] += 1
                    corr_title = ai_res.get("corrected_title")
                    corr_year = ai_res.get("corrected_year")
                    corr_media_type = ai_res.get("corrected_media_type")
                    if ai_res["is_valid_match"] is True:
                        reason = (
                            "Deterministic match policy rejected the stored match: "
                            f"{deterministic_decision.message or deterministic_decision.reason_code}"
                        )
                        corr_title = None
                        corr_year = None
                        corr_media_type = None
                    else:
                        reason = ai_res.get("reason") or "AI detected a mismatch"
                    logger.info(f"Mismatch for title '{title_record.title}' (raw: '{raw_title}'): {reason}")
                    suggestion = self._inspect_recheck_suggestion(
                        raw_title=raw_title,
                        corrected_title=corr_title,
                        corrected_year=corr_year,
                        corrected_media_type=corr_media_type,
                        run=run,
                        section_timings=section_timings,
                        expected_source_type=(
                            corr_media_type
                            or effective_source_type(title_record.media_type, title_record.source_type)
                        ),
                    )
                    if suggestion["omdb_status"] == "error":
                        stats["omdb_failures"] += 1
                    trace_details = {
                        "aiReason": reason,
                        "policyReasonCode": deterministic_decision.reason_code,
                        "suggestedTitle": corr_title,
                        "suggestedYear": corr_year,
                        "suggestedMediaType": corr_media_type,
                        "omdbOutcome": suggestion["omdb_outcome"],
                        "candidateOutcome": suggestion["candidate_outcome"],
                        "candidateMatchDecision": suggestion.get("match_decision"),
                        "candidateMatchReasonCode": suggestion.get("match_reason_code"),
                    }
                    self._record_recheck_needs_review(
                        title_id=title_id,
                        title_record=title_record,
                        occurrences=occs,
                        raw_title=raw_title,
                        feed_name=feed_name,
                        audit_outcome="mismatch_retained",
                        reason=reason,
                        omdb_status=suggestion["omdb_status"],
                        parsed_title=corr_title,
                        parsed_year=corr_year,
                        trace_details=trace_details,
                        section_timings=section_timings,
                    )

            self._flush_parse_logs(section_timings)

            # Brief rate-limit pause between AI batches if more remain
            if batch_idx < total_batches and self.ai_matcher and self.ai_matcher.is_available:
                time.sleep(5.0)

        logger.info(f"AI database recheck completed: {stats}")
        return stats

    def _recheck_existing_titles(
        self,
        run: Optional[ScanRun] = None,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> Dict[str, int]:
        return self.recheck_existing_titles(run=run, section_timings=section_timings)

    def reparse_unfound_entries(
        self,
        run: Optional[ScanRun] = None,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> Dict[str, int]:
        """
        Gathers unmapped/not found parse logs, uses AI to re-extract clean titles,
        queries OMDb and validates candidates. If successful, writes Title and Occurrence to database.
        """
        stats = {
            "unmapped_seen": 0,
            "reparsed_succeeded": 0,
            "reparsed_failed": 0,
        }

        if not self.parse_log_repo:
            return stats

        unmapped_logs = self.parse_log_repo.list_unmapped(limit=200)
        if not unmapped_logs:
            logger.info("No unmapped logs found for re-parsing.")
            return stats

        logger.info(f"Starting AI re-parsing of {len(unmapped_logs)} unmapped entries...")
        stats["unmapped_seen"] = len(unmapped_logs)

        seen_raw_titles = set()
        unique_logs = []
        for log in unmapped_logs:
            if log.raw_title and log.raw_title not in seen_raw_titles:
                seen_raw_titles.add(log.raw_title)
                unique_logs.append(log)

        batch_size = 15
        total_batches = (len(unique_logs) + batch_size - 1) // batch_size
        for batch_idx, i in enumerate(range(0, len(unique_logs), batch_size), start=1):
            chunk = unique_logs[i : i + batch_size]
            items_to_extract = [
                {
                    "id": idx,
                    "raw_title": log.raw_title,
                    "feed_type": self._parse_log_feed_type(log) or "unknown",
                }
                for idx, log in enumerate(chunk)
            ]

            logger.info(
                f"[AI Reparse] Batch {batch_idx}/{total_batches}: re-parsing {len(chunk)} unmapped entries "
                f"(items {i + 1}-{i + len(chunk)} of {len(unique_logs)})..."
            )

            extracted_results = {}
            if self.ai_matcher and self.ai_matcher.is_available:
                try:
                    extracted_results = self.ai_matcher.batch_extract_titles(items_to_extract)
                except Exception as e:
                    logger.warning(f"AI batch_extract_titles failed: {e}")

            if items_to_extract and not extracted_results:
                self._record_phase_error(run, "AI reparse phase incomplete")
                logger.error(
                    f"[AI Reparse] AI matcher failed or returned no results on batch {batch_idx}/{total_batches} "
                    f"(rate limit or API error). Stopping remaining unmapped re-parse batches immediately."
                )
                break

            if len(extracted_results) < len(items_to_extract):
                self._record_phase_error(run, "AI reparse phase returned incomplete results")

            if batch_idx < total_batches and self.ai_matcher and self.ai_matcher.is_available:
                time.sleep(5.0)

            for idx, log in enumerate(chunk):
                if idx not in extracted_results:
                    stats["reparsed_failed"] += 1
                    continue
                ai_data = extracted_results.get(idx, {})
                title = ai_data.get("title")
                year = ai_data.get("year")
                media_type = ai_data.get("media_type")
                stored_feed_type = self._parse_log_feed_type(log)
                ai_source_type = normalize_source_type(media_type)
                expected_source_type = stored_feed_type or (
                    ai_source_type if ai_source_type != "unknown" else None
                )

                if not title:
                    stats["reparsed_failed"] += 1
                    continue

                omdb_result = None
                try:
                    omdb_result = self.omdb_client.get_movie_info(
                        title,
                        str(year) if year else None,
                        media_type=expected_source_type,
                    )
                except (OmdbNoMatchError, OmdbLimitReachedError, OmdbTransportError) as ex:
                    if isinstance(ex, (OmdbLimitReachedError, OmdbTransportError)):
                        self._record_phase_error(run, "OMDb phase incomplete during reparse")
                    omdb_result = None

                is_valid = False
                if omdb_result:
                    match_decision = self._evaluate_match(
                        expected_source_type=expected_source_type,
                        omdb_result=omdb_result,
                        source_year=year if type(year) is int else None,
                    )
                    is_valid = match_decision.is_accepted
                    if is_valid and self.ai_matcher and self.ai_matcher.is_available:
                        clean_rep = clean_title_for_comparison(title)
                        clean_cand = clean_title_for_comparison(omdb_result.title)
                        if clean_rep != clean_cand:
                            try:
                                v_res = self.ai_matcher.batch_validate_omdb_matches([{
                                    "id": 0,
                                    "raw_title": log.raw_title,
                                    "feed_type": expected_source_type or "unknown",
                                    "omdb_title": omdb_result.title,
                                    "omdb_year": omdb_result.year,
                                    "omdb_type": omdb_result.media_type,
                                }]).get(0)
                                if v_res and not v_res.get("is_match", True):
                                    is_valid = False
                            except Exception as e:
                                logger.warning(f"AI candidate validation check failed: {e}")

                if omdb_result and is_valid:
                    norm_lookup_title = normalize_title(omdb_result.title)
                    title_id = get_title_id(omdb_result.imdb_id, norm_lookup_title, omdb_result.year, omdb_result.media_type)

                    title_record = Title(
                        title=omdb_result.title,
                        normalized_title=norm_lookup_title,
                        year=omdb_result.year,
                        media_type=omdb_result.media_type,
                        first_seen_at=log.processed_at or self.now,
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
                        source_type=effective_source_type(omdb_result.media_type, omdb_result.source_type),
                        content_kind=omdb_result.content_kind,
                        broadcast_range=omdb_result.broadcast_range,
                    )

                    occ_id = get_occurrence_id(None, log.raw_title)
                    occ_record = Occurrence(
                        source_feed_id=log.feed_name or "reparsed",
                        source_feed_name=log.feed_name or "reparsed",
                        feed_entry_id=None,
                        torrent_url="",
                        raw_title=log.raw_title,
                        quality="",
                        rip_type="",
                        first_seen_at=log.processed_at or self.now,
                        last_seen_at=self.now,
                    )

                    if not self.config.is_dry_run:
                        self.title_repo.upsert(title_id, title_record)
                        self.occurrence_repo.upsert(title_id, occ_id, occ_record)

                    self._log_parse_entry(
                        raw_title=log.raw_title,
                        feed_name=log.feed_name or "reparsed",
                        parsed_successfully=True,
                        parsed_title=title,
                        parsed_year=year,
                        omdb_status="found",
                        ignored=False,
                        ignore_reason=None,
                        section_timings=section_timings,
                        trace_details={
                            "feedType": stored_feed_type,
                            "expectedSourceType": expected_source_type,
                            "matchDecision": match_decision.status,
                            "matchReasonCode": match_decision.reason_code,
                            "omdbSourceType": effective_source_type(
                                omdb_result.media_type,
                                omdb_result.source_type,
                            ),
                            "omdbContentKind": omdb_result.content_kind,
                            "omdbBroadcastRange": (
                                omdb_result.broadcast_range.to_dict()
                                if omdb_result.broadcast_range is not None
                                else None
                            ),
                        },
                    )
                    stats["reparsed_succeeded"] += 1
                    if run:
                        run.titles_created += 1
                        run.occurrences_created += 1
                else:
                    stats["reparsed_failed"] += 1

            self._flush_parse_logs(section_timings)

        logger.info(f"AI re-parsing completed: {stats}")
        return stats

    def _reparse_unfound_entries(
        self,
        run: Optional[ScanRun] = None,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> Dict[str, int]:
        return self.reparse_unfound_entries(run=run, section_timings=section_timings)

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

        entry_dt = _get_entry_datetime(entry)
        item_time = entry_dt if entry_dt is not None else datetime.datetime.now(datetime.timezone.utc)

        if self.config.force_days > 0:
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
                error_message=None,
                feed_entry_id=feed_entry_id,
                torrent_url=torrent_url,
                section_timings=section_timings,
            )
            return

        parse_error: Optional[str] = None
        try:
            t0_parse = time.perf_counter()
            parsed = parse_rutracker_title(
                raw_title,
                content_type=feed_def.get("type"),
                video_settings=self.config.video_settings,
            )
            section_timings["title_parse"] += (time.perf_counter() - t0_parse)
        except Exception as e:
            logger.error(f"Error parsing rutracker title '{raw_title}': {e}", exc_info=True)
            parsed = ParsedTitle(title="", year=None, is_series=False, quality="", rip_type="")
            parse_error = f"Грешка при парсване: {e}"

        if not parsed.title:
            run.ignored_entries += 1
            if parse_error:
                run.error_count += 1
                run.error_summary.append(f"Parse error for '{raw_title}': {parse_error}")

            self._log_parse_entry(
                raw_title=raw_title,
                feed_name=feed_name,
                parsed_successfully=False,
                parsed_title=None,
                parsed_year=None,
                omdb_status="not_parsed",
                ignored=True,
                ignore_reason="parse_error" if parse_error else "no_title",
                error_message=parse_error,
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

        base_trace = {
            "parsedTitle": parsed.title,
            "parsedYear": lookup_year,
            "parsedQuality": parsed.quality or None,
            "parsedRipType": parsed.rip_type or None,
            "parsedIsSeries": parsed.is_series,
            "feedName": feed_name,
            "feedType": feed_def.get("type"),
        }
        expected_source_type = self._expected_source_type(feed_def.get("type"), parsed.is_series)
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
                section_timings=section_timings,
                trace_details={**base_trace, "decision": "ignored_parse_only", "decisionDetails": "Parse only mode"},
            )
            return

        cache_key = get_cache_key(parsed.title, lookup_year)
        t0_cache = time.perf_counter()
        cache_entry = self._get_cache_entry(cache_key)
        section_timings["cache_lookup"] += (time.perf_counter() - t0_cache)

        omdb_payload = None
        omdb_result = None
        used_manual_mapping = False

        # Check if there is a manual IMDb mapping provided for this title
        entry_log_id = get_occurrence_id(feed_entry_id, torrent_url)
        manual_mapping = (
            self._manual_mappings_by_id.get(entry_log_id)
            or self._manual_mappings_by_raw_title.get(raw_title.strip().lower())
            or (self._manual_mappings_by_parsed_title.get(normalize_title(parsed.title)) if parsed.title else None)
        )

        if manual_mapping and manual_mapping.imdb_id:
            run.omdb_requests += 1
            status = "not_found"
            payload = None
            t0_omdb = time.perf_counter()
            try:
                omdb_result = self.omdb_client.get_by_imdb_id(manual_mapping.imdb_id)
                status = "found"
                payload = omdb_result.raw_payload
                used_manual_mapping = True
                
                # If successfully retrieved by IMDb ID, delete manual mapping so it isn't reprocessed
                if not self.config.is_dry_run and self.manual_mapping_repo:
                    self.manual_mapping_repo.delete(manual_mapping.id)
                self._manual_mappings_by_id.pop(manual_mapping.id, None)
                if manual_mapping.raw_title:
                    self._manual_mappings_by_raw_title.pop(manual_mapping.raw_title.strip().lower(), None)
                if manual_mapping.parsed_title:
                    self._manual_mappings_by_parsed_title.pop(normalize_title(manual_mapping.parsed_title), None)
            except OmdbNoMatchError:
                pass
            except OmdbLimitReachedError:
                raise
            except OmdbTransportError as e:
                run.error_count += 1
                run.error_summary.append(f"OMDb Transport Error for IMDb ID {manual_mapping.imdb_id}: {str(e)}")
                self._log_parse_entry(
                    raw_title=raw_title,
                    feed_name=feed_name,
                    parsed_successfully=True,
                    parsed_title=parsed.title,
                    parsed_year=lookup_year,
                    omdb_status="error",
                    ignored=True,
                    ignore_reason="omdb_error",
                    error_message=f"OMDb Transport Error: {str(e)}",
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    section_timings=section_timings,
                    trace_details={**base_trace, "decision": "error_omdb_transport", "decisionDetails": str(e)},
                )
                return
            finally:
                section_timings["omdb_api"] += (time.perf_counter() - t0_omdb)

            if status == "found" and omdb_result:
                new_cache = OmdbCacheEntry(
                    lookup_title=parsed.title,
                    lookup_year=lookup_year,
                    status="found",
                    payload=payload,
                    fetched_at=self.now,
                    expires_at=self.now + datetime.timedelta(days=self.config.cache_ttl_days),
                )
                self._set_cache_entry(cache_key, new_cache)

        if omdb_result is None and cache_entry and cache_entry.expires_at > self.now:
            run.cache_hits += 1
            cache_info = {
                "cacheKey": cache_key,
                "cacheHit": True,
                "cacheStatus": cache_entry.status,
                "cacheFetchedAt": cache_entry.fetched_at.strftime('%Y-%m-%d %H:%M') if cache_entry.fetched_at else None,
            }
            if cache_entry.status != "found" or not cache_entry.payload:
                run.ignored_entries += 1
                err_msg = f"OMDb кеш статус '{cache_entry.status}' (записан на {cache_entry.fetched_at.strftime('%Y-%m-%d %H:%M') if cache_entry.fetched_at else 'предишен скан'})"
                logger.info(f"[Scanner:Cache] '{parsed.title}' ({lookup_year}) -> HIT negative cache: {cache_key}")
                self._log_parse_entry(
                    raw_title=raw_title,
                    feed_name=feed_name,
                    parsed_successfully=True,
                    parsed_title=parsed.title,
                    parsed_year=lookup_year,
                    omdb_status="not_found",
                    ignored=True,
                    ignore_reason="omdb_not_found",
                    error_message=err_msg,
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    section_timings=section_timings,
                    trace_details={**base_trace, **cache_info, "decision": "ignored_omdb_not_found", "decisionDetails": err_msg},
                )
                return
            omdb_payload = cache_entry.payload
            omdb_result = self.omdb_client._normalize_payload(omdb_payload)
            logger.info(f"[Scanner:Cache] '{parsed.title}' ({lookup_year}) -> HIT positive cache: {omdb_result.title} ({omdb_result.year}) [{omdb_result.imdb_id}]")
        elif omdb_result is None:
            if run.omdb_requests >= self.config.omdb_limit:
                logger.info("Soft limit reached for OMDb requests in this run.")
                run.ignored_entries += 1
                err_msg = "Достигнат лимит на OMDb заявки за това сканиране"
                self._log_parse_entry(
                    raw_title=raw_title,
                    feed_name=feed_name,
                    parsed_successfully=True,
                    parsed_title=parsed.title,
                    parsed_year=lookup_year,
                    omdb_status="skipped",
                    ignored=True,
                    ignore_reason="omdb_limit_reached",
                    error_message=err_msg,
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    section_timings=section_timings,
                    trace_details={**base_trace, "decision": "ignored_omdb_limit_reached", "decisionDetails": err_msg},
                )
                return

            run.omdb_requests += 1
            status = "not_found"
            payload = None
            t0_omdb = time.perf_counter()
            media_type_hint = expected_source_type
            logger.info(f"[Scanner:OMDb Query] Requesting OMDb for '{parsed.title}', Year: {lookup_year}, Hint: '{media_type_hint}'")
            try:
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
                    error_message=f"OMDb Transport Error: {str(e)}",
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    section_timings=section_timings,
                    trace_details={**base_trace, "decision": "error_omdb_transport", "decisionDetails": str(e)},
                )
                return
            finally:
                section_timings["omdb_api"] += (time.perf_counter() - t0_omdb)
            
            # Use shorter TTL (2 days) for negative cache so newly added titles are checked again sooner
            cache_days = self.config.cache_ttl_days if status == "found" else min(2, self.config.cache_ttl_days)
            new_cache = OmdbCacheEntry(
                lookup_title=parsed.title,
                lookup_year=lookup_year,
                status=status,
                payload=payload,
                fetched_at=self.now,
                expires_at=self.now + datetime.timedelta(days=cache_days),
            )
            t0_cache_write = time.perf_counter()
            self._set_cache_entry(cache_key, new_cache)
            section_timings["cache_lookup"] += (time.perf_counter() - t0_cache_write)

            if status != "found":
                run.ignored_entries += 1
                err_msg = f"OMDb не намери заглавие '{parsed.title}' (търсено с година: {lookup_year}, тип: {media_type_hint or 'всички'})"
                logger.info(f"[Scanner:OMDb Result] '{parsed.title}' ({lookup_year}) -> NOT FOUND in OMDb")
                self._log_parse_entry(
                    raw_title=raw_title,
                    feed_name=feed_name,
                    parsed_successfully=True,
                    parsed_title=parsed.title,
                    parsed_year=lookup_year,
                    omdb_status="not_found",
                    ignored=True,
                    ignore_reason="omdb_not_found",
                    error_message=err_msg,
                    feed_entry_id=feed_entry_id,
                    torrent_url=torrent_url,
                    section_timings=section_timings,
                    trace_details={
                        **base_trace,
                        "cacheKey": cache_key,
                        "cacheHit": False,
                        "omdbQueryTitle": parsed.title,
                        "omdbQueryYear": lookup_year,
                        "omdbQueryType": media_type_hint,
                        "decision": "ignored_omdb_not_found",
                        "decisionDetails": err_msg,
                    },
                )
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
        title_id = get_title_id(imdb_id, norm_lookup_title, lookup_year, media_type)

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
            source_type=effective_source_type(omdb_result.media_type, omdb_result.source_type),
            content_kind=omdb_result.content_kind,
            broadcast_range=omdb_result.broadcast_range,
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
            first_seen_at=item_time,
            last_seen_at=item_time,
        )

        # Upsert
        if not self.config.is_dry_run:
            self._stage_title_and_occurrence(title_id, title_record, occurrence_id, occurrence_record, run)
        else:
            # Simulate creation tracking for dry run without storing
            run.titles_created += 1
            run.occurrences_created += 1
