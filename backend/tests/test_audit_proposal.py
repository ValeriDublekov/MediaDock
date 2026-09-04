import datetime
from dataclasses import FrozenInstanceError
import unittest
from typing import Optional

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

from movies_feed import (
    AuditProposal,
    BroadcastRange,
    InvalidStatusTransitionError,
    audit_proposal_from_dict,
    get_audit_proposal_id,
    is_valid_proposal_status_transition,
    measure_evidence_size_bytes,
    redact_secrets,
)
from backend.tests.fakes import FakeAuditProposalRepository
from movies_feed.audit_proposal import ProposalSourceSnapshot, ProposalTarget
from movies_feed.ids import get_audit_proposal_id_v3

from unittest.mock import MagicMock
import sys

try:
    from movies_feed.firestore_repository import FirestoreAuditProposalRepository
    HAVE_FIRESTORE = not isinstance(sys.modules.get("firebase_admin"), MagicMock) and not isinstance(sys.modules.get("google.cloud.firestore"), MagicMock)
except ImportError:
    HAVE_FIRESTORE = False
    FirestoreAuditProposalRepository = None


class MockSnapshot:
    def __init__(self, doc_id: str, data: dict, exists: bool = True) -> None:
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self) -> dict:
        return dict(self._data) if self._data else {}


class MockDocRef:
    def __init__(self, doc_id: str, collection_dict: dict) -> None:
        self.id = doc_id
        self._collection_dict = collection_dict

    def get(self, transaction=None) -> MockSnapshot:
        if self.id in self._collection_dict:
            return MockSnapshot(self.id, self._collection_dict[self.id], exists=True)
        return MockSnapshot(self.id, {}, exists=False)

    def set(self, data: dict) -> None:
        self._collection_dict[self.id] = dict(data)

    def delete(self) -> None:
        if self.id in self._collection_dict:
            del self._collection_dict[self.id]


class MockQuery:
    def __init__(self, collection_dict: dict, filters=None, limit_val=None) -> None:
        self._collection_dict = collection_dict
        self._filters = filters or []
        self._limit_val = limit_val

    def where(self, field: str, op: str, value: any) -> "MockQuery":
        new_filters = list(self._filters)
        new_filters.append((field, op, value))
        return MockQuery(self._collection_dict, new_filters, self._limit_val)

    def limit(self, val: int) -> "MockQuery":
        return MockQuery(self._collection_dict, self._filters, val)

    def stream(self):
        results = []
        for doc_id, data in self._collection_dict.items():
            match = True
            for field, op, val in self._filters:
                if op == "==":
                    if data.get(field) != val:
                        match = False
                        break
            if match:
                results.append(MockSnapshot(doc_id, data, exists=True))
        if self._limit_val is not None:
            results = results[: self._limit_val]
        return results


class MockCollectionRef:
    def __init__(self, collection_dict: dict) -> None:
        self._collection_dict = collection_dict

    def document(self, doc_id: str) -> MockDocRef:
        return MockDocRef(doc_id, self._collection_dict)

    def where(self, field: str, op: str, value: any) -> MockQuery:
        return MockQuery(self._collection_dict, [(field, op, value)])

    def stream(self):
        return [MockSnapshot(doc_id, data, exists=True) for doc_id, data in self._collection_dict.items()]


class MockTransaction:
    _read_only = False
    _max_attempts = 1
    _id = b"test-tx-123"

    def _begin(self, retry_id=None):
        pass

    def _rollback(self):
        pass

    def _clean_up(self):
        pass

    def _commit(self):
        pass

    def get(self, doc_ref: MockDocRef) -> MockSnapshot:
        return doc_ref.get()

    def set(self, doc_ref: MockDocRef, data: dict) -> None:
        doc_ref.set(data)


class MockFirestoreClient:
    def __init__(self) -> None:
        self.collections = {}

    def collection(self, name: str) -> MockCollectionRef:
        if name not in self.collections:
            self.collections[name] = {}
        return MockCollectionRef(self.collections[name])

    def transaction(self) -> MockTransaction:
        return MockTransaction()


class AuditProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.utc = datetime.timezone.utc
        self.now = datetime.datetime(2026, 8, 10, 12, 0, 0, tzinfo=self.utc)
        self.earlier = datetime.datetime(2026, 8, 10, 10, 0, 0, tzinfo=self.utc)
        self.later = datetime.datetime(2026, 8, 10, 14, 0, 0, tzinfo=self.utc)

    def make_proposal(
        self,
        proposal_id: str = "prop-123",
        source_title_id: str = "tt0133093",
        occurrence_ids=None,
        raw_title_cluster=None,
        current_metadata=None,
        proposed_metadata=None,
        evidence=None,
        confidence: float = 0.95,
        policy_version: str = "v1",
        created_at=None,
        updated_at=None,
        status: str = "pending",
        schema_version: int = 2,
        action_kind: str = "review_only",
        target: Optional[ProposalTarget] = None,
    ) -> AuditProposal:
        return AuditProposal(
            id=proposal_id,
            source_title_id=source_title_id,
            occurrence_ids=occurrence_ids if occurrence_ids is not None else ["occ-1", "occ-2"],
            raw_title_cluster=raw_title_cluster if raw_title_cluster is not None else ["The Matrix 1999 1080p", "The.Matrix.1999.720p"],
            current_metadata=current_metadata if current_metadata is not None else {"title": "The Matrix", "year": 1999, "imdbId": "tt0133093"},
            proposed_metadata=proposed_metadata if proposed_metadata is not None else {"title": "The Matrix", "year": 1999, "imdbId": "tt0133093"},
            evidence=evidence if evidence is not None else {"ai_verdict": "valid", "score": 0.98},
            confidence=confidence,
            policy_version=policy_version,
            created_at=created_at or self.now,
            updated_at=updated_at or self.now,
            status=status,
            schema_version=schema_version,
            action_kind=action_kind,
            target=target,
        )

    # 1. Deterministic ID Generation Tests
    def test_deterministic_id_generation(self) -> None:
        source_id = "tt0133093"
        cluster = ["The Matrix 1999 1080p", "The Matrix 1999 720p"]
        id1 = get_audit_proposal_id(source_id, cluster, "v1")
        # Same inputs in different order should produce identical ID
        id2 = get_audit_proposal_id(source_id, ["The Matrix 1999 720p", "The Matrix 1999 1080p"], "v1")
        self.assertEqual(id1, id2)
        self.assertTrue(len(id1) == 64)

        # Different policy version should produce different ID
        id3 = get_audit_proposal_id(source_id, cluster, "v2")
        self.assertNotEqual(id1, id3)

        # Different source title ID produces different ID
        id4 = get_audit_proposal_id("tt0000001", cluster, "v1")
        self.assertNotEqual(id1, id4)

        # Empty inputs validation
        with self.assertRaises(ValueError):
            get_audit_proposal_id("", cluster, "v1")
        with self.assertRaises(ValueError):
            get_audit_proposal_id(source_id, [], "v1")

    def test_v3_proposal_id_generation(self) -> None:
        source_title_id = "tt0133093"
        source_feed_id = "feed-main"
        raw_title = "  The   Matrix 1999 1080p  "
        occurrence_ids = ["occ-2", "occ-1"]

        proposal_id = get_audit_proposal_id_v3(
            source_title_id,
            source_feed_id,
            raw_title,
            occurrence_ids,
            "policy-v1",
        )
        reordered_id = get_audit_proposal_id_v3(
            source_title_id,
            source_feed_id,
            raw_title.upper(),
            list(reversed(occurrence_ids)),
            "policy-v1",
        )
        self.assertEqual(proposal_id, reordered_id)
        self.assertNotEqual(
            proposal_id,
            get_audit_proposal_id_v3(
                source_title_id,
                "feed-secondary",
                raw_title,
                occurrence_ids,
                "policy-v1",
            ),
        )
        self.assertNotEqual(
            proposal_id,
            get_audit_proposal_id_v3(
                source_title_id,
                source_feed_id,
                raw_title,
                ["occ-1", "occ-3"],
                "policy-v1",
            ),
        )
        self.assertNotEqual(
            proposal_id,
            get_audit_proposal_id_v3(
                source_title_id,
                source_feed_id,
                raw_title,
                occurrence_ids,
                "policy-v2",
            ),
        )
        self.assertEqual(len(proposal_id), 64)

        for args in (
            ("", source_feed_id, raw_title, occurrence_ids, "policy-v1"),
            (source_title_id, "", raw_title, occurrence_ids, "policy-v1"),
            (source_title_id, source_feed_id, "", occurrence_ids, "policy-v1"),
            (source_title_id, source_feed_id, raw_title, [], "policy-v1"),
            (source_title_id, source_feed_id, raw_title, occurrence_ids, ""),
        ):
            with self.assertRaises(ValueError):
                get_audit_proposal_id_v3(*args)

    # 2. Secret Redaction Tests
    def test_secret_redaction(self) -> None:
        raw_evidence = {
            "api_key": "AIzaSySecretApiKey12345678901234567",
            "gemini_api_key": "my-secret-key",
            "url": "https://api.example.com/data?apikey=AIzaSySecretApiKey12345678901234567&other=1",
            "headers": {"Authorization": "Bearer ya29.a0AfH6SM...", "User-Agent": "MediaDock/1.0 Bearer ya29.a0AfH6SM..."},
            "nested": {
                "token": "secret_token_val",
                "normal": "Safe value with AIzaSySecretApiKey12345678901234567 inline",
            },
        }
        redacted = redact_secrets(raw_evidence)
        self.assertEqual(redacted["api_key"], "[REDACTED]")
        self.assertEqual(redacted["gemini_api_key"], "[REDACTED]")
        self.assertIn("apikey=[REDACTED]", redacted["url"])
        self.assertNotIn("AIzaSySecretApiKey", redacted["url"])
        self.assertEqual(redacted["headers"]["Authorization"], "[REDACTED]")
        self.assertEqual(redacted["headers"]["User-Agent"], "MediaDock/1.0 Bearer [REDACTED]")
        self.assertEqual(redacted["nested"]["token"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["normal"], "Safe value with [REDACTED] inline")

    # 3. Evidence Size Bounds Tests
    def test_evidence_size_bounds(self) -> None:
        # Under 32 KiB is fine
        small_evidence = {"note": "a" * 1000}
        proposal = self.make_proposal(evidence=small_evidence)
        self.assertIsNotNone(proposal)

        # Over 32 KiB must raise ValueError
        huge_evidence = {"note": "x" * (33 * 1024)}
        with self.assertRaises(ValueError) as ctx:
            self.make_proposal(evidence=huge_evidence)
        self.assertIn("exceeds maximum limit of 32768 bytes", str(ctx.exception))

    # 4. Model Validation Tests
    def test_model_field_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.make_proposal(proposal_id="")
        with self.assertRaises(ValueError):
            self.make_proposal(source_title_id="")
        with self.assertRaises(ValueError):
            self.make_proposal(occurrence_ids=[])
        with self.assertRaises(ValueError):
            self.make_proposal(raw_title_cluster=[])
        with self.assertRaises(ValueError):
            self.make_proposal(confidence=-0.1)
        with self.assertRaises(ValueError):
            self.make_proposal(confidence=1.5)
        with self.assertRaises(ValueError):
            self.make_proposal(status="unknown_status")

    # 5. Serialization Round-Trip Tests
    def test_serialization_round_trip(self) -> None:
        proposal = self.make_proposal()
        d = proposal.to_dict()
        self.assertEqual(d["id"], "prop-123")
        self.assertEqual(d["sourceTitleId"], "tt0133093")
        self.assertEqual(d["status"], "pending")
        self.assertEqual(d["confidence"], 0.95)
        self.assertEqual(d["schemaVersion"], 2)
        self.assertEqual(d["actionKind"], "review_only")
        self.assertNotIn("target", d)

        restored = audit_proposal_from_dict(d, doc_id="prop-123")
        self.assertEqual(restored.id, proposal.id)
        self.assertEqual(restored.source_title_id, proposal.source_title_id)
        self.assertEqual(restored.occurrence_ids, proposal.occurrence_ids)
        self.assertEqual(restored.raw_title_cluster, proposal.raw_title_cluster)
        self.assertEqual(restored.current_metadata, proposal.current_metadata)
        self.assertEqual(restored.proposed_metadata, proposal.proposed_metadata)
        self.assertEqual(restored.evidence, proposal.evidence)
        self.assertEqual(restored.confidence, proposal.confidence)
        self.assertEqual(restored.policy_version, proposal.policy_version)
        self.assertEqual(restored.created_at, proposal.created_at)
        self.assertEqual(restored.updated_at, proposal.updated_at)
        self.assertEqual(restored.status, proposal.status)
        self.assertEqual(restored.schema_version, proposal.schema_version)
        self.assertEqual(restored.action_kind, proposal.action_kind)
        self.assertEqual(restored.target, proposal.target)

    def test_repair_proposal_round_trip(self) -> None:
        target = ProposalTarget(
            title="The Matrix",
            year=1999,
            imdb_id="tt0133093",
            media_type="movie",
        )
        proposal = self.make_proposal(action_kind="repair", target=target)

        serialized = proposal.to_dict()
        self.assertEqual(proposal.schema_version, 2)
        self.assertEqual(serialized["schemaVersion"], 2)
        self.assertEqual(serialized["actionKind"], "repair")
        self.assertEqual(serialized["target"], target.to_dict())

        restored = audit_proposal_from_dict(serialized)
        self.assertEqual(restored.schema_version, 2)
        self.assertEqual(restored.action_kind, "repair")
        self.assertEqual(restored.target, target)

    def test_action_kind_and_target_validation(self) -> None:
        target = ProposalTarget(title="The Matrix", media_type="movie")

        with self.assertRaises(ValueError):
            self.make_proposal(action_kind="unknown")
        with self.assertRaises(ValueError):
            self.make_proposal(action_kind="repair")
        with self.assertRaises(ValueError):
            self.make_proposal(target=target)
        with self.assertRaises(ValueError):
            self.make_proposal(schema_version=1, action_kind="repair", target=target)

    def test_legacy_proposal_is_review_only_without_target(self) -> None:
        legacy_data = self.make_proposal().to_dict()
        legacy_data.pop("schemaVersion")
        legacy_data.pop("actionKind")
        legacy_data["actionKind"] = "repair"
        legacy_data["target"] = {"title": "Incomplete legacy target"}

        restored = audit_proposal_from_dict(legacy_data)

        self.assertEqual(restored.schema_version, 1)
        self.assertEqual(restored.action_kind, "review_only")
        self.assertIsNone(restored.target)
        self.assertEqual(restored.proposed_metadata["title"], "The Matrix")

        serialized = restored.to_dict()
        self.assertEqual(serialized["schemaVersion"], 1)
        self.assertEqual(serialized["actionKind"], "review_only")
        self.assertNotIn("target", serialized)

    def test_proposal_source_snapshot_round_trip(self) -> None:
        snapshot = ProposalSourceSnapshot(
            title="The Matrix",
            year=1999,
            imdb_id="TT0133093",
            media_type="MOVIE",
            source_type="MOVIE",
            content_kind="DOCUMENTARY",
            broadcast_range=BroadcastRange(start_year=1999, end_year=2000, raw="1999-2000"),
        )

        serialized = snapshot.to_dict()
        self.assertEqual(serialized["mediaType"], "movie")
        self.assertEqual(serialized["imdbId"], "tt0133093")
        self.assertEqual(serialized["sourceType"], "movie")
        self.assertEqual(serialized["contentKind"], "documentary")
        self.assertEqual(serialized["broadcastRange"]["startYear"], 1999)

        restored = ProposalSourceSnapshot.from_dict(serialized)
        self.assertEqual(restored, snapshot)
        with self.assertRaises(FrozenInstanceError):
            snapshot.title = "Changed"

    def test_proposal_target_round_trip_and_validation(self) -> None:
        target = ProposalTarget(
            title="The Matrix",
            year=1999,
            imdb_id="tt0133093",
            media_type="movie",
        )

        serialized = target.to_dict()
        self.assertEqual(serialized, {
            "title": "The Matrix",
            "year": 1999,
            "mediaType": "movie",
            "imdbId": "tt0133093",
        })
        restored = ProposalTarget.from_dict(serialized)
        self.assertEqual(restored, target)

        with self.assertRaises((TypeError, ValueError)):
            ProposalTarget(title="The Matrix")
        for kwargs in (
            {"title": "", "media_type": "movie"},
            {"title": "The Matrix", "media_type": "documentary"},
            {"title": "The Matrix", "media_type": "movie", "imdb_id": "not-an-imdb-id"},
            {"title": "The Matrix", "media_type": "movie", "year": 1879},
            {"title": "The Matrix", "media_type": "movie", "year": 2101},
        ):
            with self.assertRaises(ValueError):
                ProposalTarget(**kwargs)

    # 6. Status Transition State Machine Tests
    def test_status_transitions(self) -> None:
        # Allowed transitions
        self.assertTrue(is_valid_proposal_status_transition("pending", "approved"))
        self.assertTrue(is_valid_proposal_status_transition("pending", "rejected"))
        self.assertTrue(is_valid_proposal_status_transition("approved", "applying"))
        self.assertTrue(is_valid_proposal_status_transition("applying", "applied"))
        self.assertTrue(is_valid_proposal_status_transition("applying", "failed"))
        self.assertTrue(is_valid_proposal_status_transition("failed", "pending"))
        self.assertTrue(is_valid_proposal_status_transition("pending", "pending"))
        self.assertTrue(is_valid_proposal_status_transition("approved", "approved"))
        self.assertTrue(is_valid_proposal_status_transition("applied", "applied"))
        self.assertTrue(is_valid_proposal_status_transition("rejected", "rejected"))

        # Forbidden transitions
        self.assertFalse(is_valid_proposal_status_transition("pending", "applied"))
        self.assertFalse(is_valid_proposal_status_transition("pending", "applying"))
        self.assertFalse(is_valid_proposal_status_transition("approved", "pending"))
        self.assertFalse(is_valid_proposal_status_transition("approved", "applied"))
        self.assertFalse(is_valid_proposal_status_transition("applied", "pending"))
        self.assertFalse(is_valid_proposal_status_transition("applied", "approved"))
        self.assertFalse(is_valid_proposal_status_transition("rejected", "approved"))
        self.assertFalse(is_valid_proposal_status_transition("rejected", "pending"))

    # 7. FakeAuditProposalRepository Tests
    def test_fake_audit_proposal_repository(self) -> None:
        repo = FakeAuditProposalRepository()
        p1 = self.make_proposal(proposal_id="p1", source_title_id="t1", status="pending", created_at=self.earlier)
        p2 = self.make_proposal(proposal_id="p2", source_title_id="t2", status="approved", created_at=self.now)

        repo.upsert(p1)
        repo.upsert(p2)

        # Get
        fetched1 = repo.get("p1")
        self.assertIsNotNone(fetched1)
        self.assertEqual(fetched1.id, "p1")
        self.assertEqual(fetched1.status, "pending")

        # Defensive copy check
        fetched1.status = "rejected"
        self.assertEqual(repo.get("p1").status, "pending")

        # List by status
        pending_list = repo.list_by_status("pending")
        self.assertEqual(len(pending_list), 1)
        self.assertEqual(pending_list[0].id, "p1")

        approved_list = repo.list_by_status("approved")
        self.assertEqual(len(approved_list), 1)
        self.assertEqual(approved_list[0].id, "p2")

        # List by source title
        by_source = repo.list_by_source_title("t1")
        self.assertEqual(len(by_source), 1)
        self.assertEqual(by_source[0].id, "p1")

        # List all
        all_props = repo.list_all()
        self.assertEqual(len(all_props), 2)

        # Valid transition: pending -> approved
        p1_approved = self.make_proposal(
            proposal_id="p1", source_title_id="t1", status="approved", created_at=self.later, updated_at=self.later
        )
        repo.upsert(p1_approved)
        updated_p1 = repo.get("p1")
        self.assertEqual(updated_p1.status, "approved")
        # Earliest created_at must be preserved
        self.assertEqual(updated_p1.created_at, self.earlier)
        self.assertEqual(updated_p1.updated_at, self.later)

        # Invalid transition: approved -> pending
        p1_invalid = self.make_proposal(proposal_id="p1", source_title_id="t1", status="pending")
        with self.assertRaises(InvalidStatusTransitionError):
            repo.upsert(p1_invalid)

        # Delete
        repo.delete("p1")
        self.assertIsNone(repo.get("p1"))
        self.assertEqual(len(repo.list_all()), 1)

    def test_fake_audit_refresh_preserves_pending_and_decisions(self) -> None:
        repo = FakeAuditProposalRepository()
        pending = self.make_proposal(
            proposal_id="refresh-pending",
            created_at=self.earlier,
            updated_at=self.earlier,
            evidence={"version": 1},
        )
        repo.upsert(pending)

        refreshed_pending = self.make_proposal(
            proposal_id=pending.id,
            created_at=self.later,
            updated_at=self.later,
            evidence={"version": 2},
            confidence=0.8,
        )
        repo.refresh_from_audit(refreshed_pending)

        stored_pending = repo.get(pending.id)
        self.assertEqual(stored_pending.created_at, self.earlier)
        self.assertEqual(stored_pending.updated_at, self.later)
        self.assertEqual(stored_pending.evidence, {"version": 2})
        self.assertEqual(stored_pending.confidence, 0.8)

        for status in ("approved", "applying", "applied", "rejected"):
            with self.subTest(status=status):
                existing = self.make_proposal(
                    proposal_id=f"refresh-{status}",
                    status=status,
                    created_at=self.earlier,
                    updated_at=self.earlier,
                    evidence={"operator": "keep"},
                )
                if status == "applying":
                    existing.leased_until = self.later
                repo.upsert(existing)

                repo.refresh_from_audit(self.make_proposal(
                    proposal_id=existing.id,
                    status="pending",
                    created_at=self.later,
                    updated_at=self.later,
                    evidence={"operator": "replace"},
                ))

                self.assertEqual(repo.get(existing.id), existing)

    # 8. FirestoreAuditProposalRepository Parity Tests
    @unittest.skipUnless(HAVE_FIRESTORE, "firebase_admin/firestore not installed")
    def test_firestore_audit_proposal_repository_parity(self) -> None:
        mock_client = MockFirestoreClient()
        repo = FirestoreAuditProposalRepository(db=mock_client)

        p1 = self.make_proposal(proposal_id="fp1", source_title_id="t1", status="pending", created_at=self.earlier)
        p2 = self.make_proposal(proposal_id="fp2", source_title_id="t2", status="approved", created_at=self.now)

        repo.upsert(p1)
        repo.upsert(p2)

        # Get
        fetched = repo.get("fp1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, "fp1")
        self.assertEqual(fetched.status, "pending")

        # Query by status
        pending_list = repo.list_by_status("pending")
        self.assertEqual(len(pending_list), 1)
        self.assertEqual(pending_list[0].id, "fp1")

        # Query by source title
        by_source = repo.list_by_source_title("t2")
        self.assertEqual(len(by_source), 1)
        self.assertEqual(by_source[0].id, "fp2")

        # List all
        all_props = repo.list_all()
        self.assertEqual(len(all_props), 2)

        # Valid transition: pending -> approved
        p1_approved = self.make_proposal(
            proposal_id="fp1", source_title_id="t1", status="approved", created_at=self.later, updated_at=self.later
        )
        repo.upsert(p1_approved)
        updated_p1 = repo.get("fp1")
        self.assertEqual(updated_p1.status, "approved")
        self.assertEqual(updated_p1.created_at, self.earlier)
        self.assertEqual(updated_p1.updated_at, self.later)

        # Invalid transition: approved -> pending
        p1_invalid = self.make_proposal(proposal_id="fp1", source_title_id="t1", status="pending")
        with self.assertRaises(InvalidStatusTransitionError):
            repo.upsert(p1_invalid)

        pending_refresh = self.make_proposal(
            proposal_id="fp-refresh-pending",
            created_at=self.earlier,
            updated_at=self.earlier,
            evidence={"version": 1},
        )
        repo.upsert(pending_refresh)
        repo.refresh_from_audit(self.make_proposal(
            proposal_id=pending_refresh.id,
            created_at=self.later,
            updated_at=self.later,
            evidence={"version": 2},
        ))
        refreshed_pending = repo.get(pending_refresh.id)
        self.assertEqual(refreshed_pending.created_at, self.earlier)
        self.assertEqual(refreshed_pending.updated_at, self.later)
        self.assertEqual(refreshed_pending.evidence, {"version": 2})

        preserved_approved = repo.get("fp2")
        repo.refresh_from_audit(self.make_proposal(
            proposal_id="fp2",
            source_title_id="t2",
            status="pending",
            created_at=self.later,
            updated_at=self.later,
            evidence={"operator": "replace"},
        ))
        self.assertEqual(repo.get("fp2"), preserved_approved)

        # Delete
        repo.delete(pending_refresh.id)
        repo.delete("fp1")
        self.assertIsNone(repo.get("fp1"))
        self.assertEqual(len(repo.list_all()), 1)


if __name__ == "__main__":
    unittest.main()
