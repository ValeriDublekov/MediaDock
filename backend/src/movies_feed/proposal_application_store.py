from __future__ import annotations

import copy
import datetime
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Mapping, Optional

from .audit_proposal import AuditProposal
from .ids import get_title_id_v2, normalize_title
from .models import Occurrence, Title
from .repository import (
    AuditProposalRepository,
    OccurrenceRepository,
    TitleRepository,
    merge_occurrences,
    merge_titles,
)

if TYPE_CHECKING:
    from .proposal_application import ApplicationPlan


@dataclass(frozen=True)
class LeaseResult:
    acquired: bool
    lease_owner: Optional[str] = None
    leased_until: Optional[datetime.datetime] = None
    reason_code: str = ""
    reason: str = ""

    @property
    def owner(self) -> Optional[str]:
        return self.lease_owner

    @property
    def lease_until(self) -> Optional[datetime.datetime]:
        return self.leased_until

    def __bool__(self) -> bool:
        return self.acquired


LeaseAcquisitionResult = LeaseResult
ApplicationLeaseResult = LeaseResult


@dataclass(frozen=True)
class ApplicationCommitResult:
    outcome: str
    reason_code: str
    reason: str
    proposal_id: Optional[str] = None
    target_title_id: Optional[str] = None
    occurrences_moved: int = 0
    source_deleted: bool = False

    @property
    def applied(self) -> bool:
        return self.outcome == "applied"

    @property
    def success(self) -> bool:
        return self.applied


CommitResult = ApplicationCommitResult


class ProposalApplicationStore(ABC):
    """Persistence boundary used by proposal application orchestration."""

    @abstractmethod
    def get_proposal(self, proposal_id: str) -> Optional[AuditProposal]:
        pass

    @abstractmethod
    def save_proposal(self, proposal: AuditProposal) -> None:
        pass

    @abstractmethod
    def list_approved_proposals(self, limit: int = 1000) -> List[AuditProposal]:
        pass

    @abstractmethod
    def acquire_lease(
        self,
        proposal_id: str,
        lease_duration: datetime.timedelta,
        now: datetime.datetime,
        lease_owner: Optional[str] = None,
    ) -> LeaseResult:
        pass

    @abstractmethod
    def commit_application(
        self,
        plan: "ApplicationPlan",
        lease_owner: str,
        now: datetime.datetime,
    ) -> ApplicationCommitResult:
        pass

    @abstractmethod
    def get_title(self, title_id: str) -> Optional[Title]:
        pass

    @abstractmethod
    def save_title(self, title_id: str, title: Title) -> None:
        pass

    @abstractmethod
    def delete_title(self, title_id: str) -> None:
        pass

    @abstractmethod
    def get_occurrence(self, title_id: str, occurrence_id: str) -> Optional[Occurrence]:
        pass

    @abstractmethod
    def list_occurrences(self, title_id: str) -> List[Occurrence]:
        pass

    @abstractmethod
    def save_occurrence(
        self,
        title_id: str,
        occurrence_id: str,
        occurrence: Occurrence,
    ) -> None:
        pass

    @abstractmethod
    def delete_occurrence(self, title_id: str, occurrence_id: str) -> None:
        pass


