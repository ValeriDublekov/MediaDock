from typing import Dict, List

from .models import RssSnapshotItem


class RssSnapshotCollector:
    def __init__(self) -> None:
        self._candidates: Dict[str, RssSnapshotItem] = {}

    def record_candidate(
        self,
        title_id: str,
        source_type: str,
        feed_order: int,
        entry_order: int,
    ) -> None:
        if source_type not in ("movie", "series"):
            return
        candidate = RssSnapshotItem(
            title_id=title_id,
            source_type=source_type,
            group_order=0 if source_type == "movie" else 1,
            feed_order=feed_order,
            entry_order=entry_order,
            rss_position=-1,
        )
        existing = self._candidates.get(title_id)
        if existing is None or (
            candidate.group_order,
            candidate.feed_order,
            candidate.entry_order,
        ) < (
            existing.group_order,
            existing.feed_order,
            existing.entry_order,
        ):
            self._candidates[title_id] = candidate

    def build_items(self) -> List[RssSnapshotItem]:
        ordered_candidates = sorted(
            self._candidates.values(),
            key=lambda item: (
                item.group_order,
                item.feed_order,
                item.entry_order,
                item.title_id,
            ),
        )
        return [
            RssSnapshotItem(
                title_id=item.title_id,
                source_type=item.source_type,
                group_order=item.group_order,
                feed_order=item.feed_order,
                entry_order=item.entry_order,
                rss_position=position,
            )
            for position, item in enumerate(ordered_candidates)
        ]