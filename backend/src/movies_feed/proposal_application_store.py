import datetime
from abc import ABC, abstractmethod
from typing import List, Optional

from .audit_proposal import AuditProposal
from .models import Occurrence, Title
from .repository import (
    AuditProposalRepository,
    FakeAuditProposalRepository,
    FakeOccurrenceRepository,
    FakeTitleRepository,
    OccurrenceRepository,
    TitleRepository,
)


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
    ) -> bool:
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
    ) -> bool:
        return self.proposal_repository.acquire_lease(proposal_id, lease_duration, now)

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
        proposal_repository: Optional[AuditProposalRepository] = None,
        title_repository: Optional[TitleRepository] = None,
        occurrence_repository: Optional[OccurrenceRepository] = None,
    ) -> None:
        super().__init__(
            proposal_repository or FakeAuditProposalRepository(),
            title_repository or FakeTitleRepository(),
            occurrence_repository or FakeOccurrenceRepository(),
        )