class RepositoryProposalApplicationStore(ProposalApplicationStore):
    """Adapts the existing repositories to the application-specific port."""

    def __init__(
        self,
        proposal_repository: AuditProposalRepository,
        title_repository: TitleRepository,
        occurrence_repository: OccurrenceRepository,
    ) -> None:
        self.proposal_repository = proposal_repository
        self.title_repository = title_repository
        self.occurrence_repository = occurrence_repository
        self._lease_owners: dict[str, str] = {}

    def get_proposal(self, proposal_id: str) -> Optional[AuditProposal]:
        return self.proposal_repository.get(proposal_id)

    def save_proposal(self, proposal: AuditProposal) -> None:
        self.proposal_repository.upsert(proposal)

    def list_approved_proposals(self, limit: int = 1000) -> List[AuditProposal]:
        return self.proposal_repository.list_by_status("approved", limit=limit)

    def acquire_lease(
        self,
        proposal_id: str,
        lease_duration: datetime.timedelta,
        now: datetime.datetime,
        lease_owner: Optional[str] = None,
    ) -> LeaseResult:
        owner = lease_owner or uuid.uuid4().hex
        acquired = self.proposal_repository.acquire_lease(
            proposal_id,
            lease_duration,
            now,
        )
        proposal = self.get_proposal(proposal_id)
        if not acquired:
            if proposal is None:
                return LeaseResult(
                    acquired=False,
                    reason_code="proposal_not_found",
                    reason=f"Proposal {proposal_id} was not found",
                )
            if proposal.status == "failed":
                return LeaseResult(
                    acquired=False,
                    reason_code="lease_expired",
                    reason="Proposal lease was expired or unrecoverable",
                )
            if proposal.status == "applying":
                return LeaseResult(
                    acquired=False,
                    reason_code="lease_unavailable",
                    reason="Proposal has an active application lease",
                )
            return LeaseResult(
                acquired=False,
                reason_code="proposal_not_approved",
                reason="Proposal is not approved for application",
            )

        if proposal is None:
            return LeaseResult(
                acquired=False,
                reason_code="proposal_not_found",
                reason=f"Proposal {proposal_id} was not found",
            )
        setattr(proposal, "lease_owner", owner)
        self.save_proposal(proposal)
        self._lease_owners[proposal_id] = owner
        return LeaseResult(
            acquired=True,
            lease_owner=owner,
            leased_until=proposal.leased_until,
            reason_code="lease_acquired",
            reason="Application lease acquired",
        )

    def commit_application(
        self,
        plan: "ApplicationPlan",
        lease_owner: str,
        now: datetime.datetime,
    ) -> ApplicationCommitResult:
        return ApplicationCommitResult(
            outcome="failed",
            reason_code="atomic_commit_unavailable",
            reason="This repository adapter does not provide an atomic application commit",
            proposal_id=getattr(plan, "proposal_id", None),
            target_title_id=getattr(plan, "target_title_id", None),
        )

    def get_title(self, title_id: str) -> Optional[Title]:
        return self.title_repository.get(title_id)

    def save_title(self, title_id: str, title: Title) -> None:
        self.title_repository.upsert(title_id, title)

    def delete_title(self, title_id: str) -> None:
        self.title_repository.delete(title_id)

    def get_occurrence(self, title_id: str, occurrence_id: str) -> Optional[Occurrence]:
        return self.occurrence_repository.get(title_id, occurrence_id)

    def list_occurrences(self, title_id: str) -> List[Occurrence]:
        return self.occurrence_repository.list_by_title(title_id)

    def save_occurrence(
        self,
        title_id: str,
        occurrence_id: str,
        occurrence: Occurrence,
    ) -> None:
        self.occurrence_repository.upsert(title_id, occurrence_id, occurrence)

    def delete_occurrence(self, title_id: str, occurrence_id: str) -> None:
        self.occurrence_repository.delete(title_id, occurrence_id)


