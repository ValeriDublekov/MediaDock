import copy
import datetime
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

from .ai_matcher import AiMatcher
from .ai_validator import validate_batch_recheck_results, validate_batch_validate_omdb_results
from .audit_proposal import AuditProposal, ProposalSourceSnapshot, ProposalTarget
from .ids import clean_title_for_comparison, get_audit_proposal_id_v3, get_source_item_id
from .match_policy import MatchDecision, effective_source_type, evaluate_match
from .metadata_resolver import MetadataOutcome, MetadataOutcomeStatus, MetadataResolver
from .models import Occurrence, ScanRun, Title
from .omdb_client import OmdbMovieResult
from .repository import AuditProposalRepository, OccurrenceRepository, TitleRepository
from .rutracker_parser import parse_rutracker_title

if TYPE_CHECKING:
    from .scanner import ScannerConfig


logger = logging.getLogger(__name__)


@dataclass
class RecheckSuggestionOutcome:
    omdb_status: str = "skipped"
    omdb_outcome: str = "missing_corrected_title"
    candidate_outcome: str = "not_evaluated"
    retryable: bool = False
    match_decision: Optional[str] = None
    match_reason_code: Optional[str] = None
    candidate: Optional[OmdbMovieResult] = None


class ExistingTitleAuditService:
    def __init__(
        self,
        *,
        config: "ScannerConfig",
        title_repo: TitleRepository,
        occurrence_repo: OccurrenceRepository,
        audit_proposal_repo: Optional[AuditProposalRepository],
        get_ai_matcher: Callable[[], Optional[AiMatcher]],
        metadata_resolver: MetadataResolver,
        clock: Callable[[], datetime.datetime],
        flush_parse_logs: Callable[[Optional[Dict[str, float]]], None],
        log_parse_entry: Callable[..., None],
        record_phase_error: Callable[[Optional[ScanRun], str], None],
        record_metadata_outcome_failure: Callable[[Optional[ScanRun], MetadataOutcome, str], None],
        sync_omdb_attempts: Callable[[Optional[ScanRun]], None],
        evaluate_match_callback: Callable[..., MatchDecision],
        on_proposal_created: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.config = config
        self.title_repo = title_repo
        self.occurrence_repo = occurrence_repo
        self.audit_proposal_repo = audit_proposal_repo
        self._get_ai_matcher = get_ai_matcher
        self.metadata_resolver = metadata_resolver
        self.clock = clock
        self._flush_parse_logs = flush_parse_logs
        self._log_parse_entry = log_parse_entry
        self._record_phase_error = record_phase_error
        self._record_metadata_outcome_failure = record_metadata_outcome_failure
        self._sync_omdb_attempts = sync_omdb_attempts
        self._evaluate_match = evaluate_match_callback
        self._on_proposal_created = on_proposal_created

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
            audit_event_identity=f"recheck:{title_id}:{audit_outcome}",
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
    ) -> RecheckSuggestionOutcome:
        outcome = RecheckSuggestionOutcome()
        if not corrected_title:
            return outcome

        lookup_title = corrected_title.strip()
        if not lookup_title:
            outcome.omdb_outcome = "invalid_request"
            outcome.candidate_outcome = "not_evaluated"
            return outcome

        resolver_outcome = self.metadata_resolver.resolve_title(
            lookup_title,
            corrected_year,
            media_type=corrected_media_type,
            section_timings=section_timings,
        )
        self._sync_omdb_attempts(run)
        if resolver_outcome.status is MetadataOutcomeStatus.CONFIRMED_NOT_FOUND:
            outcome.omdb_status = "not_found"
            outcome.omdb_outcome = "confirmed_not_found"
            return outcome
        if resolver_outcome.status is not MetadataOutcomeStatus.FOUND:
            outcome.omdb_status = "error"
            outcome.omdb_outcome = (
                "malformed_result"
                if resolver_outcome.status is MetadataOutcomeStatus.UNEXPECTED_ERROR
                and resolver_outcome.error_message == "OMDb returned malformed metadata"
                else resolver_outcome.status.value
            )
            outcome.retryable = resolver_outcome.status in (
                MetadataOutcomeStatus.QUOTA_EXHAUSTED,
                MetadataOutcomeStatus.TRANSPORT_ERROR,
                MetadataOutcomeStatus.UNEXPECTED_ERROR,
            )
            self._record_metadata_outcome_failure(run, resolver_outcome, "recheck")
            return outcome

        omdb_result = resolver_outcome.result

        if (
            not isinstance(omdb_result, OmdbMovieResult)
            or not isinstance(omdb_result.title, str)
            or not omdb_result.title.strip()
            or omdb_result.year is not None and type(omdb_result.year) is not int
            or omdb_result.media_type not in ("movie", "series", "documentary", "short")
            or not isinstance(omdb_result.countries, list)
            or not isinstance(omdb_result.genres, list)
        ):
            outcome.omdb_status = "error"
            outcome.omdb_outcome = "malformed_result"
            outcome.retryable = True
            self._record_phase_error(run, "OMDb phase incomplete during recheck")
            return outcome

        outcome.omdb_status = "found"
        match_decision = self._evaluate_match(
            expected_source_type=expected_source_type or corrected_media_type,
            omdb_result=omdb_result,
            source_year=corrected_year,
            manual_mapping=manual_mapping,
        )
        outcome.match_decision = match_decision.status
        outcome.match_reason_code = match_decision.reason_code
        if not match_decision.is_accepted:
            if match_decision.reason_code in ("excluded_country", "excluded_genre"):
                outcome.candidate_outcome = "excluded"
            elif match_decision.reason_code == "type_mismatch":
                outcome.candidate_outcome = "type_mismatch"
            elif "year" in match_decision.reason_code:
                outcome.candidate_outcome = "year_mismatch"
            else:
                outcome.candidate_outcome = "ambiguous"
            outcome.retryable = match_decision.is_ambiguous
            return outcome

        outcome.candidate_outcome = "valid_suggestion"
        ai_matcher = self._get_ai_matcher()
        if not (
            ai_matcher
            and ai_matcher.is_available
            and clean_title_for_comparison(lookup_title)
            != clean_title_for_comparison(omdb_result.title)
        ):
            outcome.candidate = omdb_result
            return outcome

        try:
            validation_results = ai_matcher.batch_validate_omdb_matches([{
                "id": 0,
                "raw_title": raw_title,
                "feed_type": expected_source_type or corrected_media_type or "unknown",
                "omdb_title": omdb_result.title,
                "omdb_year": omdb_result.year,
                "omdb_type": omdb_result.media_type,
            }])
        except Exception:
            validation_results = None

        candidate_validations = validate_batch_validate_omdb_results(validation_results, {0})
        candidate_validation = candidate_validations.get(0)
        if candidate_validation is None:
            outcome.candidate_outcome = "ai_validation_incomplete"
            outcome.retryable = True
            self._record_phase_error(run, "AI candidate validation incomplete during recheck")
            return outcome

        if not candidate_validation["is_match"]:
            outcome.candidate_outcome = "ai_rejected"
            return outcome
        outcome.candidate = omdb_result
        return outcome

    def recheck_existing_titles(
        self,
        run: Optional[ScanRun] = None,
        section_timings: Optional[Dict[str, float]] = None,
        audit_days: Optional[int] = None,
        excluded_title_ids: Optional[Set[str]] = None,
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
            "clusters_checked": 0,
            "valid_clusters": 0,
            "proposals": 0,
            "retryable_failures": 0,
            "orphans": 0,
        }

        CURRENT_POLICY_VERSION = "v1"

        all_titles = self.title_repo.list_all_ids_and_titles()
        if not all_titles:
            logger.info("No titles found in database to recheck.")
            return stats

        if excluded_title_ids:
            all_titles = [(tid, trec) for (tid, trec) in all_titles if tid not in excluded_title_ids]

        # Filter out already AI-validated titles
        unvalidated_titles = [
            (tid, trec) for (tid, trec) in all_titles if not trec.ai_validated
        ]

        if audit_days and audit_days > 0:
            cutoff = self.clock() - datetime.timedelta(days=audit_days)
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
                    stats["orphans"] += 1
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

                clusters = {}
                for occ in occs:
                    cluster_id = (occ.source_feed_id, occ.raw_title)
                    if cluster_id not in clusters:
                        clusters[cluster_id] = []
                    clusters[cluster_id].append(occ)

                for cluster_id, cluster_occs in clusters.items():
                    is_valid = all(
                        o.validation_status == "valid"
                        and o.validation_policy_version == CURRENT_POLICY_VERSION
                        for o in cluster_occs
                    )

                    if is_valid:
                        stats["valid_clusters"] += 1
                        continue

                    raw_title = cluster_id[1]
                    feed_name = cluster_occs[0].source_feed_name
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
                    chunk_context.append((ai_id, title_id, title_record, cluster_occs, raw_title, feed_name))

            stats["titles_checked"] += len(chunk)

            if not items_to_audit:
                self._flush_parse_logs(section_timings)
                self._check_aggregate_validity(chunk, CURRENT_POLICY_VERSION)
                continue

            audit_results: Any = {}
            batch_failure_reason = "AI matcher is unavailable"
            ai_matcher = self._get_ai_matcher()
            if ai_matcher and ai_matcher.is_available:
                try:
                    audit_results = ai_matcher.batch_recheck_matches(items_to_audit)
                    batch_failure_reason = "AI response was empty, incomplete, or malformed"
                except Exception as e:
                    batch_failure_reason = f"AI matcher call failed ({type(e).__name__})"
                    logger.warning(f"AI batch_recheck_matches failed: {type(e).__name__}")

            audit_results = validate_batch_recheck_results(
                audit_results,
                {item["id"] for item in items_to_audit},
            )
            if not audit_results:
                stats["ai_failures"] += 1
                stats["retryable_failures"] += len(items_to_audit)
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

            for ai_id, title_id, title_record, cluster_occs, raw_title, feed_name in chunk_context:
                stats["clusters_checked"] += 1
                ai_res = audit_results[ai_id]
                deterministic_decision = self._evaluate_existing_title_match(title_record, raw_title)

                confidence = float(ai_res.get("confidence", 0.0) if ai_res.get("confidence") is not None else 0.0)
                is_valid = ai_res["is_valid_match"] is True and not deterministic_decision.is_rejected

                if is_valid:
                    stats["validated"] += 1
                    stats["valid_clusters"] += 1
                    if not self.config.is_dry_run:
                        for occ in cluster_occs:
                            occ.validation_status = "valid"
                            occ.validation_policy_version = CURRENT_POLICY_VERSION
                            occ.validated_at = self.clock()
                            occ.validation_reason = ai_res.get("reason")
                            occ_id = get_source_item_id(occ.source_feed_id, occ.feed_entry_id, occ.torrent_url)
                            self.occurrence_repo.upsert(title_id, occ_id, occ)
                else:
                    stats["mismatches_found"] += 1
                    stats["needs_review"] += 1
                    stats["proposals"] += 1
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
                    if suggestion.omdb_status == "error":
                        stats["omdb_failures"] += 1

                    trace_details = {
                        "aiReason": reason,
                        "policyReasonCode": deterministic_decision.reason_code,
                        "suggestedTitle": corr_title,
                        "suggestedYear": corr_year,
                        "suggestedMediaType": corr_media_type,
                        "omdbOutcome": suggestion.omdb_outcome,
                        "candidateOutcome": suggestion.candidate_outcome,
                        "candidateMatchDecision": suggestion.match_decision,
                        "candidateMatchReasonCode": suggestion.match_reason_code,
                    }
                    self._record_recheck_needs_review(
                        title_id=title_id,
                        title_record=title_record,
                        occurrences=cluster_occs,
                        raw_title=raw_title,
                        feed_name=feed_name,
                        audit_outcome="mismatch_retained",
                        reason=reason,
                        omdb_status=suggestion.omdb_status,
                        parsed_title=corr_title,
                        parsed_year=corr_year,
                        trace_details=trace_details,
                        section_timings=section_timings,
                    )

                    occ_ids = sorted(
                        get_source_item_id(o.source_feed_id, o.feed_entry_id, o.torrent_url)
                        for o in cluster_occs
                    )
                    proposal_id = get_audit_proposal_id_v3(
                        source_title_id=title_id,
                        source_feed_id=cluster_occs[0].source_feed_id,
                        raw_title=raw_title,
                        occurrence_ids=occ_ids,
                        policy_version=CURRENT_POLICY_VERSION,
                    )
                    source_snapshot = ProposalSourceSnapshot(
                        title=title_record.title,
                        year=title_record.year,
                        imdb_id=title_record.imdb_id,
                        media_type=effective_source_type(title_record.media_type, title_record.source_type),
                        source_type=title_record.source_type,
                        content_kind=title_record.content_kind,
                        broadcast_range=title_record.broadcast_range,
                    )
                    target = None
                    if suggestion.candidate is not None:
                        candidate_media_type = effective_source_type(
                            suggestion.candidate.media_type,
                            suggestion.candidate.source_type,
                        )
                        if candidate_media_type in ("movie", "series"):
                            target = ProposalTarget(
                                title=suggestion.candidate.title,
                                year=suggestion.candidate.year,
                                imdb_id=suggestion.candidate.imdb_id,
                                media_type=candidate_media_type,
                                content_kind=suggestion.candidate.content_kind,
                                broadcast_range=suggestion.candidate.broadcast_range,
                            )
                    prop = AuditProposal(
                        id=proposal_id,
                        source_title_id=title_id,
                        occurrence_ids=occ_ids,
                        raw_title_cluster=[raw_title],
                        current_metadata=source_snapshot.to_dict(),
                        proposed_metadata=target.to_dict() if target is not None else {},
                        evidence={
                            "reason": reason,
                            "policy_reason_code": deterministic_decision.reason_code,
                            "ai_confidence": confidence,
                            "source_feed_name": feed_name,
                            "omdb_outcome": suggestion.omdb_outcome,
                        },
                        confidence=confidence,
                        policy_version=CURRENT_POLICY_VERSION,
                        created_at=self.clock(),
                        updated_at=self.clock(),
                        status="pending",
                        action_kind="repair" if target is not None else "review_only",
                        target=target,
                    )
                    if self._on_proposal_created:
                        self._on_proposal_created(proposal_id)
                    if not self.config.is_dry_run and self.audit_proposal_repo:
                        self.audit_proposal_repo.refresh_from_audit(prop)

            self._flush_parse_logs(section_timings)
            self._check_aggregate_validity(chunk, CURRENT_POLICY_VERSION)

            # Brief rate-limit pause between AI batches if more remain
            ai_matcher = self._get_ai_matcher()
            if batch_idx < total_batches and ai_matcher and ai_matcher.is_available:
                time.sleep(5.0)

        logger.info(f"AI database recheck completed: {stats}")
        return stats

    def _check_aggregate_validity(self, chunk: List[tuple[str, Title]], policy_version: str) -> None:
        if self.config.is_dry_run:
            return
        for title_id, title_record in chunk:
            occs = self.occurrence_repo.list_by_title(title_id)
            if not occs:
                continue
            is_aggregate_valid = all(
                o.validation_status == "valid" and o.validation_policy_version == policy_version
                for o in occs
            )
            if is_aggregate_valid and not title_record.ai_validated:
                validated_title = copy.deepcopy(title_record)
                validated_title.ai_validated = True
                validated_title.ai_checked_at = self.clock()
                self.title_repo.upsert(title_id, validated_title)