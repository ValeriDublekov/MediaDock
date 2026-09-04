import datetime
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from .ids import get_cache_key, normalize_title
from .match_policy import normalize_source_type
from .models import OmdbCacheEntry
from .omdb_client import (
    OmdbAuthenticationError,
    OmdbClient,
    OmdbError,
    OmdbInvalidRequestError,
    OmdbLimitReachedError,
    OmdbMovieResult,
    OmdbNoMatchError,
    OmdbServiceError,
    OmdbTransportError,
)
from .repository import OmdbCacheRepository

logger = logging.getLogger(__name__)


class MetadataOutcomeStatus(str, Enum):
    FOUND = "found"
    CONFIRMED_NOT_FOUND = "confirmed_not_found"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TRANSPORT_ERROR = "transport_error"
    INVALID_REQUEST = "invalid_request"
    UNEXPECTED_ERROR = "unexpected_error"


@dataclass(frozen=True)
class MetadataOutcome:
    status: MetadataOutcomeStatus
    result: Optional[OmdbMovieResult] = None
    cache_key: Optional[str] = None
    cache_hit: bool = False
    http_attempts: int = 0
    cache_seconds: float = 0.0
    api_seconds: float = 0.0
    error_message: Optional[str] = None

    @property
    def outcome(self) -> str:
        return self.status.value

    @property
    def is_found(self) -> bool:
        return self.status is MetadataOutcomeStatus.FOUND and self.result is not None


@dataclass(frozen=True)
class _LookupContext:
    lookup_title: str
    lookup_year: Optional[int]
    source_type: str
    year_semantics: str
    lookup_identity: Optional[str] = None

    @property
    def cache_key(self) -> str:
        return get_cache_key(
            self.lookup_title,
            self.lookup_year,
            media_type=self.source_type,
            year_semantics=self.year_semantics,
            lookup_identity=self.lookup_identity,
        )


class RequestBudget:
    """Run-scoped counter that guards each actual OMDb HTTP attempt."""

    def __init__(self, limit: int) -> None:
        self.limit = max(0, int(limit))
        self.attempts = 0
        self.quota_exhausted = False

    def reset(self, limit: int) -> None:
        self.limit = max(0, int(limit))
        self.attempts = 0
        self.quota_exhausted = False

    def acquire(self) -> None:
        if self.quota_exhausted or self.attempts >= self.limit:
            self.quota_exhausted = True
            raise OmdbLimitReachedError("OMDb request budget exhausted")
        self.attempts += 1

    def mark_quota_exhausted(self) -> None:
        self.quota_exhausted = True


