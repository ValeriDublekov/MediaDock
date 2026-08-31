from typing import Any, Optional

from .firestore_repository import (
    FirestoreAuditProposalRepository,
    FirestoreOccurrenceRepository,
    FirestoreTitleRepository,
    get_firestore_client,
)
from .proposal_application_store import RepositoryProposalApplicationStore


class FirestoreProposalApplicationStore(RepositoryProposalApplicationStore):
    """Firestore-backed application store using one shared client instance."""

    def __init__(self, db: Optional[Any] = None) -> None:
        self.db = db if db is not None else get_firestore_client()
        super().__init__(
            proposal_repository=FirestoreAuditProposalRepository(self.db),
            title_repository=FirestoreTitleRepository(self.db),
            occurrence_repository=FirestoreOccurrenceRepository(self.db),
        )