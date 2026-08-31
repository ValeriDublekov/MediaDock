import copy
import datetime
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, cast

from .match_policy import BroadcastRange, ContentKind, SourceType, broadcast_range_from_dict


AuditProposalStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "applying",
    "applied",
    "failed",
]

AuditProposalActionKind = Literal["review_only", "repair"]

CURRENT_AUDIT_PROPOSAL_SCHEMA_VERSION = 2
LEGACY_AUDIT_PROPOSAL_SCHEMA_VERSION = 1

VALID_AUDIT_PROPOSAL_STATUSES = frozenset({
    "pending",
    "approved",
    "rejected",
    "applying",
    "applied",
    "failed",
})

VALID_AUDIT_PROPOSAL_ACTION_KINDS = frozenset({"review_only", "repair"})

ALLOWED_AUDIT_PROPOSAL_TRANSITIONS = frozenset({
    ("pending", "approved"),
    ("pending", "rejected"),
    ("approved", "applying"),
    ("applying", "applied"),
    ("applying", "failed"),
    ("failed", "pending"),
})

MAX_AUDIT_PROPOSAL_EVIDENCE_BYTES = 32 * 1024  # 32 KiB = 32768 bytes

_PROPOSAL_MEDIA_TYPES = frozenset({"movie", "series"})
_PROPOSAL_CONTENT_KINDS = frozenset({"standard", "documentary", "short"})
_MIN_METADATA_YEAR = 1880
_MAX_METADATA_YEAR = 2100
_IMDB_ID_PATTERN = re.compile(r"tt\d{7,10}", re.IGNORECASE)


class InvalidStatusTransitionError(ValueError):
    """Raised when an illegal audit proposal status transition is attempted."""
    pass


_SECRET_KEY_PATTERN = re.compile(
    r"^(api[-_]?key|key|token|secret|password|gemini[-_]?api[-_]?key|omdb[-_]?api[-_]?key|authorization)$",
    re.IGNORECASE,
)
_GOOGLE_API_KEY_PATTERN = re.compile(r"AIza[A-Za-z0-9_-]{20,40}")
_BEARER_TOKEN_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE)
_QUERY_SECRET_PATTERN = re.compile(
    r"([?&](?:apikey|api_key|key|token|secret|password|auth)=)[^&]+",
    re.IGNORECASE,
)


