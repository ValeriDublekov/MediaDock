"""Explicit codecs for documents stored in Firestore."""

import datetime
from typing import Any, Dict, Optional

from .match_policy import broadcast_range_from_dict, effective_source_type
from .models import (
    ManualMapping,
    OmdbCacheEntry,
    Occurrence,
    ParseLog,
    ParseLogResolution,
    RssSnapshot,
    RssSnapshotItem,
    ScanRun,
    SourceContext,
    Title,
)
from .repository import effective_retry_state


def title_from_dict(d: dict) -> Title:
    """Reconstruct a title from its camelCase Firestore document."""
    if not isinstance(d, dict) or "title" not in d:
        keys_str = list(d.keys()) if isinstance(d, dict) else str(type(d))
        raise KeyError(f"Document missing required 'title' field (keys present: {keys_str})")
    media_type = d.get("mediaType", "movie")
    content_kind = d.get("contentKind")
    if content_kind is None:
        content_kind = media_type if media_type in ("documentary", "short") else "standard"
    return Title(
        title=d["title"],
        normalized_title=d.get("normalizedTitle", d["title"].lower()),
        year=d.get("year"),
        media_type=media_type,
        first_seen_at=d.get("firstSeenAt", datetime.datetime.now(datetime.timezone.utc)),
        last_seen_at=d.get("lastSeenAt", datetime.datetime.now(datetime.timezone.utc)),
        updated_at=d.get("updatedAt", datetime.datetime.now(datetime.timezone.utc)),
        imdb_id=d.get("imdbId"),
        imdb_rating=d.get("imdbRating") if d.get("imdbRating") is None else float(d["imdbRating"]),
        imdb_votes=d.get("imdbVotes") if d.get("imdbVotes") is None else int(d["imdbVotes"]),
        metascore=d.get("metascore") if d.get("metascore") is None else int(d["metascore"]),
        genres=d.get("genres") or [],
        countries=d.get("countries") or [],
        director=d.get("director"),
        plot=d.get("plot"),
        poster_url=d.get("posterUrl"),
        runtime=d.get("runtime"),
        awards=d.get("awards"),
        box_office=d.get("boxOffice"),
        ratings=d.get("ratings") or [],
        ai_validated=d.get("aiValidated"),
        ai_checked_at=d.get("aiCheckedAt"),
        source_type=d.get("sourceType") or effective_source_type(media_type),
        content_kind=content_kind,
        broadcast_range=broadcast_range_from_dict(d.get("broadcastRange")),
    )


def source_context_from_dict(d: dict) -> Optional[SourceContext]:
    """Read optional flat provenance fields without inferring legacy context."""
    context_markers = ("feedType", "sourcePublishedAt", "observedAt")
    if not any(field_name in d for field_name in context_markers):
        return None
    return SourceContext(
        source_feed_id=d.get("sourceFeedId"),
        source_feed_name=d.get("sourceFeedName"),
        feed_type=d.get("feedType"),
        feed_entry_id=d.get("feedEntryId"),
        torrent_url=d.get("torrentUrl"),
        raw_title=d.get("rawTitle"),
        source_published_at=d.get("sourcePublishedAt"),
        observed_at=d.get("observedAt"),
    )


def occurrence_from_dict(d: dict) -> Occurrence:
    """Reconstruct an occurrence from its camelCase Firestore document."""
    return Occurrence(
        source_feed_id=d["sourceFeedId"],
        source_feed_name=d["sourceFeedName"],
        feed_entry_id=d.get("feedEntryId"),
        torrent_url=d["torrentUrl"],
        raw_title=d["rawTitle"],
        quality=d.get("quality"),
        rip_type=d.get("ripType"),
        first_seen_at=d["firstSeenAt"],
        last_seen_at=d["lastSeenAt"],
        source_context=source_context_from_dict(d),
        validation_status=d.get("validationStatus"),
        validation_policy_version=d.get("validationPolicyVersion"),
        validated_at=d.get("validatedAt"),
        validation_reason=d.get("validationReason"),
    )


def cache_entry_from_dict(d: dict) -> OmdbCacheEntry:
    """Reconstruct an OMDb cache entry from its Firestore document."""
    return OmdbCacheEntry(
        lookup_title=d["lookupTitle"],
        lookup_year=d.get("lookupYear"),
        status=d["status"],
        payload=d.get("payload"),
        fetched_at=d["fetchedAt"],
        expires_at=d["expiresAt"],
        lookup_year_semantics=d.get("lookupYearSemantics"),
        source_type=d.get("sourceType"),
        lookup_identity=d.get("lookupIdentity"),
    )


