import datetime
import unittest
from dataclasses import FrozenInstanceError
from typing import Optional

from movies_feed.audit_proposal import AuditProposal, ProposalTarget
from movies_feed.models import Title, Occurrence
from movies_feed.proposal_application_store import FakeProposalApplicationStore
from backend.tests.fakes import (
    FakeAuditProposalRepository,
    FakeOccurrenceRepository,
    FakeTitleRepository,
)
from movies_feed.proposal_application import (
    ApplicationPlanner,
    ApplicationOccurrenceFingerprint,
    ApplicationCurrentSnapshot,
    ApplicationSourceTitleFingerprint,
    ProposalApplicationService,
)
from movies_feed.ids import get_title_id_v2

class TestProposalApplicationService(unittest.TestCase):
    def setUp(self) -> None:
        self.proposal_repo = FakeAuditProposalRepository()
        self.title_repo = FakeTitleRepository()
        self.occ_repo = FakeOccurrenceRepository()
        self.store = FakeProposalApplicationStore(
            proposal_repository=self.proposal_repo,
            title_repository=self.title_repo,
            occurrence_repository=self.occ_repo,
        )
        
        self.now = datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
        self.clock = lambda: self.now
        
        self.service = ProposalApplicationService(store=self.store, clock=self.clock)

    def _make_proposal(
        self, 
        proposal_id: str, 
        source_title_id: str, 
        status: str,
        occurrence_ids: list[str],
        target: ProposalTarget,
        occurrence_fingerprints: Optional[dict[str, ApplicationOccurrenceFingerprint]] = None,
    ) -> AuditProposal:
        proposal = AuditProposal(
            id=proposal_id,
            source_title_id=source_title_id,
            occurrence_ids=occurrence_ids,
            raw_title_cluster=["raw title"],
            current_metadata={},
            proposed_metadata=target.to_dict(),
            evidence={},
            confidence=0.9,
            policy_version="v1",
            created_at=self.now,
            updated_at=self.now,
            status=status, # type: ignore
            schema_version=2,
            action_kind="repair",
            target=target,
        )
        source_title = self.title_repo.get(source_title_id)
        if source_title is not None:
            proposal.source_title_fingerprint = ApplicationSourceTitleFingerprint.from_title(source_title)
        proposal.occurrence_fingerprints = occurrence_fingerprints or {
            occurrence_id: ApplicationOccurrenceFingerprint.from_occurrence(occurrence)
            for occurrence_id in occurrence_ids
            if (occurrence := self.occ_repo.get(source_title_id, occurrence_id)) is not None
        }
        return proposal

    def _make_title(self, title_id: str, title: str, year: int, media_type: str) -> None:
        t = Title(
            title=title,
            normalized_title=title.lower(),
            year=year,
            media_type=media_type,
            first_seen_at=self.now,
            last_seen_at=self.now,
            updated_at=self.now,
        )
        self.title_repo.upsert(title_id, t)

    def _make_occ(self, title_id: str, occ_id: str) -> None:
        occ = Occurrence(
            source_feed_id="feed1",
            source_feed_name="Feed 1",
            feed_entry_id=occ_id,
            torrent_url=f"http://example.com/{occ_id}",
            raw_title="raw title",
            quality=None,
            rip_type=None,
            first_seen_at=self.now,
            last_seen_at=self.now,
        )
        self.occ_repo.upsert(title_id, occ_id, occ)

    def _make_target(
        self,
        title: str = "Target Title",
        year: int = 2021,
        imdb_id: Optional[str] = None,
    ) -> ProposalTarget:
        return ProposalTarget(
            title=title,
            year=year,
            imdb_id=imdb_id,
            media_type="movie",
        )
    def test_partial_cluster_moves(self) -> None:
        self._make_title("t1", "Title 1", 2020, "movie")
        self._make_occ("t1", "occ1")
        self._make_occ("t1", "occ2")
        
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], 
            self._make_target("Title 2")
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "applied")
        self.assertEqual(res.occurrences_moved, 1)
        self.assertFalse(res.source_deleted)
        
        self.assertIsNotNone(self.occ_repo.get(res.target_title_id, "occ1"))
        self.assertIsNone(self.occ_repo.get("t1", "occ1"))
        self.assertIsNotNone(self.occ_repo.get("t1", "occ2"))
        
        t1 = self.title_repo.get("t1")
        self.assertIsNotNone(t1)

    def test_target_already_exists(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        
        target_id = get_title_id_v2(None, "Target Title", 2021, "movie")
        self._make_title(target_id, "Target Title", 2021, "movie")
        
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], 
            self._make_target()
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "applied")
        
        t2 = self.title_repo.get(res.target_title_id)
        self.assertIsNotNone(t2)
        self.assertEqual(t2.title, "Target Title")

    def test_same_source_target(self) -> None:
        target_id = get_title_id_v2(None, "Target Title", 2021, "movie")
        self._make_title(target_id, "Target Title", 2021, "movie")
        self._make_occ(target_id, "occ1")
        
        p = self._make_proposal(
            "p1", target_id, "approved", ["occ1"], 
            self._make_target()
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "skipped")
        self.assertEqual(res.reason, "Same source and target")
        self.assertEqual(self.proposal_repo.get("p1").status, "applied")

    def test_stale_lease_recovery(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        
        p = self._make_proposal(
            "p1", "t1", "applying", ["occ1"], 
            self._make_target()
        )
        # Set lease to be in the past
        p.leased_until = self.now - datetime.timedelta(minutes=1)
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "failed")
        self.assertEqual(res.reason, "Proposal lease was stale and recovered to failed")
        self.assertEqual(self.proposal_repo.get("p1").status, "failed")
        self.assertIsNone(self.proposal_repo.get("p1").leased_until)

    def test_concurrent_source_title_locked(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        self._make_occ("t1", "occ2")
        
        # p2 is applying on t1 with a valid lease
        p2 = self._make_proposal(
            "p2", "t1", "applying", ["occ2"], 
            self._make_target("Target Title 2", 2022)
        )
        p2.leased_until = self.now + datetime.timedelta(minutes=5)
        self.proposal_repo.upsert(p2)
        
        p1 = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], 
            self._make_target()
        )
        self.proposal_repo.upsert(p1)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "skipped")
        self.assertIn("Could not acquire lease", res.reason)
        
        # p1 should still be approved
        self.assertEqual(self.proposal_repo.get("p1").status, "approved")

    def test_stale_proposal(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], 
            self._make_target()
        )
        self.title_repo.delete("t1")
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "stale")
        self.assertEqual(res.reason, "Source title no longer exists")
        self.assertEqual(self.proposal_repo.get("p1").status, "approved")

    def test_repeated_interrupted_execution(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        self._make_occ("t1", "occ2")
        occ1_snapshot = self.occ_repo.get("t1", "occ1")
        
        # Simulate interruption: occ1 already moved, occ2 not
        target_id = get_title_id_v2(None, "Target Title", 2021, "movie")
        self._make_title(target_id, "Target Title", 2021, "movie")
        
        occ1 = self.occ_repo.get("t1", "occ1")
        self.occ_repo.upsert(target_id, "occ1", occ1)
        self.occ_repo.delete("t1", "occ1")
        
        # A target-only occurrence is not proof that the source snapshot is current.
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1", "occ2"], 
            self._make_target(),
            occurrence_fingerprints={
                "occ1": ApplicationOccurrenceFingerprint.from_occurrence(occ1_snapshot),
                "occ2": ApplicationOccurrenceFingerprint.from_occurrence(
                    self.occ_repo.get("t1", "occ2")
                ),
            },
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "stale")
        self.assertEqual(self.proposal_repo.get("p1").status, "approved")
        
        # Verify the stale attempt did not move the remaining source occurrence.
        self.assertIsNotNone(self.occ_repo.get(target_id, "occ1"))
        self.assertIsNone(self.occ_repo.get(target_id, "occ2"))
        self.assertIsNotNone(self.occ_repo.get("t1", "occ2"))

    def test_last_occurrence_cleanup(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], 
            self._make_target()
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertTrue(res.source_deleted)
        self.assertIsNone(self.title_repo.get("t1"))

    def test_batch_like_failure(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        occ1 = self.occ_repo.get("t1", "occ1")
        
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1", "occ2"], 
            self._make_target(),
            occurrence_fingerprints={
                "occ1": ApplicationOccurrenceFingerprint.from_occurrence(occ1),
                "occ2": ApplicationOccurrenceFingerprint.from_occurrence(occ1),
            },
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "stale")
        self.assertIn("missing", res.reason)
        self.assertEqual(self.proposal_repo.get("p1").status, "approved")
        self.assertIsNone(self.title_repo.get(res.target_title_id))
        self.assertIsNotNone(self.occ_repo.get("t1", "occ1"))

    def test_confirmed_rejection(self) -> None:
        p = self._make_proposal(
            "p1", "t1", "pending", ["occ1"], 
            self._make_target()
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1", reject=True)
        self.assertEqual(res.outcome, "applied")
        self.assertEqual(self.proposal_repo.get("p1").status, "rejected")

    def test_dry_run(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], 
            self._make_target()
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1", dry_run=True)
        self.assertEqual(res.outcome, "planned")
        self.assertTrue(res.source_deleted)
        self.assertIsNotNone(res.plan)
        self.assertEqual(res.plan.target_title_id, get_title_id_v2(None, "Target Title", 2021, "movie"))
        with self.assertRaises(FrozenInstanceError):
            res.plan.target_title_id = "changed"
        self.assertEqual(self.proposal_repo.get("p1").status, "approved")
        self.assertIsNone(self.proposal_repo.get("p1").leased_until)
        
        self.assertIsNotNone(self.occ_repo.get("t1", "occ1"))

    def test_planner_is_pure(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        proposal = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], self._make_target()
        )
        self.proposal_repo.upsert(proposal)

        source_title = self.title_repo.get("t1")
        source_occurrence = self.occ_repo.get("t1", "occ1")
        result = ApplicationPlanner().plan(
            proposal,
            ApplicationCurrentSnapshot(
                source_title=source_title,
                source_occurrences={"occ1": source_occurrence},
                source_occurrence_count=1,
            ),
        )

        self.assertEqual(result.outcome, "ready")
        self.assertIsNotNone(result.plan)
        self.assertEqual(self.proposal_repo.get("p1").status, "approved")
        self.assertIsNotNone(self.occ_repo.get("t1", "occ1"))

    def test_ineligible_contract_cases_do_not_mutate(self) -> None:
        cases = (
            ("schema", "schema_version", 1, "schema_version"),
            ("action", "action_kind", "review_only", "action_kind"),
            ("policy", "policy_version", "v2", "policy_version_mismatch"),
            ("target", "target", None, "incomplete_target"),
        )
        self._make_title("t1", "Source Title", 2020, "movie")
        for index, (_, attribute_name, value, reason_code) in enumerate(cases):
            occurrence_id = f"occ{index}"
            self._make_occ("t1", occurrence_id)
            proposal = self._make_proposal(
                f"p{index}", "t1", "approved", [occurrence_id], self._make_target()
            )
            setattr(proposal, attribute_name, value)
            self.proposal_repo.upsert(proposal)

            result = self.service.apply_proposal(proposal.id)

            self.assertEqual(result.outcome, "ineligible")
            self.assertEqual(result.reason_code, reason_code)
            self.assertEqual(self.proposal_repo.get(proposal.id).status, "approved")
            self.assertIsNotNone(self.occ_repo.get("t1", occurrence_id))

    def test_missing_occurrence_fingerprint_is_ineligible_without_mutation(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        proposal = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], self._make_target()
        )
        proposal.occurrence_fingerprints = {}
        self.proposal_repo.upsert(proposal)

        result = self.service.apply_proposal(proposal.id)

        self.assertEqual(result.outcome, "ineligible")
        self.assertEqual(result.reason_code, "occurrence_fingerprint_membership")
        self.assertEqual(self.proposal_repo.get(proposal.id).status, "approved")
        self.assertIsNotNone(self.occ_repo.get("t1", "occ1"))

    def test_oversized_proposal_is_ineligible_without_mutation(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        occurrence_ids = [f"occ{index}" for index in range(201)]
        proposal = self._make_proposal(
            "p1", "t1", "approved", occurrence_ids, self._make_target()
        )
        self.proposal_repo.upsert(proposal)

        result = self.service.apply_proposal(proposal.id)

        self.assertEqual(result.outcome, "ineligible")
        self.assertEqual(result.reason_code, "occurrence_limit")
        self.assertEqual(self.proposal_repo.get(proposal.id).status, "approved")
        self.assertIsNone(self.title_repo.get(result.target_title_id))

    def test_changed_source_title_is_stale_without_mutation(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        proposal = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], self._make_target()
        )
        self.proposal_repo.upsert(proposal)
        changed_title = self.title_repo.get("t1")
        changed_title.title = "Changed Source Title"
        self.title_repo.upsert("t1", changed_title)

        result = self.service.apply_proposal(proposal.id)

        self.assertEqual(result.outcome, "stale")
        self.assertEqual(result.reason_code, "source_title_changed")
        self.assertEqual(self.proposal_repo.get(proposal.id).status, "approved")
        self.assertIsNotNone(self.occ_repo.get("t1", "occ1"))

    def test_changed_occurrence_is_stale_without_mutation(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        proposal = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], self._make_target()
        )
        self.proposal_repo.upsert(proposal)
        changed_occurrence = self.occ_repo.get("t1", "occ1")
        changed_occurrence.raw_title = "Changed raw title"
        self.occ_repo.upsert("t1", "occ1", changed_occurrence)

        result = self.service.apply_proposal(proposal.id)

        self.assertEqual(result.outcome, "stale")
        self.assertEqual(result.reason_code, "occurrence_changed")
        self.assertEqual(self.proposal_repo.get(proposal.id).status, "approved")
        self.assertIsNotNone(self.occ_repo.get("t1", "occ1"))

if __name__ == "__main__":
    unittest.main()