def redact_secrets(obj: Any) -> Any:
    """Recursively redacts API keys, tokens, and sensitive query params from strings and structures."""
    if isinstance(obj, str):
        redacted = _GOOGLE_API_KEY_PATTERN.sub("[REDACTED]", obj)
        redacted = _BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", redacted)
        redacted = _QUERY_SECRET_PATTERN.sub(r"\1[REDACTED]", redacted)
        return redacted
    elif isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY_PATTERN.match(k):
                new_dict[k] = "[REDACTED]"
            else:
                new_dict[k] = redact_secrets(v)
        return new_dict
    elif isinstance(obj, list):
        return [redact_secrets(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(redact_secrets(item) for item in obj)
    elif isinstance(obj, set):
        return {redact_secrets(item) for item in obj}
    return obj


def is_valid_proposal_status_transition(old_status: str, new_status: str) -> bool:
    """Checks whether transitioning from old_status to new_status is permitted."""
    if old_status == new_status:
        return True
    return (old_status, new_status) in ALLOWED_AUDIT_PROPOSAL_TRANSITIONS


def measure_evidence_size_bytes(evidence: Any) -> int:
    """Measures the UTF-8 byte size of JSON-serialized evidence."""
    if evidence is None:
        return 0
    serialized = json.dumps(evidence, default=str, separators=(",", ":"))
    return len(serialized.encode("utf-8"))


def _normalize_proposal_title(title: str) -> str:
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Proposal metadata title must be a non-empty string")
    return title.strip()


def _validate_proposal_year(year: Optional[int]) -> None:
    if year is not None and (
        type(year) is not int
        or year < _MIN_METADATA_YEAR
        or year > _MAX_METADATA_YEAR
    ):
        raise ValueError(
            f"Proposal metadata year must be between {_MIN_METADATA_YEAR} and {_MAX_METADATA_YEAR}"
        )


def _normalize_proposal_imdb_id(imdb_id: Optional[str]) -> Optional[str]:
    if imdb_id is None:
        return None
    if not isinstance(imdb_id, str):
        raise ValueError("Proposal metadata imdb_id must be a valid IMDb ID")
    normalized_id = imdb_id.strip().lower()
    if not _IMDB_ID_PATTERN.fullmatch(normalized_id):
        raise ValueError("Proposal metadata imdb_id must match the IMDb ID format")
    return normalized_id


def _normalize_proposal_media_type(media_type: str) -> Literal["movie", "series"]:
    if not isinstance(media_type, str):
        raise ValueError("Proposal metadata media_type must be 'movie' or 'series'")
    normalized_media_type = media_type.strip().lower()
    if normalized_media_type not in _PROPOSAL_MEDIA_TYPES:
        raise ValueError("Proposal metadata media_type must be 'movie' or 'series'")
    return cast(Literal["movie", "series"], normalized_media_type)


def _normalize_proposal_source_type(source_type: Optional[str]) -> Optional[SourceType]:
    if source_type is None:
        return None
    if not isinstance(source_type, str):
        raise ValueError("Proposal metadata source_type must be a valid source type")
    normalized_source_type = source_type.strip().lower()
    if normalized_source_type not in {"movie", "series", "unknown"}:
        raise ValueError("Proposal metadata source_type must be 'movie', 'series', or 'unknown'")
    return cast(SourceType, normalized_source_type)


def _normalize_proposal_content_kind(content_kind: Optional[str]) -> Optional[ContentKind]:
    if content_kind is None:
        return None
    if not isinstance(content_kind, str):
        raise ValueError("Proposal metadata content_kind must be a valid content kind")
    normalized_content_kind = content_kind.strip().lower()
    if normalized_content_kind not in _PROPOSAL_CONTENT_KINDS:
        raise ValueError("Proposal metadata content_kind must be 'standard', 'documentary', or 'short'")
    return cast(ContentKind, normalized_content_kind)


def _validate_proposal_broadcast_range(broadcast_range: Optional[BroadcastRange]) -> None:
    if broadcast_range is None:
        return
    if not isinstance(broadcast_range, BroadcastRange):
        raise ValueError("Proposal metadata broadcast_range must be a BroadcastRange")
    _validate_proposal_year(broadcast_range.start_year)
    _validate_proposal_year(broadcast_range.end_year)


def _proposal_broadcast_range_from_dict(value: Any) -> Optional[BroadcastRange]:
    if value is None:
        return None
    if isinstance(value, BroadcastRange):
        return value
    if not isinstance(value, dict):
        raise ValueError("Proposal metadata broadcastRange must be a dictionary")
    broadcast_range = broadcast_range_from_dict(value)
    if broadcast_range is None:
        raise ValueError("Proposal metadata broadcastRange must be a valid broadcast range")
    return broadcast_range


def _proposal_metadata_to_dict(
    *,
    title: str,
    year: Optional[int],
    imdb_id: Optional[str],
    media_type: Literal["movie", "series"],
    source_type: Optional[SourceType] = None,
    content_kind: Optional[ContentKind] = None,
    broadcast_range: Optional[BroadcastRange] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "title": title,
        "year": year,
        "mediaType": media_type,
    }
    if imdb_id is not None:
        result["imdbId"] = imdb_id
    if source_type is not None:
        result["sourceType"] = source_type
    if content_kind is not None:
        result["contentKind"] = content_kind
    if broadcast_range is not None:
        result["broadcastRange"] = broadcast_range.to_dict()
    return result


@dataclass(frozen=True)
class ProposalSourceSnapshot:
    title: str
    media_type: Literal["movie", "series"]
    year: Optional[int] = None
    imdb_id: Optional[str] = None
    source_type: Optional[SourceType] = None
    content_kind: Optional[ContentKind] = None
    broadcast_range: Optional[BroadcastRange] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _normalize_proposal_title(self.title))
        object.__setattr__(self, "media_type", _normalize_proposal_media_type(self.media_type))
        _validate_proposal_year(self.year)
        object.__setattr__(self, "imdb_id", _normalize_proposal_imdb_id(self.imdb_id))
        object.__setattr__(self, "source_type", _normalize_proposal_source_type(self.source_type))
        object.__setattr__(self, "content_kind", _normalize_proposal_content_kind(self.content_kind))
        _validate_proposal_broadcast_range(self.broadcast_range)

    def to_dict(self) -> Dict[str, Any]:
        return _proposal_metadata_to_dict(
            title=self.title,
            year=self.year,
            imdb_id=self.imdb_id,
            media_type=self.media_type,
            source_type=self.source_type,
            content_kind=self.content_kind,
            broadcast_range=self.broadcast_range,
        )

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ProposalSourceSnapshot":
        if not isinstance(value, dict):
            raise ValueError("ProposalSourceSnapshot must be reconstructed from a dictionary")
        return cls(
            title=value.get("title"),
            media_type=value.get("mediaType"),
            year=value.get("year"),
            imdb_id=value.get("imdbId"),
            source_type=value.get("sourceType"),
            content_kind=value.get("contentKind"),
            broadcast_range=_proposal_broadcast_range_from_dict(value.get("broadcastRange")),
        )


@dataclass(frozen=True)
class ProposalTarget:
    title: str
    media_type: Literal["movie", "series"]
    year: Optional[int] = None
    imdb_id: Optional[str] = None
    content_kind: Optional[ContentKind] = None
    broadcast_range: Optional[BroadcastRange] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _normalize_proposal_title(self.title))
        object.__setattr__(self, "media_type", _normalize_proposal_media_type(self.media_type))
        _validate_proposal_year(self.year)
        object.__setattr__(self, "imdb_id", _normalize_proposal_imdb_id(self.imdb_id))
        object.__setattr__(self, "content_kind", _normalize_proposal_content_kind(self.content_kind))
        _validate_proposal_broadcast_range(self.broadcast_range)

    def to_dict(self) -> Dict[str, Any]:
        return _proposal_metadata_to_dict(
            title=self.title,
            year=self.year,
            imdb_id=self.imdb_id,
            media_type=self.media_type,
            content_kind=self.content_kind,
            broadcast_range=self.broadcast_range,
        )

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ProposalTarget":
        if not isinstance(value, dict):
            raise ValueError("ProposalTarget must be reconstructed from a dictionary")
        return cls(
            title=value.get("title"),
            media_type=value.get("mediaType"),
            year=value.get("year"),
            imdb_id=value.get("imdbId"),
            content_kind=value.get("contentKind"),
            broadcast_range=_proposal_broadcast_range_from_dict(value.get("broadcastRange")),
        )