def scan_run_from_dict(d: dict) -> ScanRun:
    """Reconstruct a scan run from its camelCase Firestore document."""
    return ScanRun(
        started_at=d["startedAt"],
        finished_at=d.get("finishedAt"),
        status=d["status"],
        trigger=d["trigger"],
        feeds_processed=d.get("feedsProcessed", 0),
        entries_seen=d.get("entriesSeen", 0),
        titles_created=d.get("titlesCreated", 0),
        titles_updated=d.get("titlesUpdated", 0),
        occurrences_created=d.get("occurrencesCreated", 0),
        occurrences_updated=d.get("occurrencesUpdated", 0),
        cache_hits=d.get("cacheHits", 0),
        omdb_requests=d.get("omdbRequests", 0),
        ignored_entries=d.get("ignoredEntries", 0),
        ai_calls=d.get("aiCalls", 0),
        ai_items_processed=d.get("aiItemsProcessed", 0),
        ai_failures=d.get("aiFailures", 0),
        retries_attempted=d.get("retriesAttempted", 0),
        retries_resolved=d.get("retriesResolved", 0),
        retries_failed=d.get("retriesFailed", 0),
        proposals_created=d.get("proposalsCreated", 0),
        proposals_applied=d.get("proposalsApplied", 0),
        proposals_failed=d.get("proposalsFailed", 0),
        error_count=d.get("errorCount", 0),
        error_summary=d.get("errorSummary") or [],
        section_timings=d.get("sectionTimings") or {},
        phase_metrics=d.get("phaseMetrics") or {},
    )


def parse_log_from_dict(d: dict, doc_id: Optional[str] = None) -> ParseLog:
    """Reconstruct a parse log from its camelCase Firestore document."""
    log_id = d.get("id") or doc_id or ""
    retry_state = d.get("retryState")
    if retry_state not in ("retryable", "terminal", "resolved"):
        retry_state = None
    attempt_count = d.get("attemptCount", 0)
    if not isinstance(attempt_count, int) or isinstance(attempt_count, bool) or attempt_count < 0:
        attempt_count = 0
    resolution = None
    resolution_data = d.get("resolution")
    if isinstance(resolution_data, dict):
        try:
            resolution = ParseLogResolution(
                resolved_at=resolution_data["resolvedAt"],
                outcome=resolution_data["outcome"],
                reason=resolution_data["reason"],
                title_id=resolution_data.get("titleId"),
                occurrence_id=resolution_data.get("occurrenceId"),
            )
        except (KeyError, TypeError, ValueError):
            resolution = None
    log = ParseLog(
        id=log_id,
        raw_title=d.get("rawTitle", ""),
        feed_name=d.get("feedName", ""),
        parsed_successfully=d.get("parsedSuccessfully", False),
        parsed_title=d.get("parsedTitle"),
        parsed_year=d.get("parsedYear"),
        omdb_status=d.get("omdbStatus", "not_parsed"),
        ignored=d.get("ignored", False),
        ignore_reason=d.get("ignoreReason"),
        processed_at=d.get("processedAt") or datetime.datetime.now(datetime.timezone.utc),
        error_message=d.get("errorMessage"),
        trace_details=d.get("traceDetails"),
        decision=d.get("decision"),
        source_context=source_context_from_dict(d),
        event_kind=d.get("eventKind"),
        retry_state=retry_state,
        attempt_count=attempt_count,
        last_attempt_at=d.get("lastAttemptAt"),
        resolution=resolution,
    )
    log.retry_state = effective_retry_state(log)
    if log.retry_state == "retryable" or (
        log.resolution is not None
        and (
            (log.retry_state == "resolved" and log.resolution.outcome != "matched")
            or (log.retry_state == "terminal" and log.resolution.outcome != "terminal")
        )
    ):
        log.resolution = None
    return log


def manual_mapping_from_dict(d: dict, doc_id: Optional[str] = None) -> ManualMapping:
    """Reconstruct a manual mapping from its camelCase Firestore document."""
    mapping_id = d.get("id") or doc_id or ""
    return ManualMapping(
        id=mapping_id,
        raw_title=d.get("rawTitle", ""),
        imdb_id=d.get("imdbId", ""),
        created_at=d.get("createdAt") or datetime.datetime.now(datetime.timezone.utc),
        parsed_title=d.get("parsedTitle"),
        parsed_year=d.get("parsedYear"),
        created_by=d.get("createdBy"),
    )


def rss_snapshot_item_from_dict(d: dict) -> RssSnapshotItem:
    """Reconstruct an RSS snapshot item from its Firestore document."""
    return RssSnapshotItem(
        title_id=d["titleId"],
        source_type=d["sourceType"],
        group_order=d["groupOrder"],
        feed_order=d["feedOrder"],
        entry_order=d["entryOrder"],
        rss_position=d["rssPosition"],
    )


def rss_snapshot_from_dict(d: dict, doc_id: Optional[str] = None) -> RssSnapshot:
    """Reconstruct RSS snapshot metadata from its Firestore document."""
    return RssSnapshot(
        id=d.get("id") or doc_id or "",
        run_id=d["runId"],
        created_at=d["createdAt"],
        item_count=d.get("itemCount", 0),
        status=d.get("status", "ready"),
    )