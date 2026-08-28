"""MoviesFeed / MediaDock backend package."""

from .ids import (
    get_audit_event_id,
    get_cache_key,
    get_fallback_title_id,
    get_fallback_title_id_v1,
    get_fallback_title_id_v2,
    get_occurrence_id,
    get_occurrence_id_v1,
    get_source_item_id,
    get_title_id,
    get_title_id_v2,
    normalize_title,
)
from .match_policy import (
    BroadcastRange,
    ContentKind,
    DecisionStatus,
    MatchDecision,
    MediaClassification,
    SourceType,
    classify_media,
    effective_source_type,
    evaluate_match,
    normalize_source_type,
    parse_broadcast_range,
)
from .models import (
    ManualMapping,
    OmdbCacheEntry,
    Occurrence,
    ParseLog,
    ParseLogResolution,
    RetryCursor,
    RetryPage,
    ScanRun,
    SourceContext,
    Title,
)
from .metadata_resolver import (
    MetadataOutcome,
    MetadataOutcomeStatus,
    MetadataResolver,
    OmdbResolver,
    RequestBudget,
)
from .repository import (
    FakeManualMappingRepository,
    FakeOmdbCacheRepository,
    FakeOccurrenceRepository,
    FakeParseLogRepository,
    FakeScanRunRepository,
    FakeTitleRepository,
    ManualMappingRepository,
    OmdbCacheRepository,
    OccurrenceRepository,
    ParseLogRepository,
    ScanRunRepository,
    TitleRepository,
    merge_occurrences,
    merge_parse_logs,
    merge_titles,
)
try:
    from .firestore_repository import (
        FirestoreTitleRepository,
        FirestoreOccurrenceRepository,
        FirestoreOmdbCacheRepository,
        FirestoreParseLogRepository,
        FirestoreScanRunRepository,
        FirestoreManualMappingRepository,
        get_firestore_client,
    )
except ImportError:
    pass

__version__ = "0.1.0"