@dataclass
class AuditProposal:
    id: str
    source_title_id: str
    occurrence_ids: List[str]
    raw_title_cluster: List[str]
    current_metadata: Dict[str, Any]
    proposed_metadata: Dict[str, Any]
    evidence: Dict[str, Any]
    confidence: float
    policy_version: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    status: AuditProposalStatus = "pending"
    leased_until: Optional[datetime.datetime] = None
    schema_version: int = CURRENT_AUDIT_PROPOSAL_SCHEMA_VERSION
    action_kind: AuditProposalActionKind = "review_only"
    target: Optional[ProposalTarget] = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("AuditProposal id must be a non-empty string")
        if not isinstance(self.source_title_id, str) or not self.source_title_id.strip():
            raise ValueError("AuditProposal source_title_id must be a non-empty string")
        if not isinstance(self.occurrence_ids, (list, tuple)) or not self.occurrence_ids:
            raise ValueError("AuditProposal occurrence_ids must be a non-empty list")
        if not isinstance(self.raw_title_cluster, (list, tuple)) or not self.raw_title_cluster:
            raise ValueError("AuditProposal raw_title_cluster must be a non-empty list")
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise ValueError("AuditProposal confidence must be a numeric float")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError("AuditProposal confidence must be between 0.0 and 1.0")
        if self.status not in VALID_AUDIT_PROPOSAL_STATUSES:
            raise ValueError(f"Invalid AuditProposal status '{self.status}'")
        if (
            type(self.schema_version) is not int
            or self.schema_version not in {
                LEGACY_AUDIT_PROPOSAL_SCHEMA_VERSION,
                CURRENT_AUDIT_PROPOSAL_SCHEMA_VERSION,
            }
        ):
            raise ValueError("AuditProposal schema_version must be 1 or 2")
        if not isinstance(self.action_kind, str) or self.action_kind not in VALID_AUDIT_PROPOSAL_ACTION_KINDS:
            raise ValueError("AuditProposal action_kind must be 'review_only' or 'repair'")
        if self.target is not None and not isinstance(self.target, ProposalTarget):
            raise ValueError("AuditProposal target must be a ProposalTarget")
        if self.action_kind == "repair":
            if self.schema_version != CURRENT_AUDIT_PROPOSAL_SCHEMA_VERSION:
                raise ValueError("AuditProposal repair action_kind requires schema version 2")
            if self.target is None:
                raise ValueError("AuditProposal repair requires a complete ProposalTarget")
        elif self.target is not None:
            raise ValueError("AuditProposal review_only cannot have an actionable target")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("AuditProposal policy_version must be a non-empty string")
        if not isinstance(self.created_at, datetime.datetime):
            raise ValueError("AuditProposal created_at must be a datetime")
        if not isinstance(self.updated_at, datetime.datetime):
            raise ValueError("AuditProposal updated_at must be a datetime")

        self.evidence = redact_secrets(self.evidence or {})
        self.current_metadata = redact_secrets(self.current_metadata or {})
        self.proposed_metadata = redact_secrets(self.proposed_metadata or {})

        size = measure_evidence_size_bytes(self.evidence)
        if size > MAX_AUDIT_PROPOSAL_EVIDENCE_BYTES:
            raise ValueError(
                f"AuditProposal evidence size ({size} bytes) exceeds maximum limit of "
                f"{MAX_AUDIT_PROPOSAL_EVIDENCE_BYTES} bytes (32 KiB)"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Converts the AuditProposal model to a camelCase Firestore dictionary."""
        res = {
            "id": self.id,
            "sourceTitleId": self.source_title_id,
            "occurrenceIds": list(self.occurrence_ids),
            "rawTitleCluster": list(self.raw_title_cluster),
            "currentMetadata": copy.deepcopy(self.current_metadata),
            "proposedMetadata": copy.deepcopy(self.proposed_metadata),
            "evidence": copy.deepcopy(self.evidence),
            "confidence": float(self.confidence),
            "policyVersion": self.policy_version,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "status": self.status,
            "schemaVersion": self.schema_version,
            "actionKind": self.action_kind,
        }
        if self.target is not None:
            res["target"] = self.target.to_dict()
        if self.leased_until is not None:
            res["leasedUntil"] = self.leased_until
        return res


def audit_proposal_from_dict(d: dict, doc_id: Optional[str] = None) -> AuditProposal:
    """Reconstructs an AuditProposal model from a camelCase dictionary retrieved from Firestore."""
    schema_version = d.get("schemaVersion", LEGACY_AUDIT_PROPOSAL_SCHEMA_VERSION)
    if schema_version == LEGACY_AUDIT_PROPOSAL_SCHEMA_VERSION:
        action_kind: AuditProposalActionKind = "review_only"
        target = None
    else:
        action_kind = d.get("actionKind", "review_only")
        target_value = d.get("target")
        target = None if target_value is None else ProposalTarget.from_dict(target_value)

    proposal_id = d.get("id") or doc_id or ""
    created_at = d.get("createdAt")
    if not isinstance(created_at, datetime.datetime):
        created_at = datetime.datetime.now(datetime.timezone.utc)
    updated_at = d.get("updatedAt")
    if not isinstance(updated_at, datetime.datetime):
        updated_at = datetime.datetime.now(datetime.timezone.utc)

    status = d.get("status", "pending")
    if status not in VALID_AUDIT_PROPOSAL_STATUSES:
        status = "pending"

    leased_until = d.get("leasedUntil")
    if leased_until is not None and not isinstance(leased_until, datetime.datetime):
        leased_until = None

    confidence = d.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (ValueError, TypeError):
        confidence = 0.0

    return AuditProposal(
        id=proposal_id,
        source_title_id=d.get("sourceTitleId", ""),
        occurrence_ids=list(d.get("occurrenceIds") or []),
        raw_title_cluster=list(d.get("rawTitleCluster") or []),
        current_metadata=dict(d.get("currentMetadata") or {}),
        proposed_metadata=dict(d.get("proposedMetadata") or {}),
        evidence=dict(d.get("evidence") or {}),
        confidence=confidence,
        policy_version=d.get("policyVersion", "v1"),
        created_at=created_at,
        updated_at=updated_at,
        status=status,
        leased_until=leased_until,
        schema_version=schema_version,
        action_kind=action_kind,
        target=target,
    )