class FakeProposalApplicationStore(RepositoryProposalApplicationStore):
    """In-memory application store backed by the defensive fake repositories."""

    def __init__(
        self,
        proposal_repository: AuditProposalRepository,
        title_repository: TitleRepository,
        occurrence_repository: OccurrenceRepository,
        fail_before_commit: bool = False,
    ) -> None:
        super().__init__(
            proposal_repository,
            title_repository,
            occurrence_repository,
        )
        self.fail_before_commit = fail_before_commit
        self.fail_next_commit = False
        self.injected_failure: Optional[BaseException] = None

    def inject_failure_before_commit(
        self,
        failure: Optional[BaseException] = None,
    ) -> None:
        self.fail_next_commit = True
        self.injected_failure = failure

    def clear_injected_failure(self) -> None:
        self.fail_before_commit = False
        self.fail_next_commit = False
        self.injected_failure = None

    @staticmethod
    def _commit_result(
        outcome: str,
        reason_code: str,
        reason: str,
        plan: "ApplicationPlan",
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

    def _failure_before_commit(self, plan: "ApplicationPlan") -> Optional[ApplicationCommitResult]:
        if self.injected_failure is not None:
            failure = self.injected_failure
            self.injected_failure = None
            raise failure
        if self.fail_next_commit:
            self.fail_next_commit = False
            return self._commit_result(
                "failed",
                "injected_failure",
                "Injected failure before application commit",
                plan,
            )
        if self.fail_before_commit:
            return self._commit_result(
                "failed",
                "injected_failure",
                "Injected failure before application commit",
                plan,
            )
        return None

    def commit_application(
        self,
        plan: "ApplicationPlan",
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
            _proposal_occurrence_fingerprints,
            _proposal_source_fingerprint,
            _validated_fingerprint,
        )

        proposal_id = getattr(plan, "proposal_id", None)
        proposal = self.get_proposal(proposal_id) if isinstance(proposal_id, str) else None
        if proposal is None:
            return self._commit_result(
                "failed",
                "proposal_not_found",
                "Application proposal was not found",
                plan,
            )
        if proposal.status == "applied":
            return self._commit_result(
                "applied",
                "already_applied",
                "Proposal was already applied",
                plan,
                occurrences_moved=0,
                source_deleted=getattr(plan, "source_deleted", False),
            )
        if proposal.status != "applying":
            return self._commit_result(
                "failed",
                "proposal_not_applying",
                "Proposal does not have an active application lease",
                plan,
            )

        stored_owner = self._lease_owners.get(proposal.id)
        if stored_owner is None:
            stored_owner = getattr(proposal, "lease_owner", None)
        if not lease_owner or stored_owner != lease_owner:
            return self._commit_result(
                "failed",
                "lease_owner_mismatch",
                "Application lease owner does not match",
                plan,
            )
        if proposal.leased_until is None or now >= proposal.leased_until:
            return self._commit_result(
                "failed",
                "lease_expired",
                "Application lease has expired",
                plan,
            )

        occurrence_ids = tuple(getattr(plan, "occurrence_ids", ()))
        if (
            not occurrence_ids
            or len(occurrence_ids) > MAX_APPLICATION_OCCURRENCES
            or len(set(occurrence_ids)) != len(occurrence_ids)
            or any(not isinstance(occurrence_id, str) or not occurrence_id for occurrence_id in occurrence_ids)
        ):
            return self._commit_result(
                "ineligible",
                "occurrence_ids",
                "Application plan occurrence membership is invalid",
                plan,
            )

        target = getattr(plan, "target", None)
        if (
            proposal.schema_version != 2
            or proposal.action_kind != "repair"
            or proposal.policy_version != CURRENT_APPLICATION_POLICY_VERSION
            or proposal.target is None
            or target != proposal.target
            or proposal.source_title_id != getattr(plan, "source_title_id", None)
            or tuple(proposal.occurrence_ids) != occurrence_ids
        ):
            return self._commit_result(
                "ineligible",
                "plan_precondition",
                "Application proposal no longer matches the application plan",
                plan,
            )

        target_title_id = get_title_id_v2(
            target.imdb_id,
            target.title,
            target.year,
            target.media_type,
        )
        if target_title_id != getattr(plan, "target_title_id", None):
            return self._commit_result(
                "ineligible",
                "target_changed",
                "Application target no longer matches the application plan",
                plan,
            )

        plan_source_fingerprint = dict(getattr(plan, "source_title_fingerprint", ()))
        proposal_source_fingerprint = _validated_fingerprint(
            _proposal_source_fingerprint(proposal),
            _SOURCE_TITLE_FINGERPRINT_FIELDS,
        )
        if (
            proposal_source_fingerprint is None
            or _freeze_value(proposal_source_fingerprint) != _freeze_value(plan_source_fingerprint)
        ):
            return self._commit_result(
                "ineligible",
                "source_fingerprint_changed",
                "Proposal source fingerprint no longer matches the application plan",
                plan,
            )

        plan_occurrence_fingerprints = dict(getattr(plan, "occurrence_fingerprints", ()))
        proposal_occurrence_fingerprints = _proposal_occurrence_fingerprints(proposal)
        if (
            not isinstance(proposal_occurrence_fingerprints, Mapping)
            or set(plan_occurrence_fingerprints) != set(occurrence_ids)
            or set(proposal_occurrence_fingerprints) != set(occurrence_ids)
        ):
            return self._commit_result(
                "ineligible",
                "occurrence_fingerprint_membership",
                "Proposal occurrence fingerprints no longer match the application plan",
                plan,
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
                return self._commit_result(
                    "ineligible",
                    "occurrence_fingerprint_changed",
                    f"Occurrence fingerprint for {occurrence_id} no longer matches the application plan",
                    plan,
                )

        source_title_id = plan.source_title_id
        source_title = self.get_title(source_title_id)
        if source_title is None:
            return self._commit_result(
                "stale",
                "source_title_missing",
                "Source title no longer exists",
                plan,
            )
        if _freeze_value(_canonical_source_fingerprint_from_title(source_title)) != _freeze_value(
            plan_source_fingerprint
        ):
            return self._commit_result(
                "stale",
                "source_title_changed",
                "Source title fingerprint is stale",
                plan,
            )

        source_occurrences: dict[str, Occurrence] = {}
        for occurrence_id in occurrence_ids:
            occurrence = self.get_occurrence(source_title_id, occurrence_id)
            if occurrence is None:
                return self._commit_result(
                    "stale",
                    "occurrence_missing",
                    f"Occurrence {occurrence_id} is missing from the source title",
                    plan,
                )
            if _freeze_value(_canonical_occurrence_fingerprint_from_occurrence(occurrence)) != _freeze_value(
                plan_occurrence_fingerprints[occurrence_id]
            ):
                return self._commit_result(
                    "stale",
                    "occurrence_changed",
                    f"Occurrence {occurrence_id} fingerprint is stale",
                    plan,
                )
            source_occurrences[occurrence_id] = occurrence

        source_occurrence_count = len(self.list_occurrences(source_title_id))
        if source_occurrence_count != plan.source_occurrence_count:
            return self._commit_result(
                "stale",
                "occurrence_membership_changed",
                "Source occurrence membership is stale",
                plan,
            )

        source_deleted = (
            source_title_id != plan.target_title_id
            and source_occurrence_count == len(occurrence_ids)
        )
        if source_deleted != plan.source_deleted:
            return self._commit_result(
                "stale",
                "source_deletion_changed",
                "Source deletion precondition is stale",
                plan,
            )

        target_title = None
        staged_target_title = None
        staged_target_occurrences: list[tuple[str, Occurrence]] = []
        if source_title_id != plan.target_title_id:
            target_title = self.get_title(plan.target_title_id)
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
                updated_at=now,
                imdb_id=target.imdb_id,
                source_type=target.media_type,
                content_kind=target.content_kind,
                broadcast_range=target.broadcast_range,
            )
            staged_target_title = (
                merge_titles(target_title, target_incoming)
                if target_title is not None
                else target_incoming
            )
            for occurrence_id in occurrence_ids:
                existing_target_occurrence = self.get_occurrence(
                    plan.target_title_id,
                    occurrence_id,
                )
                incoming_occurrence = source_occurrences[occurrence_id]
                staged_target_occurrences.append(
                    (
                        occurrence_id,
                        merge_occurrences(existing_target_occurrence, incoming_occurrence)
                        if existing_target_occurrence is not None
                        else copy.deepcopy(incoming_occurrence),
                    )
                )

        staged_proposal = copy.deepcopy(proposal)
        staged_proposal.status = "applied"
        staged_proposal.leased_until = None
        setattr(staged_proposal, "lease_owner", None)

        injected_result = self._failure_before_commit(plan)
        if injected_result is not None:
            return injected_result

        repository_snapshots = []
        for repository in (
            self.proposal_repository,
            self.title_repository,
            self.occurrence_repository,
        ):
            repository_store = getattr(repository, "_store", None)
            if isinstance(repository_store, dict):
                repository_snapshots.append((repository, copy.deepcopy(repository_store)))
        lease_owners_snapshot = copy.deepcopy(self._lease_owners)
        try:
            if staged_target_title is not None:
                self.save_title(plan.target_title_id, staged_target_title)
            for occurrence_id, occurrence in staged_target_occurrences:
                self.save_occurrence(plan.target_title_id, occurrence_id, occurrence)
            for occurrence_id in occurrence_ids:
                self.delete_occurrence(source_title_id, occurrence_id)
            if source_deleted:
                self.delete_title(source_title_id)
            self.save_proposal(staged_proposal)
            self._lease_owners.pop(proposal.id, None)
        except Exception as error:
            for repository, repository_store in repository_snapshots:
                repository._store = repository_store
            self._lease_owners = lease_owners_snapshot
            return self._commit_result(
                "failed",
                "commit_failed",
                f"Application commit failed ({type(error).__name__})",
                plan,
            )

        return self._commit_result(
            "applied",
            "applied",
            "Application committed successfully",
            plan,
            occurrences_moved=len(occurrence_ids),
            source_deleted=source_deleted,
        )