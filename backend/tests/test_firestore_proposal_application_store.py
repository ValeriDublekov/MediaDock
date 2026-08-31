import datetime
import os
import unittest
from concurrent.futures import ThreadPoolExecutor

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

from movies_feed.audit_proposal import AuditProposal, ProposalTarget
from movies_feed.firestore_proposal_application_store import (
    FirestoreProposalApplicationStore,
)
from movies_feed.firestore_repository import get_firestore_client
from movies_feed.ids import get_title_id_v2, normalize_title
from movies_feed.models import Occurrence, Title
from movies_feed.proposal_application import (
    ApplicationCurrentSnapshot,
    ApplicationOccurrenceFingerprint,
    ApplicationPlanner,
    ApplicationSourceTitleFingerprint,
)


@unittest.skipUnless(
    os.environ.get("FIRESTORE_EMULATOR_HOST"),
    "Firestore emulator is not running/configured in environment",
)
class FirestoreProposalApplicationStoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = get_firestore_client(project_id="demo-mediadock")
        cls.utc = datetime.timezone.utc

    def setUp(self) -> None:
        self.now = datetime.datetime(2026, 8, 31, 12, 0, tzinfo=self.utc)
        self._clear_collection("auditProposals")
        self._clear_collection("proposalApplicationLeases")
        self._clear_titles()

    def _clear_collection(self, collection_name: str) -> None:
        for document in self.db.collection(collection_name).stream():
            document.reference.delete()

    def _clear_titles(self) -> None:
        for title in self.db.collection("titles").stream():
            for occurrence in title.reference.collection("occurrences").stream():
                occurrence.reference.delete()
            title.reference.delete()

    def _make_proposal(
        self,
        proposal_id: str,
        *,
        source_title_id: str = "source-title",
        status: str = "approved",
        leased_until: datetime.datetime | None = None,
    ) -> dict:
        proposal = AuditProposal(
            id=proposal_id,
            source_title_id=source_title_id,
            occurrence_ids=["occurrence-1"],
            raw_title_cluster=["Source Title 2020 1080p"],
            current_metadata={"title": "Source Title", "year": 2020, "mediaType": "movie"},
            proposed_metadata={"title": "Target Title", "year": 2021, "mediaType": "movie"},
            evidence={"reason": "synthetic test evidence"},
            confidence=0.9,
            policy_version="v1",
            created_at=self.now,
            updated_at=self.now,
            status=status,
            leased_until=leased_until,
            schema_version=2,
            action_kind="repair",
            target=ProposalTarget(
                title="Target Title",
                year=2021,
                media_type="movie",
                imdb_id="tt1234567",
            ),
        )
        data = proposal.to_dict()
        if status == "applying":
            data["leaseOwner"] = "old-owner"
        return data

    def _seed_proposal(self, proposal_id: str, **kwargs) -> None:
        self.db.collection("auditProposals").document(proposal_id).set(
            self._make_proposal(proposal_id, **kwargs)
        )

    def _seed_ready_application(
        self,
        *,
        source_occurrence_ids: tuple[str, ...] = ("occurrence-1",),
    ):
        source_title = Title(
            title="Source Title",
            normalized_title=normalize_title("Source Title"),
            year=2020,
            media_type="movie",
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
            source_type="movie",
            content_kind="standard",
        )
        occurrences = {
            occurrence_id: Occurrence(
                source_feed_id="feed-1",
                source_feed_name="Feed 1",
                feed_entry_id=occurrence_id,
                torrent_url=f"https://example.test/{occurrence_id}",
                raw_title="Source Title 2020 1080p",
                quality="1080p",
                rip_type="WEB-DL",
                first_seen_at=self.now,
                last_seen_at=self.now,
            )
            for occurrence_id in source_occurrence_ids
        }
        proposal_data = self._make_proposal("proposal-1")
        source_fingerprint = ApplicationSourceTitleFingerprint.from_title(
            source_title
        )
        occurrence_fingerprint = ApplicationOccurrenceFingerprint.from_occurrence(
            occurrences["occurrence-1"]
        )
        proposal_data["sourceTitleFingerprint"] = source_fingerprint.to_dict()
        proposal_data["occurrenceFingerprints"] = {
            "occurrence-1": occurrence_fingerprint.to_dict()
        }

        source_ref = self.db.collection("titles").document("source-title")
        source_ref.set(source_title.to_dict())
        for occurrence_id, occurrence in occurrences.items():
            source_ref.collection("occurrences").document(occurrence_id).set(
                occurrence.to_dict()
            )
        self.db.collection("auditProposals").document("proposal-1").set(
            proposal_data
        )

        proposal = AuditProposal(
            id="proposal-1",
            source_title_id="source-title",
            occurrence_ids=["occurrence-1"],
            raw_title_cluster=["Source Title 2020 1080p"],
            current_metadata={"title": "Source Title", "year": 2020, "mediaType": "movie"},
            proposed_metadata={"title": "Target Title", "year": 2021, "mediaType": "movie"},
            evidence={"reason": "synthetic test evidence"},
            confidence=0.9,
            policy_version="v1",
            created_at=self.now,
            updated_at=self.now,
            status="approved",
            schema_version=2,
            action_kind="repair",
            target=ProposalTarget(
                title="Target Title",
                year=2021,
                media_type="movie",
                imdb_id="tt1234567",
            ),
        )
        proposal.source_title_fingerprint = source_fingerprint
        proposal.occurrence_fingerprints = {
            "occurrence-1": occurrence_fingerprint
        }
        planning = ApplicationPlanner().plan(
            proposal,
            ApplicationCurrentSnapshot(
                source_title=source_title,
                source_occurrences={"occurrence-1": occurrences["occurrence-1"]},
                source_occurrence_count=len(occurrences),
            ),
        )
        self.assertEqual(planning.outcome, "ready")
        self.assertIsNotNone(planning.plan)
        store = FirestoreProposalApplicationStore(self.db)
        lease = store.acquire_lease(
            "proposal-1", datetime.timedelta(minutes=5), self.now
        )
        self.assertTrue(lease)
        return store, planning.plan, lease

    def test_acquisition_persists_random_owner_and_allows_one_worker(self) -> None:
        self._seed_proposal("proposal-1")
        store = FirestoreProposalApplicationStore(self.db)

        acquired = store.acquire_lease(
            "proposal-1",
            datetime.timedelta(minutes=5),
            self.now,
        )
        rejected = store.acquire_lease(
            "proposal-1",
            datetime.timedelta(minutes=5),
            self.now + datetime.timedelta(minutes=1),
        )

        self.assertTrue(acquired)
        self.assertIsNotNone(acquired.lease_owner)
        self.assertEqual(acquired.reason_code, "lease_acquired")
        self.assertFalse(rejected)
        self.assertEqual(rejected.reason_code, "lease_unavailable")

        stored = self.db.collection("auditProposals").document("proposal-1").get().to_dict()
        self.assertEqual(stored["status"], "applying")
        self.assertEqual(stored["leaseOwner"], acquired.lease_owner)
        self.assertEqual(stored["leasedUntil"], self.now + datetime.timedelta(minutes=5))
        self.assertEqual(stored["updatedAt"], self.now)

    def test_same_source_proposals_have_one_winner_under_concurrent_attempts(self) -> None:
        self._seed_proposal("proposal-a")
        self._seed_proposal("proposal-b")

        def acquire(proposal_id: str):
            return FirestoreProposalApplicationStore(self.db).acquire_lease(
                proposal_id,
                datetime.timedelta(minutes=5),
                self.now,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(acquire, ("proposal-a", "proposal-b")))

        self.assertEqual(sum(result.acquired for result in results), 1)
        self.assertEqual(
            sorted(result.reason_code for result in results),
            ["lease_acquired", "lease_unavailable"],
        )

    def test_expired_lease_fails_without_catalog_mutation_or_evidence_logging(self) -> None:
        expired_at = self.now - datetime.timedelta(minutes=1)
        self._seed_proposal(
            "expired-proposal",
            status="applying",
            leased_until=expired_at,
        )
        title_ref = self.db.collection("titles").document("source-title")
        occurrence_ref = title_ref.collection("occurrences").document("occurrence-1")
        title_ref.set({"title": "Source Title", "updatedAt": self.now})
        occurrence_ref.set({"rawTitle": "Source Title 2020 1080p", "updatedAt": self.now})
        title_before = title_ref.get().to_dict()
        occurrence_before = occurrence_ref.get().to_dict()

        result = FirestoreProposalApplicationStore(self.db).acquire_lease(
            "expired-proposal",
            datetime.timedelta(minutes=5),
            self.now,
        )

        self.assertFalse(result)
        self.assertEqual(result.reason_code, "lease_expired")
        self.assertNotIn("synthetic test evidence", result.reason)
        stored = self.db.collection("auditProposals").document("expired-proposal").get().to_dict()
        self.assertEqual(stored["status"], "failed")
        self.assertIsNone(stored["leaseOwner"])
        self.assertIsNone(stored["leasedUntil"])
        self.assertEqual(stored["failureCode"], "lease_expired")
        self.assertEqual(stored["failureReason"], "Application lease expired or was unrecoverable")
        self.assertEqual(title_ref.get().to_dict(), title_before)
        self.assertEqual(occurrence_ref.get().to_dict(), occurrence_before)

    def test_commit_moves_only_named_occurrences_in_one_transaction(self) -> None:
        store, plan, lease = self._seed_ready_application(
            source_occurrence_ids=("occurrence-1", "occurrence-2")
        )

        result = store.commit_application(plan, lease.lease_owner, self.now)

        target_id = get_title_id_v2("tt1234567", "Target Title", 2021, "movie")
        source_ref = self.db.collection("titles").document("source-title")
        target_ref = self.db.collection("titles").document(target_id)
        self.assertTrue(result.applied)
        self.assertFalse(result.source_deleted)
        self.assertFalse(source_ref.collection("occurrences").document("occurrence-1").get().exists)
        self.assertTrue(source_ref.collection("occurrences").document("occurrence-2").get().exists)
        self.assertTrue(target_ref.collection("occurrences").document("occurrence-1").get().exists)
        self.assertFalse(target_ref.collection("occurrences").document("occurrence-2").get().exists)
        self.assertFalse(source_ref.get().to_dict()["aiValidated"])
        self.assertFalse(target_ref.get().to_dict()["aiValidated"])
        stored_proposal = self.db.collection("auditProposals").document("proposal-1").get().to_dict()
        self.assertEqual(stored_proposal["status"], "applied")
        self.assertIsNone(stored_proposal["leaseOwner"])

    def test_stale_occurrence_fails_proposal_without_catalog_mutation(self) -> None:
        store, plan, lease = self._seed_ready_application()
        source_ref = self.db.collection("titles").document("source-title")
        occurrence_ref = source_ref.collection("occurrences").document("occurrence-1")
        changed_occurrence = occurrence_ref.get().to_dict()
        changed_occurrence["rawTitle"] = "Changed title"
        occurrence_ref.set(changed_occurrence)

        result = store.commit_application(plan, lease.lease_owner, self.now)

        self.assertEqual(result.outcome, "stale")
        self.assertEqual(result.reason_code, "occurrence_changed")
        self.assertTrue(occurrence_ref.get().exists)
        self.assertFalse(
            self.db.collection("titles").document(plan.target_title_id).get().exists
        )
        stored_proposal = self.db.collection("auditProposals").document("proposal-1").get().to_dict()
        self.assertEqual(stored_proposal["status"], "failed")
        self.assertIsNone(stored_proposal["leaseOwner"])
        self.assertIsNone(stored_proposal["leasedUntil"])
        self.assertEqual(stored_proposal["failureCode"], "stale")
        self.assertFalse(
            self.db.collection("proposalApplicationLeases").document("source-title").get().exists
        )

    def test_retried_commit_is_idempotent(self) -> None:
        store, plan, lease = self._seed_ready_application()

        first = store.commit_application(plan, lease.lease_owner, self.now)
        second = store.commit_application(plan, lease.lease_owner, self.now)

        self.assertTrue(first.applied)
        self.assertTrue(second.applied)
        self.assertEqual(second.reason_code, "already_applied")


if __name__ == "__main__":
    unittest.main()