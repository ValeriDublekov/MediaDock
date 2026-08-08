"""MoviesFeed / MediaDock backend package."""

from .ids import (
    get_cache_key,
    get_fallback_title_id,
    get_occurrence_id,
    get_title_id,
    normalize_title,
)
from .models import OmdbCacheEntry, Occurrence, ParseLog, ScanRun, Title
from .repository import (
    FakeOmdbCacheRepository,
    FakeOccurrenceRepository,
    FakeParseLogRepository,
    FakeScanRunRepository,
    FakeTitleRepository,
    OmdbCacheRepository,
    OccurrenceRepository,
    ParseLogRepository,
    ScanRunRepository,
    TitleRepository,
    merge_occurrences,
    merge_titles,
)
from .firestore_repository import (
    FirestoreTitleRepository,
    FirestoreOccurrenceRepository,
    FirestoreOmdbCacheRepository,
    FirestoreParseLogRepository,
    FirestoreScanRunRepository,
    get_firestore_client,
)

__version__ = "0.1.0"
