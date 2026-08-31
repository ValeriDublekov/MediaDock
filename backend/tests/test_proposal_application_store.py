import datetime
import unittest
from unittest.mock import MagicMock

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

from movies_feed.audit_proposal import AuditProposal
from movies_feed.firestore_proposal_application_store import FirestoreProposalApplicationStore
from movies_feed.firestore_repository import (
    FirestoreAuditProposalRepository,
    FirestoreOccurrenceRepository,
    FirestoreTitleRepository,
)
from movies_feed.ids import get_title_id_v2
from movies_feed.models import Occurrence, Title
from movies_feed.proposal_application import ProposalApplicationService
from movies_feed.proposal_application_store import FakeProposalApplicationStore


class ProposalApplicationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.datetime(2026, 8, 31, 12, 0, tzinfo=datetime.timezone.utc)
        self.store = FakeProposalApplicationStore()

    def make_proposal(self, proposal_id: str = "proposal-1", status: str = "pending") -> AuditProposal:
        return AuditProposal(
            id=proposal_id,
            source_title_id="source-title",
            occurrence_ids=["occurrence-1"],
            raw_title_cluster=["Target Title 2021 1080p"],
            current_metadata={"title": "Source Title", "year": 2020, "mediaType": "movie"},
            proposed_metadata={
                "title": "Target Title",
                "year": 2021,
                "mediaType": "movie",
                "imdbId": "tt1234567",
            },
            evidence={"reason": "test"},
            confidence=0.9,
            policy_version="v1",
            created_at=self.now,
            updated_at=self.now,
            status=status,
        )

    def make_title(self, title: str = "Source Title", year: int = 2020) -> Title:
        return Title(
            title=title,
            normalized_title=title.lower(),
            year=year,
            media_type="movie",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
        )

    def make_occurrence(self) -> Occurrence:
        return Occurrence(
            source_feed_id="feed-1",
            source_feed_name="Feed 1",
            feed_entry_id="entry-1",
            torrent_url="https://example.test/entry-1",
            raw_title="Target Title 2021 1080p",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.now,
            last_seen_at=self.now,
        )

    def test_fake_store_round_trips_defensive_copies(self) -> None:
        proposal = self.make_proposal()
        title = self.make_title()
        occurrence = self.make_occurrence()

        self.store.save_proposal(proposal)
        self.store.save_title("source-title", title)
        self.store.save_occurrence("source-title", "occurrence-1", occurrence)

        fetched_proposal = self.store.get_proposal(proposal.id)
        fetched_title = self.store.get_title("source-title")
        fetched_occurrence = self.store.get_occurrence("source-title", "occurrence-1")
        fetched_proposal.status = "approved"
        fetched_title.title = "Changed"
        fetched_occurrence.raw_title = "Changed"

        self.assertEqual(self.store.get_proposal(proposal.id).status, "pending")
        self.assertEqual(self.store.get_title("source-title").title, "Source Title")
        self.assertEqual(
            self.store.get_occurrence("source-title", "occurrence-1").raw_title,
            "Target Title 2021 1080p",
        )

    def test_fake_store_lists_approved_proposals_and_acquires_lease(self) -> None:
        self.store.save_proposal(self.make_proposal("pending-proposal"))
        self.store.save_proposal(self.make_proposal("approved-proposal", status="approved"))

        approved = self.store.list_approved_proposals()
        self.assertEqual([proposal.id for proposal in approved], ["approved-proposal"])

        acquired = self.store.acquire_lease(
            "approved-proposal",
            datetime.timedelta(minutes=5),
            self.now,
        )
        self.assertTrue(acquired)
        leased = self.store.get_proposal("approved-proposal")
        self.assertEqual(leased.status, "applying")
        self.assertEqual(leased.leased_until, self.now + datetime.timedelta(minutes=5))

    def test_application_service_accepts_store_boundary(self) -> None:
        self.store.save_title("source-title", self.make_title())
        self.store.save_occurrence("source-title", "occurrence-1", self.make_occurrence())
        self.store.save_proposal(self.make_proposal(status="approved"))

        service = ProposalApplicationService(store=self.store, clock=lambda: self.now)
        result = service.apply_proposal("proposal-1")

        target_id = get_title_id_v2("tt1234567", "Target Title", 2021, "movie")
        self.assertEqual(result.outcome, "applied")
        self.assertEqual(result.target_title_id, target_id)
        self.assertIsNotNone(self.store.get_title(target_id))
        self.assertIsNone(self.store.get_occurrence("source-title", "occurrence-1"))
        self.assertIsNotNone(self.store.get_occurrence(target_id, "occurrence-1"))

    def test_firestore_store_composes_shared_client_repositories(self) -> None:
        db = MagicMock()

        store = FirestoreProposalApplicationStore(db)

        self.assertIs(store.db, db)
        self.assertIsInstance(store.proposal_repository, FirestoreAuditProposalRepository)
        self.assertIsInstance(store.title_repository, FirestoreTitleRepository)
        self.assertIsInstance(store.occurrence_repository, FirestoreOccurrenceRepository)
        self.assertIs(store.proposal_repository.db, db)
        self.assertIs(store.title_repository.db, db)
        self.assertIs(store.occurrence_repository.db, db)


if __name__ == "__main__":
    unittest.main()