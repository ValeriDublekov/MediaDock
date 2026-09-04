from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional


@dataclass(frozen=True)
class FeedDefinition:
    id: str
    name: str
    url: Optional[str]
    type: Optional[str]

    def require_url(self) -> str:
        if self.url is None:
            raise ValueError("configured feed URL is missing")
        return self.url


@dataclass(frozen=True)
class ScanPhaseOutcome:
    status: str = "skipped"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: float = 0.0
    counters: Mapping[str, Any] = field(default_factory=dict)
    errors: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
        }
        result.update(dict(self.counters))
        if self.errors is not None:
            result["errors"] = self.errors
        return result