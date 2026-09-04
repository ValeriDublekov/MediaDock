import datetime
import unittest
from unittest.mock import ANY, MagicMock

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

from movies_feed.audit_proposal import AuditProposal, ProposalTarget
from movies_feed.firestore_proposal_application_store import FirestoreProposalApplicationStore
from movies_feed.firestore_repository import (
    FirestoreAuditProposalRepository,
    FirestoreOccurrenceRepository,
    FirestoreTitleRepository,
)
from movies_feed.ids import get_title_id_v2
from movies_feed.models import Occurrence, Title
from movies_feed.proposal_application import (
    ApplicationCurrentSnapshot,
    ApplicationOccurrenceFingerprint,
    ApplicationPlanner,
    ApplicationSourceTitleFingerprint,
    ProposalApplicationService,
)
from movies_feed.proposal_application_store import FakeProposalApplicationStore
from backend.tests.fakes import (
    FakeAuditProposalRepository,
    FakeOccurrenceRepository,
    FakeTitleRepository,
)


class ProposalApplicationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.datetime(2026, 8, 31, 12, 0, tzinfo=datetime.timezone.utc)
        self.store = FakeProposalApplicationStore(
            proposal_repository=FakeAuditProposalRepository(),
            title_repository=FakeTitleRepository(),
            occurrence_repository=FakeOccurrenceRepository(),
        )

    def make_proposal(
        self,
        proposal_id: str = "proposal-1",
        status: str = "approved",
        occurrence_ids: list[str] | None = None,
        policy_version: str = "v1",
    ) -> AuditProposal:
        target = ProposalTarget(
            title="Target Title",
            year=2021,
            media_type="movie",
            imdb_id="tt1234567",
        )
        return AuditProposal(
            id=proposal_id,
            source_title_id="source-title",
            occurrence_ids=occurrence_ids or ["occurrence-1"],
            raw_title_cluster=["Target Title 2021 1080p"],
            current_metadata={"title": "Source Title", "year": 2020, "mediaType": "movie"},
            proposed_metadata=target.to_dict(),
            evidence={"reason": "test"},
            confidence=0.9,
            policy_version=policy_version,
            created_at=self.now,
            updated_at=self.now,
            status=status,
            schema_version=2,
            action_kind="repair",
            target=target,
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

    def make_occurrence(self, occurrence_id: str = "occurrence-1") -> Occurrence:
        return Occurrence(
            source_feed_id="feed-1",
            source_feed_name="Feed 1",
            feed_entry_id=occurrence_id,
            torrent_url=f"https://example.test/{occurrence_id}",
            raw_title="Target Title 2021 1080p",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.now,
            last_seen_at=self.now,
        )

    def make_ready_plan(
        self,
        occurrence_ids: list[str] | None = None,
        *,
        proposal_id: str = "proposal-1",
        source_occurrence_ids: list[str] | None = None,
    ):
        occurrence_ids = occurrence_ids or ["occurrence-1"]
        source_occurrence_ids = source_occurrence_ids or occurrence_ids
        title = self.make_title()
        self.store.save_title("source-title", title)
        occurrences = {
            occurrence_id: self.make_occurrence(occurrence_id)
            for occurrence_id in source_occurrence_ids
        }
        for occurrence_id, occurrence in occurrences.items():
            self.store.save_occurrence("source-title", occurrence_id, occurrence)

        proposal = self.make_proposal(
            proposal_id=proposal_id,
            occurrence_ids=occurrence_ids,
        )
        proposal.source_title_fingerprint = ApplicationSourceTitleFingerprint.from_title(title)
        proposal.occurrence_fingerprints = {
            occurrence_id: ApplicationOccurrenceFingerprint.from_occurrence(occurrence)
            for occurrence_id, occurrence in occurrences.items()
            if occurrence_id in occurrence_ids
        }
        self.store.save_proposal(proposal)
        planning = ApplicationPlanner().plan(
            proposal,
            ApplicationCurrentSnapshot(
                source_title=title,
                source_occurrences=occurrences,
                source_occurrence_count=len(occurrences),
            ),
        )
        self.assertEqual(planning.outcome, "ready")
        self.assertIsNotNone(planning.plan)
        return proposal, planning.plan, occurrences

    def acquire(self, proposal_id: str = "proposal-1"):
        lease = self.store.acquire_lease(
            proposal_id,
            datetime.timedelta(minutes=5),
            self.now,
            lease_owner="owner-1",
        )
        self.assertTrue(lease)
        self.assertEqual(lease.lease_owner, "owner-1")
        return lease

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

        self.assertEqual(self.store.get_proposal(proposal.id).status, "approved")
        self.assertEqual(self.store.get_title("source-title").title, "Source Title")
        self.assertEqual(
            self.store.get_occurrence("source-title", "occurrence-1").raw_title,
            "Target Title 2021 1080p",
        )

    def test_fake_store_lists_approved_proposals_and_acquires_lease(self) -> None:
        self.store.save_proposal(self.make_proposal("pending-proposal", status="pending"))
        self.store.save_proposal(self.make_proposal("approved-proposal"))

        approved = self.store.list_approved_proposals()
        self.assertEqual([proposal.id for proposal in approved], ["approved-proposal"])

        acquired = self.store.acquire_lease("approved-proposal", datetime.timedelta(minutes=5), self.now)
        self.assertTrue(acquired)
        leased = self.store.get_proposal("approved-proposal")
        self.assertEqual(leased.status, "applying")
        self.assertEqual(leased.leased_until, self.now + datetime.timedelta(minutes=5))

    def test_target_absent_is_created_and_occurrence_is_moved(self) -> None:
        proposal, plan, _ = self.make_ready_plan()
        lease = self.acquire()

        result = self.store.commit_application(plan, lease.lease_owner, self.now)

        target_id = get_title_id_v2("tt1234567", "Target Title", 2021, "movie")
        self.assertEqual(result.outcome, "applied")
        self.assertEqual(result.occurrences_moved, 1)
        self.assertTrue(result.source_deleted)
        self.assertIsNotNone(self.store.get_title(target_id))
        self.assertIsNone(self.store.get_title("source-title"))
        self.assertIsNotNone(self.store.get_occurrence(target_id, "occurrence-1"))
        self.assertEqual(self.store.get_proposal(proposal.id).status, "applied")

    def test_existing_target_is_merged(self) -> None:
        proposal, plan, _ = self.make_ready_plan()
        target_id = get_title_id_v2("tt1234567", "Target Title", 2021, "movie")
        existing_target = self.make_title("Target Title", 2021)
        self.store.save_title(target_id, existing_target)
        lease = self.acquire()

        result = self.store.commit_application(plan, lease.lease_owner, self.now)

        self.assertEqual(result.outcome, "applied")
        self.assertIsNotNone(self.store.get_title(target_id))
        self.assertIsNotNone(self.store.get_occurrence(target_id, "occurrence-1"))
        self.assertIsNone(self.store.get_occurrence("source-title", "occurrence-1"))

    def test_partial_source_cluster_keeps_source_title_and_unnamed_occurrence(self) -> None:
        proposal, plan, _ = self.make_ready_plan(
            ["occurrence-1"],
            source_occurrence_ids=["occurrence-1", "occurrence-2"],
        )
        lease = self.acquire()

        result = self.store.commit_application(plan, lease.lease_owner, self.now)

        target_id = get_title_id_v2("tt1234567", "Target Title", 2021, "movie")
        self.assertEqual(result.outcome, "applied")
        self.assertFalse(result.source_deleted)
        self.assertIsNotNone(self.store.get_title("source-title"))
        self.assertIsNone(self.store.get_occurrence("source-title", "occurrence-1"))
        self.assertIsNotNone(self.store.get_occurrence("source-title", "occurrence-2"))
        self.assertIsNotNone(self.store.get_occurrence(target_id, "occurrence-1"))

    def test_last_occurrence_cleanup_deletes_source_title(self) -> None:
        _, plan, _ = self.make_ready_plan()
        lease = self.acquire()

        result = self.store.commit_application(plan, lease.lease_owner, self.now)

        self.assertTrue(result.source_deleted)
        self.assertIsNone(self.store.get_title("source-title"))

    def test_stale_source_title_does_not_mutate_catalog(self) -> None:
        _, plan, _ = self.make_ready_plan()
        lease = self.acquire()
        changed_title = self.make_title("Changed Source Title")
        self.store.save_title("source-title", changed_title)

        result = self.store.commit_application(plan, lease.lease_owner, self.now)

        self.assertEqual(result.outcome, "stale")
        self.assertEqual(result.reason_code, "source_title_changed")
        self.assertIsNone(self.store.get_title(plan.target_title_id))
        self.assertIsNotNone(self.store.get_occurrence("source-title", "occurrence-1"))

    def test_changed_or_missing_occurrence_does_not_mutate_catalog(self) -> None:
        _, changed_plan, _ = self.make_ready_plan(proposal_id="changed-proposal")
        changed_lease = self.acquire("changed-proposal")
        changed_occurrence = self.make_occurrence()
        changed_occurrence.raw_title = "Changed raw title"
        self.store.save_occurrence("source-title", "occurrence-1", changed_occurrence)

        changed_result = self.store.commit_application(
            changed_plan,
            changed_lease.lease_owner,
            self.now,
        )
        self.assertEqual(changed_result.outcome, "stale")
        self.assertIsNone(self.store.get_title(changed_plan.target_title_id))

        self.store = FakeProposalApplicationStore(
            proposal_repository=FakeAuditProposalRepository(),
            title_repository=FakeTitleRepository(),
            occurrence_repository=FakeOccurrenceRepository(),
        )
        _, missing_plan, _ = self.make_ready_plan(
            proposal_id="missing-proposal",
            source_occurrence_ids=["occurrence-1", "occurrence-2"],
        )
        missing_lease = self.acquire("missing-proposal")
        self.store.delete_occurrence("source-title", "occurrence-1")

        missing_result = self.store.commit_application(
            missing_plan,
            missing_lease.lease_owner,
            self.now,
        )
        self.assertEqual(missing_result.outcome, "stale")
        self.assertEqual(missing_result.reason_code, "occurrence_missing")
        self.assertIsNone(self.store.get_title(missing_plan.target_title_id))

    def test_policy_mismatch_is_rejected_without_mutation(self) -> None:
        proposal, plan, _ = self.make_ready_plan()
        proposal.policy_version = "v2"
        self.store.save_proposal(proposal)
        lease = self.acquire()

        result = self.store.commit_application(plan, lease.lease_owner, self.now)

        self.assertEqual(result.outcome, "ineligible")
        self.assertEqual(result.reason_code, "plan_precondition")
        self.assertIsNone(self.store.get_title(plan.target_title_id))
        self.assertIsNotNone(self.store.get_occurrence("source-title", "occurrence-1"))

    def test_wrong_lease_owner_is_rejected_without_mutation(self) -> None:
        _, plan, _ = self.make_ready_plan()
        self.acquire()

        result = self.store.commit_application(plan, "wrong-owner", self.now)

        self.assertEqual(result.outcome, "failed")
        self.assertEqual(result.reason_code, "lease_owner_mismatch")
        self.assertIsNone(self.store.get_title(plan.target_title_id))
        self.assertIsNotNone(self.store.get_occurrence("source-title", "occurrence-1"))

    def test_repeated_application_is_idempotent(self) -> None:
        _, plan, _ = self.make_ready_plan()
        lease = self.acquire()
        first = self.store.commit_application(plan, lease.lease_owner, self.now)
        target_snapshot = self.store.get_title(plan.target_title_id)
        occurrence_snapshot = self.store.get_occurrence(plan.target_title_id, "occurrence-1")

        second = self.store.commit_application(plan, lease.lease_owner, self.now)

        self.assertEqual(first.outcome, "applied")
        self.assertEqual(second.outcome, "applied")
        self.assertEqual(second.reason_code, "already_applied")
        self.assertEqual(self.store.get_title(plan.target_title_id), target_snapshot)
        self.assertEqual(
            self.store.get_occurrence(plan.target_title_id, "occurrence-1"),
            occurrence_snapshot,
        )

    def test_injected_failure_before_commit_leaves_zero_catalog_mutations(self) -> None:
        _, plan, _ = self.make_ready_plan()
        lease = self.acquire()
        self.store.fail_before_commit = True

        result = self.store.commit_application(plan, lease.lease_owner, self.now)

        self.assertEqual(result.outcome, "failed")
        self.assertEqual(result.reason_code, "injected_failure")
        self.assertEqual(self.store.get_proposal(plan.proposal_id).status, "applying")
        self.assertIsNone(self.store.get_title(plan.target_title_id))
        self.assertIsNotNone(self.store.get_occurrence("source-title", "occurrence-1"))

    def test_dry_run_leaves_store_unchanged(self) -> None:
        proposal, _, occurrences = self.make_ready_plan()
        service = ProposalApplicationService(store=self.store, clock=lambda: self.now)

        result = service.apply_proposal(proposal.id, dry_run=True)

        self.assertEqual(result.outcome, "planned")
        self.assertEqual(self.store.get_proposal(proposal.id).status, "approved")
        self.assertIsNone(self.store.get_title(result.target_title_id))
        self.assertIsNotNone(self.store.get_occurrence("source-title", next(iter(occurrences))))

    def test_application_service_accepts_store_boundary(self) -> None:
        self.store.save_title("source-title", self.make_title())
        occurrence = self.make_occurrence()
        self.store.save_occurrence("source-title", "occurrence-1", occurrence)
        proposal = self.make_proposal(status="approved")
        proposal.source_title_fingerprint = ApplicationSourceTitleFingerprint.from_title(
            self.make_title()
        )
        proposal.occurrence_fingerprints = {
            "occurrence-1": ApplicationOccurrenceFingerprint.from_occurrence(occurrence)
        }
        self.store.save_proposal(proposal)

        service = ProposalApplicationService(store=self.store, clock=lambda: self.now)
        result = service.apply_proposal("proposal-1")

        target_id = get_title_id_v2("tt1234567", "Target Title", 2021, "movie")
        self.assertEqual(result.outcome, "applied")
        self.assertEqual(result.target_title_id, target_id)
        self.assertIsNotNone(self.store.get_title(target_id))
        self.assertIsNone(self.store.get_occurrence("source-title", "occurrence-1"))
        self.assertIsNotNone(self.store.get_occurrence(target_id, "occurrence-1"))

    def test_application_service_delegates_live_mutation_to_atomic_commit(self) -> None:
        proposal, plan, _ = self.make_ready_plan()
        store = MagicMock(wraps=self.store)
        service = ProposalApplicationService(store=store, clock=lambda: self.now)

        result = service.apply_proposal(proposal.id)

        self.assertEqual(result.outcome, "applied")
        store.acquire_lease.assert_called_once()
        store.commit_application.assert_called_once_with(
            plan,
            ANY,
            self.now,
        )
        store.save_title.assert_not_called()
        store.save_occurrence.assert_not_called()
        store.delete_occurrence.assert_not_called()
        store.delete_title.assert_not_called()

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