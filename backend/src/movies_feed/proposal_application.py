import datetime
from typing import Callable, Optional, Literal, Tuple
from dataclasses import dataclass

from .audit_proposal import AuditProposal
from .models import Title, Occurrence
from .proposal_application_store import (
    ProposalApplicationStore,
    RepositoryProposalApplicationStore,
)
from .repository import AuditProposalRepository, TitleRepository, OccurrenceRepository
from .ids import get_title_id_v2, normalize_title

ApplicationOutcome = Literal["planned", "applied", "skipped", "failed"]

@dataclass
class ProposalApplicationResult:
    proposal_id: str
    outcome: ApplicationOutcome
    reason: str
    target_title_id: Optional[str] = None
    occurrences_moved: int = 0
    source_deleted: bool = False

class ProposalApplicationService:
    def __init__(
        self,
        proposal_repo: Optional[AuditProposalRepository] = None,
        title_repo: Optional[TitleRepository] = None,
        occurrence_repo: Optional[OccurrenceRepository] = None,
        clock: Optional[Callable[[], datetime.datetime]] = None,
        now: Optional[datetime.datetime] = None,
        store: Optional[ProposalApplicationStore] = None,
    ) -> None:
        if store is not None:
            if proposal_repo is not None or title_repo is not None or occurrence_repo is not None:
                raise ValueError("Provide either store or the legacy repository arguments, not both")
            self.store = store
        else:
            if proposal_repo is None or title_repo is None or occurrence_repo is None:
                raise ValueError("Proposal application requires a store or all legacy repositories")
            self.store = RepositoryProposalApplicationStore(
                proposal_repo,
                title_repo,
                occurrence_repo,
            )
        if clock is not None:
            self.clock = clock
        elif now is not None:
            self.clock = lambda: now
        else:
            self.clock = lambda: datetime.datetime.now(datetime.timezone.utc)

    def _mark_state(self, proposal: AuditProposal, status: str) -> None:
        proposal.status = status # type: ignore
        if status in ("applied", "failed", "rejected", "pending"):
            proposal.leased_until = None
        proposal.updated_at = self.clock()
        self.store.save_proposal(proposal)

    def apply_proposal(self, proposal_id: str, dry_run: bool = False, reject: bool = False) -> ProposalApplicationResult:
        proposal = self.store.get_proposal(proposal_id)
        if not proposal:
            return ProposalApplicationResult(proposal_id, "failed", f"Proposal {proposal_id} not found")

        if reject:
            if proposal.status in ("applied", "failed", "rejected"):
                return ProposalApplicationResult(proposal_id, "skipped", f"Cannot reject proposal in terminal state '{proposal.status}'")
            if not dry_run:
                self._mark_state(proposal, "rejected")
            outcome: ApplicationOutcome = "planned" if dry_run else "applied"
            return ProposalApplicationResult(proposal_id, outcome, "Confirmed rejection")

        if proposal.status == "applied":
            return ProposalApplicationResult(proposal_id, "skipped", "Proposal already applied")
        if proposal.status == "failed":
            return ProposalApplicationResult(proposal_id, "failed", "Proposal is in failed state")
        if proposal.status == "rejected":
            return ProposalApplicationResult(proposal_id, "skipped", "Proposal was rejected")
        if proposal.status == "pending":
            return ProposalApplicationResult(proposal_id, "failed", "Proposal must be approved before application")

        if not dry_run and proposal.status in ("approved", "applying"):
            lease_duration = datetime.timedelta(minutes=5)
            acquired = self.store.acquire_lease(proposal_id, lease_duration, self.clock())
            if not acquired:
                proposal = self.store.get_proposal(proposal_id)
                if not proposal:
                    return ProposalApplicationResult(proposal_id, "failed", f"Proposal {proposal_id} not found")
                
                # Check if acquire_lease recovered a stale lease to failed
                if proposal.status == "failed":
                    return ProposalApplicationResult(proposal_id, "failed", "Proposal lease was stale and recovered to failed")
                return ProposalApplicationResult(proposal_id, "skipped", "Could not acquire lease (concurrent application or unrecovered stale state)")
            # Re-fetch proposal after acquiring lease to have correct status and leased_until
            proposal = self.store.get_proposal(proposal_id)
            if not proposal:
                return ProposalApplicationResult(proposal_id, "failed", f"Proposal {proposal_id} not found")

        source_title = self.store.get_title(proposal.source_title_id)
        if not source_title:
            if not dry_run:
                self._mark_state(proposal, "failed")
            return ProposalApplicationResult(proposal_id, "failed", "Source title not found")

        proposed = proposal.proposed_metadata
        imdb_id = proposed.get("imdbId")
        title_str = proposed.get("title", "")
        year = proposed.get("year")
        media_type = proposed.get("mediaType", "")

        target_title_id = get_title_id_v2(imdb_id, title_str, year, media_type)

        if target_title_id == proposal.source_title_id:
            if not dry_run:
                self._mark_state(proposal, "applied")
            outcome: ApplicationOutcome = "planned" if dry_run else "skipped"
            return ProposalApplicationResult(
                proposal_id, 
                outcome, 
                "Same source and target", 
                target_title_id=target_title_id
            )

        occurrences_to_move: list[Tuple[str, Occurrence]] = []
        for occ_id in proposal.occurrence_ids:
            occ = self.store.get_occurrence(proposal.source_title_id, occ_id)
            if occ:
                occurrences_to_move.append((occ_id, occ))
            else:
                # Recoverability check
                target_occ = self.store.get_occurrence(target_title_id, occ_id)
                if target_occ:
                    pass # already moved
                else:
                    if not dry_run:
                        self._mark_state(proposal, "failed")
                    return ProposalApplicationResult(
                        proposal_id, "failed", f"Occurrence {occ_id} missing", target_title_id=target_title_id
                    )

        source_occ_count = len(self.store.list_occurrences(proposal.source_title_id))
        will_delete_source = source_occ_count == len(occurrences_to_move)

        if dry_run:
            return ProposalApplicationResult(
                proposal_id, 
                "planned", 
                "Planned application", 
                target_title_id=target_title_id, 
                occurrences_moved=len(occurrences_to_move),
                source_deleted=will_delete_source
            )

        # Execute
        target_title = self.store.get_title(target_title_id)
        if not target_title:
            now = self.clock()
            first_seen = source_title.first_seen_at
            last_seen = source_title.last_seen_at
            if occurrences_to_move:
                first_seen = min(occ.first_seen_at for _, occ in occurrences_to_move)
                last_seen = max(occ.last_seen_at for _, occ in occurrences_to_move)

            target_title = Title(
                title=title_str,
                normalized_title=normalize_title(title_str),
                year=year,
                media_type=media_type,
                first_seen_at=first_seen,
                last_seen_at=last_seen,
                updated_at=now,
                imdb_id=imdb_id,
            )
            self.store.save_title(target_title_id, target_title)
        else:
            # Merge logic for existing target
            target_title.updated_at = self.clock()
            if occurrences_to_move:
                target_title.first_seen_at = min(target_title.first_seen_at, min(occ.first_seen_at for _, occ in occurrences_to_move))
                target_title.last_seen_at = max(target_title.last_seen_at, max(occ.last_seen_at for _, occ in occurrences_to_move))
            self.store.save_title(target_title_id, target_title)

        for occ_id, occ in occurrences_to_move:
            self.store.save_occurrence(target_title_id, occ_id, occ)
            self.store.delete_occurrence(proposal.source_title_id, occ_id)

        if will_delete_source:
            self.store.delete_title(proposal.source_title_id)

        self._mark_state(proposal, "applied")
        return ProposalApplicationResult(
            proposal_id, 
            "applied", 
            "Applied successfully", 
            target_title_id=target_title_id, 
            occurrences_moved=len(occurrences_to_move),
            source_deleted=will_delete_source
        )
