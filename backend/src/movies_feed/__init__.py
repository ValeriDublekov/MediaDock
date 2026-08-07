"""MoviesFeed / MediaDock backend package."""

from .ids import (
    get_cache_key,
    get_fallback_title_id,
    get_occurrence_id,
    get_title_id,
    normalize_title,
)
from .models import OmdbCacheEntry, Occurrence, ScanRun, Title
from .repository import (
    FakeOmdbCacheRepository,
    FakeOccurrenceRepository,
    FakeScanRunRepository,
    FakeTitleRepository,
    OmdbCacheRepository,
    OccurrenceRepository,
    ScanRunRepository,
    TitleRepository,
    merge_occurrences,
    merge_titles,
)

__version__ = "0.1.0"
