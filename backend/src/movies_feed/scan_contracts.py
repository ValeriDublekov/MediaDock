from dataclasses import dataclass
from typing import Optional


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