import datetime
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Optional, Sequence, Tuple

from .audit_proposal import AuditProposal, ProposalTarget
from .models import Title, Occurrence
from .proposal_application_store import (
    FakeProposalApplicationStore,
    ProposalApplicationStore,
    RepositoryProposalApplicationStore,
)
from .repository import (
    AuditProposalRepository,
    OccurrenceRepository,
    TitleRepository,
)
from .ids import get_title_id_v2
from .match_policy import BroadcastRange

CURRENT_APPLICATION_POLICY_VERSION = "v1"
MAX_APPLICATION_OCCURRENCES = 200

ApplicationOutcome = Literal[
    "planned",
    "applied",
    "skipped",
    "failed",
    "ineligible",
    "stale",
]
ApplicationPlanningOutcome = Literal[
    "ready",
    "ineligible",
    "stale",
    "same_source_target",
]

_SOURCE_TITLE_FINGERPRINT_FIELDS = (
    "title",
    "normalizedTitle",
    "year",
    "imdbId",
    "mediaType",
    "sourceType",
    "contentKind",
    "broadcastRange",
)
_OCCURRENCE_FINGERPRINT_FIELDS = (
    "sourceFeedId",
    "feedEntryId",
    "torrentUrl",
    "rawTitle",
    "quality",
    "ripType",
    "feedType",
    "sourcePublishedAt",
)


@dataclass(frozen=True)
class ApplicationSourceTitleFingerprint:
    title: str
    normalized_title: str
    year: Optional[int]
    imdb_id: Optional[str]
    media_type: str
    source_type: Optional[str]
    content_kind: Optional[str]
    broadcast_range: Optional[BroadcastRange]

    @classmethod
    def from_title(cls, title: Title) -> "ApplicationSourceTitleFingerprint":
        return cls(
            title=title.title,
            normalized_title=title.normalized_title,
            year=title.year,
            imdb_id=title.imdb_id,
            media_type=title.media_type,
            source_type=title.source_type,
            content_kind=title.content_kind,
            broadcast_range=title.broadcast_range,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "normalizedTitle": self.normalized_title,
            "year": self.year,
            "imdbId": self.imdb_id,
            "mediaType": self.media_type,
            "sourceType": self.source_type,
            "contentKind": self.content_kind,
            "broadcastRange": (
                self.broadcast_range.to_dict()
                if self.broadcast_range is not None
                else None
            ),
        }