class MetadataResolver(ABC):
    @abstractmethod
    def start_run(
        self,
        *,
        now: Optional[datetime.datetime] = None,
        request_limit: Optional[int] = None,
        is_dry_run: Optional[bool] = None,
    ) -> None:
        pass

    @abstractmethod
    def resolve_title(
        self,
        lookup_title: str,
        lookup_year: Optional[int] = None,
        media_type: Optional[str] = None,
        year_semantics: Optional[str] = None,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> MetadataOutcome:
        pass

    @abstractmethod
    def resolve_by_imdb_id(
        self,
        imdb_id: str,
        lookup_title: Optional[str] = None,
        lookup_year: Optional[int] = None,
        media_type: Optional[str] = None,
        year_semantics: Optional[str] = None,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> MetadataOutcome:
        pass

    @abstractmethod
    def prefetch(
        self,
        requests: Iterable[Tuple[str, Optional[int], Optional[str], Optional[str]]],
        section_timings: Optional[Dict[str, float]] = None,
    ) -> None:
        pass


class OmdbResolver(MetadataResolver):
    """Shared OMDb cache, classification, timing, and run-budget boundary."""

    def __init__(
        self,
        omdb_client: OmdbClient,
        cache_repo: OmdbCacheRepository,
        *,
        cache_ttl_days: int = 30,
        request_limit: int = 50,
        is_dry_run: bool = False,
        now: Optional[datetime.datetime] = None,
    ) -> None:
        self.omdb_client = omdb_client
        self.cache_repo = cache_repo
        self.cache_ttl_days = max(0, int(cache_ttl_days))
        self.is_dry_run = is_dry_run
        self._now = now or datetime.datetime.now(datetime.timezone.utc)
        self.budget = RequestBudget(request_limit)
        self._session_cache: Dict[str, Optional[OmdbCacheEntry]] = {}
        self._install_request_guard()

    @property
    def http_attempts(self) -> int:
        return self.budget.attempts

    @property
    def quota_exhausted(self) -> bool:
        return self.budget.quota_exhausted

    def start_run(
        self,
        *,
        now: Optional[datetime.datetime] = None,
        request_limit: Optional[int] = None,
        is_dry_run: Optional[bool] = None,
    ) -> None:
        if now is not None:
            self._now = now
        if request_limit is None:
            request_limit = self.budget.limit
        self.budget.reset(request_limit)
        if is_dry_run is not None:
            self.is_dry_run = is_dry_run
        self._session_cache.clear()
        self._install_request_guard()

    def prefetch(
        self,
        requests: Iterable[Tuple[str, Optional[int], Optional[str], Optional[str]]],
        section_timings: Optional[Dict[str, float]] = None,
    ) -> None:
        contexts = [
            self._build_context(title, year, media_type, semantics)
            for title, year, media_type, semantics in requests
        ]
        contexts = [context for context in contexts if context is not None]
        missing = [context for context in contexts if context.cache_key not in self._session_cache]
        if not missing:
            return

        t0 = time.perf_counter()
        fetched = self.cache_repo.get_many(list({context.cache_key for context in missing}))
        self._add_timing(section_timings, "cache_lookup", time.perf_counter() - t0)
        for context in missing:
            self._session_cache[context.cache_key] = fetched.get(context.cache_key)

    def resolve_title(
        self,
        lookup_title: str,
        lookup_year: Optional[int] = None,
        media_type: Optional[str] = None,
        year_semantics: Optional[str] = None,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> MetadataOutcome:
        context, validation_error = self._build_context_with_error(
            lookup_title,
            lookup_year,
            media_type,
            year_semantics,
        )
        if validation_error:
            return MetadataOutcome(
                status=MetadataOutcomeStatus.INVALID_REQUEST,
                error_message=validation_error,
            )
        return self._resolve(
            context,
            lambda: self.omdb_client.get_movie_info(
                context.lookup_title,
                str(context.lookup_year) if context.lookup_year is not None else None,
                media_type=context.source_type if context.source_type != "unknown" else None,
            ),
            section_timings=section_timings,
            method_name="get_movie_info",
        )

    def resolve_by_imdb_id(
        self,
        imdb_id: str,
        lookup_title: Optional[str] = None,
        lookup_year: Optional[int] = None,
        media_type: Optional[str] = None,
        year_semantics: Optional[str] = None,
        section_timings: Optional[Dict[str, float]] = None,
    ) -> MetadataOutcome:
        normalized_id = imdb_id.strip().lower() if isinstance(imdb_id, str) else ""
        if not re.fullmatch(r"tt\d{7,10}", normalized_id):
            return MetadataOutcome(
                status=MetadataOutcomeStatus.INVALID_REQUEST,
                error_message="IMDb ID has an invalid format",
            )
        context_title = lookup_title or normalized_id
        context, validation_error = self._build_context_with_error(
            context_title,
            lookup_year,
            media_type,
            year_semantics,
            lookup_identity=f"imdb:{normalized_id}",
        )
        if validation_error:
            return MetadataOutcome(
                status=MetadataOutcomeStatus.INVALID_REQUEST,
                error_message=validation_error,
            )
        outcome = self._resolve(
            context,
            lambda: self.omdb_client.get_by_imdb_id(normalized_id),
            section_timings=section_timings,
            method_name="get_by_imdb_id",
            expected_imdb_id=normalized_id,
        )
        return outcome

    def _resolve(
        self,
        context: _LookupContext,
        call: Callable[[], OmdbMovieResult],
        *,
        section_timings: Optional[Dict[str, float]],
        method_name: str,
        expected_imdb_id: Optional[str] = None,
    ) -> MetadataOutcome:
        cache_key = context.cache_key
        before_attempts = self.budget.attempts
        cache_elapsed = 0.0
        api_elapsed = 0.0

        t0_cache = time.perf_counter()
        cache_entry = self._get_cache_entry(cache_key)
        if cache_entry and self._is_matching_cache_entry(cache_entry, context):
            if cache_entry.expires_at > self._now:
                if cache_entry.status in ("confirmed_not_found", "not_found"):
                    cache_elapsed += time.perf_counter() - t0_cache
                    self._add_timing(section_timings, "cache_lookup", cache_elapsed)
                    return self._outcome(
                        MetadataOutcomeStatus.CONFIRMED_NOT_FOUND,
                        cache_key=cache_key,
                        cache_hit=True,
                        before_attempts=before_attempts,
                        cache_seconds=cache_elapsed,
                    )
                if cache_entry.status == "found" and cache_entry.payload:
                    cached_result = self._normalize_cached_result(cache_entry.payload)
                    if cached_result is not None and self._matches_imdb_id(cached_result, expected_imdb_id):
                        cache_elapsed += time.perf_counter() - t0_cache
                        self._add_timing(section_timings, "cache_lookup", cache_elapsed)
                        return self._outcome(
                            MetadataOutcomeStatus.FOUND,
                            result=cached_result,
                            cache_key=cache_key,
                            cache_hit=True,
                            before_attempts=before_attempts,
                            cache_seconds=cache_elapsed,
                        )
                    self._session_cache[cache_key] = None
        cache_elapsed += time.perf_counter() - t0_cache
        self._add_timing(section_timings, "cache_lookup", cache_elapsed)

        if self.budget.quota_exhausted:
            return self._outcome(
                MetadataOutcomeStatus.QUOTA_EXHAUSTED,
                cache_key=cache_key,
                before_attempts=before_attempts,
                cache_seconds=cache_elapsed,
            )

        t0_api = time.perf_counter()
        try:
            if not self._uses_native_request_guard(method_name):
                self.budget.acquire()
            result = call()
        except OmdbLimitReachedError as exc:
            self.budget.mark_quota_exhausted()
            api_elapsed = time.perf_counter() - t0_api
            self._add_timing(section_timings, "omdb_api", api_elapsed)
            return self._outcome(
                MetadataOutcomeStatus.QUOTA_EXHAUSTED,
                cache_key=cache_key,
                before_attempts=before_attempts,
                cache_seconds=cache_elapsed,
                api_seconds=api_elapsed,
                error_message=self._sanitize_error(exc),
            )
        except OmdbNoMatchError:
            api_elapsed = time.perf_counter() - t0_api
            self._add_timing(section_timings, "omdb_api", api_elapsed)
            self._store_cache(
                context,
                status=MetadataOutcomeStatus.CONFIRMED_NOT_FOUND.value,
                payload=None,
                section_timings=section_timings,
            )
            return self._outcome(
                MetadataOutcomeStatus.CONFIRMED_NOT_FOUND,
                cache_key=cache_key,
                before_attempts=before_attempts,
                cache_seconds=cache_elapsed,
                api_seconds=api_elapsed,
            )
        except OmdbTransportError as exc:
            api_elapsed = time.perf_counter() - t0_api
            self._add_timing(section_timings, "omdb_api", api_elapsed)
            return self._outcome(
                MetadataOutcomeStatus.TRANSPORT_ERROR,
                cache_key=cache_key,
                before_attempts=before_attempts,
                cache_seconds=cache_elapsed,
                api_seconds=api_elapsed,
                error_message=self._sanitize_error(exc),
            )
        except (OmdbInvalidRequestError, ValueError) as exc:
            api_elapsed = time.perf_counter() - t0_api
            self._add_timing(section_timings, "omdb_api", api_elapsed)
            return self._outcome(
                MetadataOutcomeStatus.INVALID_REQUEST,
                cache_key=cache_key,
                before_attempts=before_attempts,
                cache_seconds=cache_elapsed,
                api_seconds=api_elapsed,
                error_message=self._sanitize_error(exc),
            )
        except (OmdbAuthenticationError, OmdbServiceError, OmdbError) as exc:
            api_elapsed = time.perf_counter() - t0_api
            self._add_timing(section_timings, "omdb_api", api_elapsed)
            return self._outcome(
                MetadataOutcomeStatus.UNEXPECTED_ERROR,
                cache_key=cache_key,
                before_attempts=before_attempts,
                cache_seconds=cache_elapsed,
                api_seconds=api_elapsed,
                error_message=self._sanitize_error(exc),
            )
        except Exception as exc:
            api_elapsed = time.perf_counter() - t0_api
            self._add_timing(section_timings, "omdb_api", api_elapsed)
            return self._outcome(
                MetadataOutcomeStatus.UNEXPECTED_ERROR,
                cache_key=cache_key,
                before_attempts=before_attempts,
                cache_seconds=cache_elapsed,
                api_seconds=api_elapsed,
                error_message=self._sanitize_error(exc),
            )

        api_elapsed = time.perf_counter() - t0_api
        self._add_timing(section_timings, "omdb_api", api_elapsed)
        if not self._is_valid_result(result):
            return self._outcome(
                MetadataOutcomeStatus.UNEXPECTED_ERROR,
                cache_key=cache_key,
                before_attempts=before_attempts,
                cache_seconds=cache_elapsed,
                api_seconds=api_elapsed,
                error_message="OMDb returned malformed metadata",
            )
        if not self._matches_imdb_id(result, expected_imdb_id):
            return self._outcome(
                MetadataOutcomeStatus.UNEXPECTED_ERROR,
                cache_key=cache_key,
                before_attempts=before_attempts,
                cache_seconds=cache_elapsed,
                api_seconds=api_elapsed,
                error_message="OMDb returned a different IMDb ID",
            )

        payload = result.raw_payload if isinstance(result.raw_payload, dict) and result.raw_payload else result.to_dict()
        self._store_cache(
            context,
            status=MetadataOutcomeStatus.FOUND.value,
            payload=payload,
            section_timings=section_timings,
        )
        return self._outcome(
            MetadataOutcomeStatus.FOUND,
            result=result,
            cache_key=cache_key,
            before_attempts=before_attempts,
            cache_seconds=cache_elapsed,
            api_seconds=api_elapsed,
        )

    @staticmethod
    def _build_context_with_error(
        lookup_title: str,
        lookup_year: Optional[int],
        media_type: Optional[str],
        year_semantics: Optional[str],
        lookup_identity: Optional[str] = None,
    ) -> Tuple[Optional[_LookupContext], Optional[str]]:
        if not isinstance(lookup_title, str) or not lookup_title.strip():
            return None, "Lookup title must not be empty"
        if lookup_year is not None and (isinstance(lookup_year, bool) or type(lookup_year) is not int):
            return None, "Lookup year must be an integer or null"

        normalized_media_type = normalize_source_type(media_type)
        if isinstance(media_type, str) and media_type.strip().lower() not in ("", "movie", "series", "unknown"):
            return None, "Lookup media type is unsupported"
        normalized_semantics = year_semantics.strip().lower() if isinstance(year_semantics, str) else ""
        if not normalized_semantics:
            normalized_semantics = {
                "movie": "movie_release_year",
                "series": "series_season_year",
            }.get(normalized_media_type, "unknown_year")
        if normalized_semantics not in ("movie_release_year", "series_season_year", "unknown_year"):
            return None, "Lookup year semantics are unsupported"

        normalized_identity = lookup_identity.strip().lower() if isinstance(lookup_identity, str) else None
        return _LookupContext(
            lookup_title=normalize_title(lookup_title),
            lookup_year=lookup_year,
            source_type=normalized_media_type,
            year_semantics=normalized_semantics,
            lookup_identity=normalized_identity,
        ), None

    def _build_context(
        self,
        lookup_title: str,
        lookup_year: Optional[int],
        media_type: Optional[str],
        year_semantics: Optional[str],
    ) -> Optional[_LookupContext]:
        context, error = self._build_context_with_error(
            lookup_title,
            lookup_year,
            media_type,
            year_semantics,
        )
        return None if error else context

    def _get_cache_entry(self, cache_key: str) -> Optional[OmdbCacheEntry]:
        if cache_key not in self._session_cache:
            self._session_cache[cache_key] = self.cache_repo.get(cache_key)
        return self._session_cache[cache_key]

    @staticmethod
    def _is_matching_cache_entry(entry: OmdbCacheEntry, context: _LookupContext) -> bool:
        return (
            entry.lookup_title == context.lookup_title
            and entry.lookup_year == context.lookup_year
            and entry.lookup_year_semantics == context.year_semantics
            and entry.source_type == context.source_type
            and entry.lookup_identity == context.lookup_identity
        )

    def _normalize_cached_result(self, payload: Dict[str, Any]) -> Optional[OmdbMovieResult]:
        normalizer = getattr(self.omdb_client, "_normalize_payload", None)
        if not callable(normalizer):
            return None
        try:
            result = normalizer(payload)
        except Exception:
            return None
        return result if self._is_valid_result(result) else None

    @staticmethod
    def _is_valid_result(result: Any) -> bool:
        return (
            isinstance(result, OmdbMovieResult)
            and isinstance(result.title, str)
            and bool(result.title.strip())
            and (result.year is None or type(result.year) is int)
            and result.media_type in ("movie", "series", "documentary", "short")
            and isinstance(result.genres, list)
            and isinstance(result.countries, list)
        )

    @staticmethod
    def _matches_imdb_id(result: OmdbMovieResult, expected_imdb_id: Optional[str]) -> bool:
        if expected_imdb_id is None:
            return True
        return bool(result.imdb_id) and result.imdb_id.strip().lower() == expected_imdb_id

    def _store_cache(
        self,
        context: _LookupContext,
        *,
        status: str,
        payload: Optional[Dict[str, Any]],
        section_timings: Optional[Dict[str, float]],
    ) -> None:
        ttl_days = self.cache_ttl_days if status == MetadataOutcomeStatus.FOUND.value else min(2, self.cache_ttl_days)
        entry = OmdbCacheEntry(
            lookup_title=context.lookup_title,
            lookup_year=context.lookup_year,
            status=status,
            payload=payload,
            fetched_at=self._now,
            expires_at=self._now + datetime.timedelta(days=ttl_days),
            lookup_year_semantics=context.year_semantics,
            source_type=context.source_type,
            lookup_identity=context.lookup_identity,
        )
        self._session_cache[context.cache_key] = entry
        if self.is_dry_run:
            return
        t0 = time.perf_counter()
        try:
            self.cache_repo.set(context.cache_key, entry)
        except Exception as exc:
            logger.warning("Could not persist OMDb cache entry (%s)", type(exc).__name__)
        self._add_timing(section_timings, "cache_lookup", time.perf_counter() - t0)

    def _outcome(
        self,
        status: MetadataOutcomeStatus,
        *,
        before_attempts: int,
        cache_key: Optional[str] = None,
        result: Optional[OmdbMovieResult] = None,
        cache_hit: bool = False,
        cache_seconds: float = 0.0,
        api_seconds: float = 0.0,
        error_message: Optional[str] = None,
    ) -> MetadataOutcome:
        return MetadataOutcome(
            status=status,
            result=result,
            cache_key=cache_key,
            cache_hit=cache_hit,
            http_attempts=self.budget.attempts - before_attempts,
            cache_seconds=cache_seconds,
            api_seconds=api_seconds,
            error_message=error_message,
        )

    def _install_request_guard(self) -> None:
        setter = getattr(self.omdb_client, "set_request_guard", None)
        if callable(setter):
            setter(self.budget.acquire)

    def _uses_native_request_guard(self, method_name: str) -> bool:
        base_method = getattr(OmdbClient, method_name, None)
        client_method = getattr(type(self.omdb_client), method_name, None)
        return callable(getattr(self.omdb_client, "set_request_guard", None)) and client_method is base_method

    def _sanitize_error(self, error: Exception) -> str:
        message = str(error)
        api_key = getattr(self.omdb_client, "_api_key", "")
        if api_key:
            message = message.replace(api_key, "[REDACTED]")
        return re.sub(r"([?&](?:key|apikey|api_key)=)[^&\s]+", r"\1[REDACTED]", message, flags=re.IGNORECASE)

    @staticmethod
    def _add_timing(section_timings: Optional[Dict[str, float]], name: str, elapsed: float) -> None:
        if section_timings is not None:
            section_timings[name] = section_timings.get(name, 0.0) + elapsed