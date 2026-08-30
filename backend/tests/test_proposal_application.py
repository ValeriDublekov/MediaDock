import datetime
import unittest
from typing import Any, Dict

from movies_feed.models import AuditProposal, Title, Occurrence
from movies_feed.repository import FakeAuditProposalRepository, FakeTitleRepository, FakeOccurrenceRepository
from movies_feed.proposal_application import ProposalApplicationService
from movies_feed.ids import get_title_id_v2

class TestProposalApplicationService(unittest.TestCase):
    def setUp(self) -> None:
        self.proposal_repo = FakeAuditProposalRepository()
        self.title_repo = FakeTitleRepository()
        self.occ_repo = FakeOccurrenceRepository()
        
        self.now = datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
        self.clock = lambda: self.now
        
        self.service = ProposalApplicationService(
            self.proposal_repo, self.title_repo, self.occ_repo, self.clock
        )

    def _make_proposal(
        self, 
        proposal_id: str, 
        source_title_id: str, 
        status: str,
        occurrence_ids: list[str],
        proposed_metadata: Dict[str, Any]
    ) -> AuditProposal:
        return AuditProposal(
            id=proposal_id,
            source_title_id=source_title_id,
            occurrence_ids=occurrence_ids,
            raw_title_cluster=["raw title"],
            current_metadata={},
            proposed_metadata=proposed_metadata,
            evidence={},
            confidence=0.9,
            policy_version="v1",
            created_at=self.now,
            updated_at=self.now,
            status=status # type: ignore
        )

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

    def test_partial_cluster_moves(self) -> None:
        self._make_title("t1", "Title 1", 2020, "movie")
        self._make_occ("t1", "occ1")
        self._make_occ("t1", "occ2")
        
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], 
            {"title": "Title 2", "year": 2021, "mediaType": "movie"}
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
            {"title": "Target Title", "year": 2021, "mediaType": "movie"}
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
            {"title": "Target Title", "year": 2021, "mediaType": "movie"}
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "skipped")
        self.assertEqual(res.reason, "Same source and target")
        self.assertEqual(self.proposal_repo.get("p1").status, "applied")

    def test_stale_proposal(self) -> None:
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], 
            {"title": "Target Title", "year": 2021, "mediaType": "movie"}
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "failed")
        self.assertEqual(res.reason, "Source title not found")
        self.assertEqual(self.proposal_repo.get("p1").status, "failed")

    def test_repeated_interrupted_execution(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        self._make_occ("t1", "occ2")
        
        p = self._make_proposal(
            "p1", "t1", "applying", ["occ1", "occ2"], 
            {"title": "Target Title", "year": 2021, "mediaType": "movie"}
        )
        self.proposal_repo.upsert(p)
        
        # Simulate interruption: occ1 already moved, occ2 not
        target_id = get_title_id_v2(None, "Target Title", 2021, "movie")
        self._make_title(target_id, "Target Title", 2021, "movie")
        
        # We also need to construct occ1 first, and then upsert
        # but self._make_occ can be used
        # Wait, occ1 is currently in "t1". I need to move it to target_id.
        occ1 = self.occ_repo.get("t1", "occ1")
        self.occ_repo.upsert(target_id, "occ1", occ1)
        self.occ_repo.delete("t1", "occ1")
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "applied")
        self.assertEqual(self.proposal_repo.get("p1").status, "applied")
        
        # Verify both moved
        self.assertIsNotNone(self.occ_repo.get(target_id, "occ1"))
        self.assertIsNotNone(self.occ_repo.get(target_id, "occ2"))

    def test_last_occurrence_cleanup(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1"], 
            {"title": "Target Title", "year": 2021, "mediaType": "movie"}
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertTrue(res.source_deleted)
        self.assertIsNone(self.title_repo.get("t1"))

    def test_batch_like_failure(self) -> None:
        self._make_title("t1", "Source Title", 2020, "movie")
        self._make_occ("t1", "occ1")
        
        p = self._make_proposal(
            "p1", "t1", "approved", ["occ1", "occ2"], 
            {"title": "Target Title", "year": 2021, "mediaType": "movie"}
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1")
        self.assertEqual(res.outcome, "failed")
        self.assertIn("missing", res.reason)
        self.assertEqual(self.proposal_repo.get("p1").status, "failed")

    def test_confirmed_rejection(self) -> None:
        p = self._make_proposal(
            "p1", "t1", "pending", ["occ1"], 
            {"title": "Target Title", "year": 2021, "mediaType": "movie"}
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
            {"title": "Target Title", "year": 2021, "mediaType": "movie"}
        )
        self.proposal_repo.upsert(p)
        
        res = self.service.apply_proposal("p1", dry_run=True)
        self.assertEqual(res.outcome, "planned")
        self.assertTrue(res.source_deleted)
        self.assertEqual(self.proposal_repo.get("p1").status, "approved")
        
        self.assertIsNotNone(self.occ_repo.get("t1", "occ1"))

if __name__ == "__main__":
    unittest.main()