@dataclass(frozen=True)
class ApplicationOccurrenceFingerprint:
    source_feed_id: Optional[str]
    feed_entry_id: Optional[str]
    torrent_url: Optional[str]
    raw_title: Optional[str]
    quality: Optional[str]
    rip_type: Optional[str]
    feed_type: Optional[str]
    source_published_at: Optional[datetime.datetime]

    @classmethod
    def from_occurrence(cls, occurrence: Occurrence) -> "ApplicationOccurrenceFingerprint":
        source_context = occurrence.source_context
        return cls(
            source_feed_id=occurrence.source_feed_id,
            feed_entry_id=occurrence.feed_entry_id,
            torrent_url=occurrence.torrent_url,
            raw_title=occurrence.raw_title,
            quality=occurrence.quality,
            rip_type=occurrence.rip_type,
            feed_type=source_context.feed_type if source_context is not None else None,
            source_published_at=(
                source_context.source_published_at
                if source_context is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceFeedId": self.source_feed_id,
            "feedEntryId": self.feed_entry_id,
            "torrentUrl": self.torrent_url,
            "rawTitle": self.raw_title,
            "quality": self.quality,
            "ripType": self.rip_type,
            "feedType": self.feed_type,
            "sourcePublishedAt": self.source_published_at,
        }


@dataclass(frozen=True)
class ApplicationCurrentSnapshot:
    source_title: Optional[Title]
    source_occurrences: Mapping[str, Optional[Occurrence]]
    source_occurrence_count: Optional[int] = None


@dataclass(frozen=True)
class ApplicationPlan:
    proposal_id: str
    source_title_id: str
    target_title_id: str
    target: ProposalTarget
    occurrence_ids: Tuple[str, ...]
    source_title_fingerprint: Tuple[Tuple[str, Any], ...]
    occurrence_fingerprints: Tuple[
        Tuple[str, Tuple[Tuple[str, Any], ...]], ...
    ]
    source_occurrence_count: int
    source_deleted: bool

    @property
    def occurrences_moved(self) -> int:
        if self.source_title_id == self.target_title_id:
            return 0
        return len(self.occurrence_ids)


@dataclass(frozen=True)
class ApplicationPlanningResult:
    outcome: ApplicationPlanningOutcome
    reason_code: str
    reason: str
    plan: Optional[ApplicationPlan] = None


def _as_mapping(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return None


def _freeze_value(value: Any) -> Any:
    if isinstance(value, BroadcastRange):
        return (
            value.start_year,
            value.end_year,
            value.raw,
        )
    if isinstance(value, Mapping):
        return tuple(
            (key, _freeze_value(item))
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _canonical_broadcast_range(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, BroadcastRange):
        return value.to_dict()
    value_map = _as_mapping(value)
    if value_map is None or set(value_map) != {"startYear", "endYear", "raw"}:
        raise ValueError("broadcastRange must be complete")
    return value_map


def _canonical_source_fingerprint_from_title(title: Title) -> dict[str, Any]:
    return ApplicationSourceTitleFingerprint.from_title(title).to_dict()


def _canonical_occurrence_fingerprint_from_occurrence(
    occurrence: Occurrence,
) -> dict[str, Any]:
    return ApplicationOccurrenceFingerprint.from_occurrence(occurrence).to_dict()


def _proposal_source_fingerprint(proposal: AuditProposal) -> Any:
    for attribute_name in ("source_title_fingerprint", "sourceTitleFingerprint"):
        value = getattr(proposal, attribute_name, None)
        if value is not None:
            return value

    current_metadata = getattr(proposal, "current_metadata", None)
    current_metadata_map = _as_mapping(current_metadata)
    if current_metadata_map is not None:
        nested = current_metadata_map.get("sourceTitleFingerprint")
        if nested is not None:
            return nested
        if set(current_metadata_map) == set(_SOURCE_TITLE_FINGERPRINT_FIELDS):
            return current_metadata_map
    return None


def _proposal_occurrence_fingerprints(proposal: AuditProposal) -> Any:
    for attribute_name in ("occurrence_fingerprints", "occurrenceFingerprints"):
        value = getattr(proposal, attribute_name, None)
        if value is not None:
            return value
    return None


def _validated_fingerprint(
    value: Any,
    expected_fields: Sequence[str],
) -> Optional[dict[str, Any]]:
    value_map = _as_mapping(value)
    if value_map is None or set(value_map) != set(expected_fields):
        return None
    if "broadcastRange" in value_map:
        try:
            value_map["broadcastRange"] = _canonical_broadcast_range(
                value_map["broadcastRange"]
            )
        except ValueError:
            return None
    return value_map


def _frozen_mapping(value: Mapping[str, Any]) -> Tuple[Tuple[str, Any], ...]:
    return tuple(
        (key, _freeze_value(value[key]))
        for key in sorted(value)
    )


class ApplicationPlanner:
    def __init__(
        self,
        current_policy_version: str = CURRENT_APPLICATION_POLICY_VERSION,
    ) -> None:
        self.current_policy_version = current_policy_version

    def plan(
        self,
        proposal: AuditProposal,
        source_title_or_snapshot: Optional[Title | ApplicationCurrentSnapshot],
        source_occurrences: Optional[Mapping[str, Optional[Occurrence]]] = None,
        source_occurrence_count: Optional[int] = None,
    ) -> ApplicationPlanningResult:
        if isinstance(source_title_or_snapshot, ApplicationCurrentSnapshot):
            snapshot = source_title_or_snapshot
            source_title = snapshot.source_title
            source_occurrences = snapshot.source_occurrences
            source_occurrence_count = snapshot.source_occurrence_count
        else:
            source_title = source_title_or_snapshot

        if proposal.schema_version != 2:
            return self._ineligible("schema_version", "Proposal schema version must be 2")
        if proposal.action_kind != "repair":
            return self._ineligible("action_kind", "Proposal action kind must be repair")
        if proposal.policy_version != self.current_policy_version:
            return self._ineligible(
                "policy_version_mismatch",
                "Proposal policy version does not match the current application policy",
            )

        target = proposal.target
        if not isinstance(target, ProposalTarget):
            return self._ineligible("incomplete_target", "Proposal target is incomplete")

        occurrence_ids = tuple(proposal.occurrence_ids)
        if (
            not occurrence_ids
            or any(not isinstance(occurrence_id, str) or not occurrence_id for occurrence_id in occurrence_ids)
            or len(set(occurrence_ids)) != len(occurrence_ids)
            or len(occurrence_ids) > MAX_APPLICATION_OCCURRENCES
        ):
            reason_code = (
                "occurrence_limit"
                if len(occurrence_ids) > MAX_APPLICATION_OCCURRENCES
                else "occurrence_ids"
            )
            return self._ineligible(reason_code, "Proposal occurrence membership is invalid")

        source_fingerprint = _validated_fingerprint(
            _proposal_source_fingerprint(proposal),
            _SOURCE_TITLE_FINGERPRINT_FIELDS,
        )
        if source_fingerprint is None:
            return self._ineligible(
                "missing_source_fingerprint",
                "Proposal source title fingerprint is missing or incomplete",
            )

        occurrence_fingerprints_value = _proposal_occurrence_fingerprints(proposal)
        if not isinstance(occurrence_fingerprints_value, Mapping):
            return self._ineligible(
                "missing_occurrence_fingerprints",
                "Proposal occurrence fingerprints are missing or incomplete",
            )
        if set(occurrence_fingerprints_value) != set(occurrence_ids):
            return self._ineligible(
                "occurrence_fingerprint_membership",
                "Proposal occurrence fingerprints do not match occurrenceIds",
            )

        validated_occurrence_fingerprints: dict[str, dict[str, Any]] = {}
        for occurrence_id in occurrence_ids:
            fingerprint = _validated_fingerprint(
                occurrence_fingerprints_value[occurrence_id],
                _OCCURRENCE_FINGERPRINT_FIELDS,
            )
            if fingerprint is None:
                return self._ineligible(
                    "missing_occurrence_fingerprint",
                    f"Occurrence fingerprint for {occurrence_id} is missing or incomplete",
                )
            validated_occurrence_fingerprints[occurrence_id] = fingerprint

        if source_title is None:
            return self._stale("source_title_missing", "Source title no longer exists")

        current_source_fingerprint = _canonical_source_fingerprint_from_title(source_title)
        if _freeze_value(source_fingerprint) != _freeze_value(current_source_fingerprint):
            return self._stale("source_title_changed", "Source title fingerprint is stale")

        current_occurrences = source_occurrences or {}
        for occurrence_id in occurrence_ids:
            occurrence = current_occurrences.get(occurrence_id)
            if occurrence is None:
                return self._stale(
                    "occurrence_missing",
                    f"Occurrence {occurrence_id} is missing from the source title",
                )
            current_fingerprint = _canonical_occurrence_fingerprint_from_occurrence(occurrence)
            if _freeze_value(validated_occurrence_fingerprints[occurrence_id]) != _freeze_value(
                current_fingerprint
            ):
                return self._stale(
                    "occurrence_changed",
                    f"Occurrence {occurrence_id} fingerprint is stale",
                )

        if source_occurrence_count is None:
            source_occurrence_count = len(current_occurrences)
        if source_occurrence_count < len(occurrence_ids):
            return self._stale(
                "occurrence_membership_changed",
                "Source occurrence membership is stale",
            )

        target_title_id = get_title_id_v2(
            target.imdb_id,
            target.title,
            target.year,
            target.media_type,
        )
        same_source_target = target_title_id == proposal.source_title_id
        source_deleted = (
            not same_source_target
            and source_occurrence_count == len(occurrence_ids)
        )
        plan = ApplicationPlan(
            proposal_id=proposal.id,
            source_title_id=proposal.source_title_id,
            target_title_id=target_title_id,
            target=target,
            occurrence_ids=occurrence_ids,
            source_title_fingerprint=_frozen_mapping(source_fingerprint),
            occurrence_fingerprints=tuple(
                (
                    occurrence_id,
                    _frozen_mapping(validated_occurrence_fingerprints[occurrence_id]),
                )
                for occurrence_id in occurrence_ids
            ),
            source_occurrence_count=source_occurrence_count,
            source_deleted=source_deleted,
        )
        if same_source_target:
            return ApplicationPlanningResult(
                "same_source_target",
                "same_source_target",
                "Canonical target is the source title",
                plan,
            )
        return ApplicationPlanningResult("ready", "ready", "Application plan is ready", plan)

    @staticmethod
    def _ineligible(reason_code: str, reason: str) -> ApplicationPlanningResult:
        return ApplicationPlanningResult("ineligible", reason_code, reason)

    @staticmethod
    def _stale(reason_code: str, reason: str) -> ApplicationPlanningResult:
        return ApplicationPlanningResult("stale", reason_code, reason)

@dataclass
class ProposalApplicationResult:
    proposal_id: str
    outcome: ApplicationOutcome
    reason: str
    target_title_id: Optional[str] = None
    occurrences_moved: int = 0
    source_deleted: bool = False
    plan: Optional[ApplicationPlan] = None
    reason_code: Optional[str] = None

class ProposalApplicationService:
    def __init__(
        self,
        proposal_repo: Optional[AuditProposalRepository] = None,
        title_repo: Optional[TitleRepository] = None,
        occurrence_repo: Optional[OccurrenceRepository] = None,
        clock: Optional[Callable[[], datetime.datetime]] = None,
        now: Optional[datetime.datetime] = None,
        store: Optional[ProposalApplicationStore] = None,
    ) -> None:
        if store is not None:
            if proposal_repo is not None or title_repo is not None or occurrence_repo is not None:
                raise ValueError("Provide either store or the legacy repository arguments, not both")
            self.store = store
        else:
            if proposal_repo is None or title_repo is None or occurrence_repo is None:
                raise ValueError("Proposal application requires a store or all legacy repositories")
            self.store = RepositoryProposalApplicationStore(
                proposal_repo,
                title_repo,
                occurrence_repo,
            )
        if clock is not None:
            self.clock = clock
        elif now is not None:
            self.clock = lambda: now
        else:
            self.clock = lambda: datetime.datetime.now(datetime.timezone.utc)
        self.planner = ApplicationPlanner()

    def _mark_state(self, proposal: AuditProposal, status: str) -> None:
        proposal.status = status # type: ignore
        if status in ("applied", "failed", "rejected", "pending"):
            proposal.leased_until = None
        proposal.updated_at = self.clock()
        self.store.save_proposal(proposal)

    def plan_proposal(self, proposal_id: str) -> ApplicationPlanningResult:
        proposal = self.store.get_proposal(proposal_id)
        if proposal is None:
            return ApplicationPlanningResult(
                "ineligible",
                "proposal_not_found",
                f"Proposal {proposal_id} not found",
            )

        source_title = self.store.get_title(proposal.source_title_id)
        named_occurrences = {
            occurrence_id: self.store.get_occurrence(
                proposal.source_title_id,
                occurrence_id,
            )
            for occurrence_id in proposal.occurrence_ids
        }
        source_occurrence_count = (
            len(self.store.list_occurrences(proposal.source_title_id))
            if source_title is not None
            else 0
        )
        return self.planner.plan(
            proposal,
            ApplicationCurrentSnapshot(
                source_title=source_title,
                source_occurrences=named_occurrences,
                source_occurrence_count=source_occurrence_count,
            ),
        )

    def apply_proposal(self, proposal_id: str, dry_run: bool = False, reject: bool = False) -> ProposalApplicationResult:
        proposal = self.store.get_proposal(proposal_id)
        if not proposal:
            return ProposalApplicationResult(proposal_id, "failed", f"Proposal {proposal_id} not found")

        if reject:
            if proposal.status in ("applied", "failed", "rejected"):
                return ProposalApplicationResult(proposal_id, "skipped", f"Cannot reject proposal in terminal state '{proposal.status}'")
            if not dry_run:
                self._mark_state(proposal, "rejected")
            outcome: ApplicationOutcome = "planned" if dry_run else "applied"
            return ProposalApplicationResult(proposal_id, outcome, "Confirmed rejection")

        if proposal.status == "applied":
            return ProposalApplicationResult(proposal_id, "skipped", "Proposal already applied")
        if proposal.status == "failed":
            return ProposalApplicationResult(proposal_id, "failed", "Proposal is in failed state")
        if proposal.status == "rejected":
            return ProposalApplicationResult(proposal_id, "skipped", "Proposal was rejected")
        if proposal.status == "pending":
            return ProposalApplicationResult(proposal_id, "failed", "Proposal must be approved before application")

        planning = self.plan_proposal(proposal_id)
        if planning.outcome in ("ineligible", "stale"):
            return ProposalApplicationResult(
                proposal_id,
                planning.outcome,
                planning.reason,
                reason_code=planning.reason_code,
            )
        if planning.plan is None:
            return ProposalApplicationResult(
                proposal_id,
                "failed",
                "Application planner returned no plan",
                reason_code="planner_missing_plan",
            )

        plan = planning.plan
        if dry_run:
            outcome: ApplicationOutcome = "planned" if planning.outcome == "ready" else "skipped"
            return ProposalApplicationResult(
                proposal_id,
                outcome,
                "Planned application" if planning.outcome == "ready" else planning.reason,
                target_title_id=plan.target_title_id,
                occurrences_moved=plan.occurrences_moved,
                source_deleted=plan.source_deleted,
                plan=plan,
                reason_code=planning.reason_code,
            )

        lease = self.store.acquire_lease(
            proposal_id,
            datetime.timedelta(minutes=5),
            self.clock(),
        )
        if not lease.acquired or lease.lease_owner is None:
            outcome: ApplicationOutcome = (
                "failed" if lease.reason_code == "lease_expired" else "skipped"
            )
            reason = (
                "Proposal lease was stale and recovered to failed"
                if lease.reason_code == "lease_expired"
                else "Could not acquire lease (concurrent application or unrecovered stale state)"
            )
            return ProposalApplicationResult(
                proposal_id,
                outcome,
                reason,
                target_title_id=plan.target_title_id,
                plan=plan,
                reason_code=lease.reason_code,
            )

        committed = self.store.commit_application(plan, lease.lease_owner, self.clock())
        outcome = (
            "skipped"
            if planning.outcome == "same_source_target" and committed.outcome == "applied"
            else committed.outcome
        )
        if outcome not in ("applied", "skipped", "failed", "ineligible", "stale"):
            outcome = "failed"
        return ProposalApplicationResult(
            proposal_id,
            outcome,
            "Same source and target" if outcome == "skipped" else committed.reason,
            target_title_id=committed.target_title_id or plan.target_title_id,
            occurrences_moved=committed.occurrences_moved,
            source_deleted=committed.source_deleted,
            plan=plan,
            reason_code=committed.reason_code,
        )
