from __future__ import annotations

import copy
import datetime
import secrets
from typing import Any, Mapping, Optional

from firebase_admin import firestore

from .firestore_repository import (
    FirestoreAuditProposalRepository,
    FirestoreOccurrenceRepository,
    FirestoreTitleRepository,
    get_firestore_client,
    occurrence_from_dict,
    title_from_dict,
)
from .ids import get_title_id_v2, normalize_title
from .models import Occurrence, Title
from .proposal_application_store import (
    ApplicationCommitResult,
    LeaseResult,
    RepositoryProposalApplicationStore,
)
from .repository import merge_occurrences, merge_titles


_LEASE_COLLECTION = "proposalApplicationLeases"
_LEASE_EXPIRED_CODE = "lease_expired"
_LEASE_EXPIRED_REASON = "Application lease expired or was unrecoverable"
_LEASE_UNAVAILABLE_REASON = "Proposal has an active application lease"


def _as_utc(value: Any) -> Optional[datetime.datetime]:
    if not isinstance(value, datetime.datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _is_active(expiry: Optional[datetime.datetime], now: datetime.datetime) -> bool:
    return expiry is not None and now < expiry


def _expired_proposal_data(
    data: dict[str, Any],
    now: datetime.datetime,
) -> dict[str, Any]:
    failed = dict(data)
    failed.update(
        {
            "status": "failed",
            "leaseOwner": None,
            "leasedUntil": None,
            "updatedAt": now,
            "failureCode": _LEASE_EXPIRED_CODE,
            "failureReason": _LEASE_EXPIRED_REASON,
        }
    )
    return failed


class FirestoreProposalApplicationStore(RepositoryProposalApplicationStore):
    """Firestore-backed application store using one shared client instance."""

    def __init__(self, db: Optional[Any] = None) -> None:
        self.db = db if db is not None else get_firestore_client()
        super().__init__(
            proposal_repository=FirestoreAuditProposalRepository(self.db),
            title_repository=FirestoreTitleRepository(self.db),
            occurrence_repository=FirestoreOccurrenceRepository(self.db),
        )

    def acquire_lease(
        self,
        proposal_id: str,
        lease_duration: datetime.timedelta,
        now: datetime.datetime,
        lease_owner: Optional[str] = None,
    ) -> LeaseResult:
        del lease_owner
        owner = secrets.token_hex(32)
        normalized_now = _as_utc(now)
        if normalized_now is None:
            return LeaseResult(
                acquired=False,
                reason_code="invalid_lease_time",
                reason="Application lease time is invalid",
            )
        if not isinstance(lease_duration, datetime.timedelta) or lease_duration <= datetime.timedelta(0):
            return LeaseResult(
                acquired=False,
                reason_code="invalid_lease_duration",
                reason="Application lease duration must be positive",
            )

        leased_until = normalized_now + lease_duration
        proposal_ref = self.proposal_repository.collection_ref.document(proposal_id)

        @firestore.transactional
        def _acquire_tx(transaction):
            proposal_snapshot = proposal_ref.get(transaction=transaction)
            if not proposal_snapshot.exists:
                return LeaseResult(
                    acquired=False,
                    reason_code="proposal_not_found",
                    reason=f"Proposal {proposal_id} was not found",
                )

            proposal_data = proposal_snapshot.to_dict() or {}
            source_title_id = proposal_data.get("sourceTitleId")
            if not isinstance(source_title_id, str) or not source_title_id:
                return LeaseResult(
                    acquired=False,
                    reason_code="proposal_invalid",
                    reason="Proposal source title is invalid",
                )

            source_lease_ref = self.db.collection(_LEASE_COLLECTION).document(source_title_id)
            source_lease_snapshot = source_lease_ref.get(transaction=transaction)
            source_proposals = list(
                self.proposal_repository.collection_ref.where(
                    "sourceTitleId", "==", source_title_id
                ).stream(transaction=transaction)
            )
            source_proposals.sort(key=lambda snapshot: snapshot.id)

            status = proposal_data.get("status")
            current_expiry = _as_utc(proposal_data.get("leasedUntil"))
            if status == "applying":
                if _is_active(current_expiry, normalized_now):
                    return LeaseResult(
                        acquired=False,
                        reason_code="lease_unavailable",
                        reason=_LEASE_UNAVAILABLE_REASON,
                    )

                transaction.set(
                    proposal_ref,
                    _expired_proposal_data(proposal_data, normalized_now),
                )
                source_lease_data = source_lease_snapshot.to_dict() if source_lease_snapshot.exists else {}
                if source_lease_data.get("proposalId") == proposal_id:
                    transaction.delete(source_lease_ref)
                return LeaseResult(
                    acquired=False,
                    reason_code=_LEASE_EXPIRED_CODE,
                    reason=_LEASE_EXPIRED_REASON,
                )

            if status != "approved":
                return LeaseResult(
                    acquired=False,
                    reason_code="proposal_not_approved",
                    reason="Proposal is not approved for application",
                )

            active_other_leases = []
            expired_other_leases = []
            for source_proposal in source_proposals:
                if source_proposal.id == proposal_id:
                    continue
                source_proposal_data = source_proposal.to_dict() or {}
                if source_proposal_data.get("status") != "applying":
                    continue
                source_proposal_expiry = _as_utc(
                    source_proposal_data.get("leasedUntil")
                )
                if _is_active(source_proposal_expiry, normalized_now):
                    active_other_leases.append(source_proposal)
                else:
                    expired_other_leases.append((source_proposal, source_proposal_data))

            if active_other_leases:
                return LeaseResult(
                    acquired=False,
                    reason_code="lease_unavailable",
                    reason=_LEASE_UNAVAILABLE_REASON,
                )

            source_lease_data = source_lease_snapshot.to_dict() if source_lease_snapshot.exists else {}
            source_lease_expiry = _as_utc(source_lease_data.get("leasedUntil"))
            if _is_active(source_lease_expiry, normalized_now):
                return LeaseResult(
                    acquired=False,
                    reason_code="lease_unavailable",
                    reason=_LEASE_UNAVAILABLE_REASON,
                )

            for source_proposal, source_proposal_data in expired_other_leases:
                transaction.set(
                    self.proposal_repository.collection_ref.document(source_proposal.id),
                    _expired_proposal_data(source_proposal_data, normalized_now),
                )

            leased_proposal_data = dict(proposal_data)
            leased_proposal_data.update(
                {
                    "status": "applying",
                    "leaseOwner": owner,
                    "leasedUntil": leased_until,
                    "updatedAt": normalized_now,
                    "failureCode": None,
                    "failureReason": None,
                }
            )
            transaction.set(proposal_ref, leased_proposal_data)
            transaction.set(
                source_lease_ref,
                {
                    "proposalId": proposal_id,
                    "sourceTitleId": source_title_id,
                    "leaseOwner": owner,
                    "leasedUntil": leased_until,
                    "updatedAt": normalized_now,
                },
            )
            return LeaseResult(
                acquired=True,
                lease_owner=owner,
                leased_until=leased_until,
                reason_code="lease_acquired",
                reason="Application lease acquired",
            )

        transaction = self.db.transaction()
        return _acquire_tx(transaction)

    @staticmethod
    def _commit_result(
        outcome: str,
        reason_code: str,
        reason: str,
        plan: Any,
        *,
        occurrences_moved: int = 0,
        source_deleted: bool = False,
    ) -> ApplicationCommitResult:
        return ApplicationCommitResult(
            outcome=outcome,
            reason_code=reason_code,
            reason=reason,
            proposal_id=getattr(plan, "proposal_id", None),
            target_title_id=getattr(plan, "target_title_id", None),
            occurrences_moved=occurrences_moved,
            source_deleted=source_deleted,
        )

    def _mark_aborted_commit_failed(
        self,
        proposal_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> None:
        proposal_ref = self.proposal_repository.collection_ref.document(proposal_id)

        @firestore.transactional
        def _mark_failed_tx(transaction):
            snapshot = proposal_ref.get(transaction=transaction)
            if not snapshot.exists:
                return
            data = snapshot.to_dict() or {}
            if data.get("status") != "applying" or data.get("leaseOwner") != lease_owner:
                return
            source_title_id = data.get("sourceTitleId")
            failed_data = copy.deepcopy(data)
            failed_data.update(
                {
                    "status": "failed",
                    "leaseOwner": None,
                    "leasedUntil": None,
                    "updatedAt": now,
                    "failureCode": "commit_failed",
                    "failureReason": "Application transaction failed before commit",
                }
            )
            transaction.set(proposal_ref, failed_data)
            if isinstance(source_title_id, str) and source_title_id:
                transaction.delete(
                    self.db.collection(_LEASE_COLLECTION).document(source_title_id)
                )

        _mark_failed_tx(self.db.transaction())

    def commit_application(
        self,
        plan: Any,
        lease_owner: str,
        now: datetime.datetime,
    ) -> ApplicationCommitResult:
        from .proposal_application import (
            CURRENT_APPLICATION_POLICY_VERSION,
            MAX_APPLICATION_OCCURRENCES,
            _OCCURRENCE_FINGERPRINT_FIELDS,
            _SOURCE_TITLE_FINGERPRINT_FIELDS,
            _canonical_occurrence_fingerprint_from_occurrence,
            _canonical_source_fingerprint_from_title,
            _freeze_value,
            _validated_fingerprint,
        )

        proposal_id = getattr(plan, "proposal_id", None)
        if not isinstance(proposal_id, str) or not proposal_id:
            return self._commit_result(
                "failed", "proposal_not_found", "Application proposal was not found", plan
            )

        proposal_ref = self.proposal_repository.collection_ref.document(proposal_id)

        @firestore.transactional
        def _commit_tx(transaction):
            proposal_snapshot = proposal_ref.get(transaction=transaction)
            if not proposal_snapshot.exists:
                return self._commit_result(
                    "failed", "proposal_not_found", "Application proposal was not found", plan
                )

            proposal_data = proposal_snapshot.to_dict() or {}
            if proposal_data.get("status") == "applied":
                return self._commit_result(
                    "applied",
                    "already_applied",
                    "Proposal was already applied",
                    plan,
                    source_deleted=getattr(plan, "source_deleted", False),
                )
            if proposal_data.get("status") != "applying":
                return self._commit_result(
                    "failed",
                    "proposal_not_applying",
                    "Proposal does not have an active application lease",
                    plan,
                )
            if not lease_owner or proposal_data.get("leaseOwner") != lease_owner:
                return self._commit_result(
                    "failed",
                    "lease_owner_mismatch",
                    "Application lease owner does not match",
                    plan,
                )
            source_title_id = proposal_data.get("sourceTitleId")
            normalized_now = _as_utc(now)
            if not isinstance(source_title_id, str) or not source_title_id:
                return self._commit_result(
                    "failed",
                    "proposal_invalid",
                    "Proposal source title is invalid",
                    plan,
                )
            if normalized_now is None:
                return self._commit_result(
                    "failed",
                    "invalid_commit_time",
                    "Application commit time is invalid",
                    plan,
                )
            source_lease_ref = self.db.collection(_LEASE_COLLECTION).document(
                source_title_id
            )

            def _finish_failed_attempt(
                outcome: str,
                reason_code: str,
                reason: str,
            ) -> ApplicationCommitResult:
                failed_proposal_data = copy.deepcopy(proposal_data)
                failed_proposal_data.update(
                    {
                        "status": "failed",
                        "leaseOwner": None,
                        "leasedUntil": None,
                        "updatedAt": normalized_now,
                        "failureCode": "stale" if outcome == "stale" else reason_code,
                        "failureReason": reason[:500],
                    }
                )
                transaction.set(proposal_ref, failed_proposal_data)
                transaction.delete(source_lease_ref)
                return self._commit_result(
                    outcome,
                    reason_code,
                    reason,
                    plan,
                )

            lease_expiry = _as_utc(proposal_data.get("leasedUntil"))
            if lease_expiry is None or normalized_now >= lease_expiry:
                return _finish_failed_attempt(
                    "failed", "lease_expired", "Application lease has expired"
                )

            occurrence_ids = tuple(getattr(plan, "occurrence_ids", ()))
            if (
                not occurrence_ids
                or len(occurrence_ids) > MAX_APPLICATION_OCCURRENCES
                or len(set(occurrence_ids)) != len(occurrence_ids)
                or any(
                    not isinstance(occurrence_id, str) or not occurrence_id
                    for occurrence_id in occurrence_ids
                )
            ):
                return _finish_failed_attempt(
                    "ineligible",
                    "occurrence_ids",
                    "Application plan occurrence membership is invalid",
                )

            target = getattr(plan, "target", None)
            target_data = proposal_data.get("target")
            plan_source_title_id = getattr(plan, "source_title_id", None)
            if (
                proposal_data.get("schemaVersion") != 2
                or proposal_data.get("actionKind") != "repair"
                or proposal_data.get("policyVersion") != CURRENT_APPLICATION_POLICY_VERSION
                or not isinstance(target_data, Mapping)
                or target is None
                or target.to_dict() != dict(target_data)
                or source_title_id != plan_source_title_id
                or tuple(proposal_data.get("occurrenceIds") or ()) != occurrence_ids
            ):
                return _finish_failed_attempt(
                    "ineligible",
                    "plan_precondition",
                    "Application proposal no longer matches the application plan",
                )

            target_title_id = get_title_id_v2(
                target.imdb_id, target.title, target.year, target.media_type
            )
            if target_title_id != getattr(plan, "target_title_id", None):
                return _finish_failed_attempt(
                    "ineligible",
                    "target_changed",
                    "Application target no longer matches the application plan",
                )

            plan_source_fingerprint = dict(
                getattr(plan, "source_title_fingerprint", ())
            )
            proposal_source_fingerprint = proposal_data.get("sourceTitleFingerprint")
            if proposal_source_fingerprint is None:
                current_metadata = proposal_data.get("currentMetadata")
                if isinstance(current_metadata, Mapping):
                    proposal_source_fingerprint = current_metadata.get(
                        "sourceTitleFingerprint"
                    )
            validated_source_fingerprint = _validated_fingerprint(
                proposal_source_fingerprint,
                _SOURCE_TITLE_FINGERPRINT_FIELDS,
            )
            if (
                validated_source_fingerprint is None
                or _freeze_value(validated_source_fingerprint)
                != _freeze_value(plan_source_fingerprint)
            ):
                return _finish_failed_attempt(
                    "ineligible",
                    "source_fingerprint_changed",
                    "Proposal source fingerprint no longer matches the application plan",
                )

            plan_occurrence_fingerprints = dict(
                getattr(plan, "occurrence_fingerprints", ())
            )
            proposal_occurrence_fingerprints = proposal_data.get(
                "occurrenceFingerprints"
            )
            if (
                not isinstance(proposal_occurrence_fingerprints, Mapping)
                or set(plan_occurrence_fingerprints) != set(occurrence_ids)
                or set(proposal_occurrence_fingerprints) != set(occurrence_ids)
            ):
                return _finish_failed_attempt(
                    "ineligible",
                    "occurrence_fingerprint_membership",
                    "Proposal occurrence fingerprints no longer match the application plan",
                )
            for occurrence_id in occurrence_ids:
                proposal_fingerprint = _validated_fingerprint(
                    proposal_occurrence_fingerprints[occurrence_id],
                    _OCCURRENCE_FINGERPRINT_FIELDS,
                )
                if (
                    proposal_fingerprint is None
                    or _freeze_value(proposal_fingerprint)
                    != _freeze_value(plan_occurrence_fingerprints[occurrence_id])
                ):
                    return _finish_failed_attempt(
                        "ineligible",
                        "occurrence_fingerprint_changed",
                        f"Occurrence fingerprint for {occurrence_id} no longer matches the application plan",
                    )

            source_title_ref = self.title_repository.collection_ref.document(
                plan_source_title_id
            )
            target_title_ref = self.title_repository.collection_ref.document(target_title_id)
            source_occurrences_ref = source_title_ref.collection("occurrences")
            target_occurrences_ref = target_title_ref.collection("occurrences")

            source_title_snapshot = source_title_ref.get(transaction=transaction)
            target_title_snapshot = target_title_ref.get(transaction=transaction)
            source_occurrence_snapshots = list(
                source_occurrences_ref.stream(transaction=transaction)
            )
            source_occurrence_snapshots.sort(key=lambda snapshot: snapshot.id)
            source_occurrence_by_id = {
                snapshot.id: snapshot for snapshot in source_occurrence_snapshots
            }
            target_occurrence_snapshots = {
                occurrence_id: target_occurrences_ref.document(occurrence_id).get(
                    transaction=transaction
                )
                for occurrence_id in occurrence_ids
            }

            if not source_title_snapshot.exists:
                return _finish_failed_attempt(
                    "stale", "source_title_missing", "Source title no longer exists"
                )
            source_title = title_from_dict(source_title_snapshot.to_dict() or {})
            if _freeze_value(
                _canonical_source_fingerprint_from_title(source_title)
            ) != _freeze_value(plan_source_fingerprint):
                return _finish_failed_attempt(
                    "stale",
                    "source_title_changed",
                    "Source title fingerprint is stale",
                )

            source_occurrences: dict[str, Occurrence] = {}
            for occurrence_id in occurrence_ids:
                occurrence_snapshot = source_occurrence_by_id.get(occurrence_id)
                if occurrence_snapshot is None or not occurrence_snapshot.exists:
                    return _finish_failed_attempt(
                        "stale",
                        "occurrence_missing",
                        f"Occurrence {occurrence_id} is missing from the source title",
                    )
                occurrence = occurrence_from_dict(occurrence_snapshot.to_dict() or {})
                if _freeze_value(
                    _canonical_occurrence_fingerprint_from_occurrence(occurrence)
                ) != _freeze_value(plan_occurrence_fingerprints[occurrence_id]):
                    return _finish_failed_attempt(
                        "stale",
                        "occurrence_changed",
                        f"Occurrence {occurrence_id} fingerprint is stale",
                    )
                source_occurrences[occurrence_id] = occurrence

            source_occurrence_count = len(source_occurrence_snapshots)
            if source_occurrence_count != getattr(plan, "source_occurrence_count", None):
                return _finish_failed_attempt(
                    "stale",
                    "occurrence_membership_changed",
                    "Source occurrence membership is stale",
                )

            source_deleted = (
                plan_source_title_id != target_title_id
                and source_occurrence_count == len(occurrence_ids)
            )
            if source_deleted != getattr(plan, "source_deleted", None):
                return _finish_failed_attempt(
                    "stale",
                    "source_deletion_changed",
                    "Source deletion precondition is stale",
                )

            staged_target_title = None
            staged_target_occurrences: dict[str, Occurrence] = {}
            if plan_source_title_id != target_title_id:
                moved_first_seen = min(
                    occurrence.first_seen_at for occurrence in source_occurrences.values()
                )
                moved_last_seen = max(
                    occurrence.last_seen_at for occurrence in source_occurrences.values()
                )
                target_incoming = Title(
                    title=target.title,
                    normalized_title=normalize_title(target.title),
                    year=target.year,
                    media_type=target.media_type,
                    first_seen_at=moved_first_seen,
                    last_seen_at=moved_last_seen,
                    updated_at=normalized_now,
                    imdb_id=target.imdb_id,
                    source_type=target.media_type,
                    content_kind=target.content_kind,
                    broadcast_range=target.broadcast_range,
                )
                if target_title_snapshot.exists:
                    staged_target_title = merge_titles(
                        title_from_dict(target_title_snapshot.to_dict() or {}),
                        target_incoming,
                    )
                else:
                    staged_target_title = target_incoming
                staged_target_title.ai_validated = False
                staged_target_title.ai_checked_at = normalized_now

                for occurrence_id in occurrence_ids:
                    incoming_occurrence = source_occurrences[occurrence_id]
                    existing_snapshot = target_occurrence_snapshots[occurrence_id]
                    staged_target_occurrences[occurrence_id] = (
                        merge_occurrences(
                            occurrence_from_dict(existing_snapshot.to_dict() or {}),
                            incoming_occurrence,
                        )
                        if existing_snapshot.exists
                        else copy.deepcopy(incoming_occurrence)
                    )

            staged_source_title = copy.deepcopy(source_title)
            staged_source_title.ai_validated = False
            staged_source_title.ai_checked_at = normalized_now
            staged_source_title.updated_at = normalized_now
            staged_proposal_data = copy.deepcopy(proposal_data)
            staged_proposal_data.update(
                {
                    "status": "applied",
                    "leaseOwner": None,
                    "leasedUntil": None,
                    "updatedAt": normalized_now,
                    "failureCode": None,
                    "failureReason": None,
                }
            )

            if staged_target_title is not None:
                transaction.set(target_title_ref, staged_target_title.to_dict())
            for occurrence_id, occurrence in staged_target_occurrences.items():
                transaction.set(
                    target_occurrences_ref.document(occurrence_id), occurrence.to_dict()
                )
            for occurrence_id in occurrence_ids:
                transaction.delete(source_occurrences_ref.document(occurrence_id))
            if source_deleted:
                transaction.delete(source_title_ref)
            elif plan_source_title_id != target_title_id:
                transaction.set(source_title_ref, staged_source_title.to_dict())
            transaction.set(proposal_ref, staged_proposal_data)
            transaction.delete(source_lease_ref)

            return self._commit_result(
                "applied",
                "applied",
                "Application committed successfully",
                plan,
                occurrences_moved=len(occurrence_ids),
                source_deleted=source_deleted,
            )

        try:
            return _commit_tx(self.db.transaction())
        except Exception as error:
            try:
                self._mark_aborted_commit_failed(
                    proposal_id,
                    lease_owner,
                    _as_utc(now) or datetime.datetime.now(datetime.timezone.utc),
                )
            except Exception:
                pass
            return self._commit_result(
                "failed",
                "commit_failed",
                f"Application commit failed ({type(error).__name__})",
                plan,
            )