import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from movies_feed.feed_fetcher import FeedFetcher
from movies_feed.match_policy import parse_broadcast_range
from movies_feed.metadata_resolver import MetadataResolver
from movies_feed.omdb_client import (
    OmdbClient,
    OmdbLimitReachedError,
    OmdbMovieResult,
    OmdbNoMatchError,
)
from movies_feed.proposal_application_store import ProposalApplicationStore
from movies_feed.repository import (
    AuditProposalRepository,
    FakeAuditProposalRepository,
    FakeManualMappingRepository,
    FakeOccurrenceRepository,
    FakeOmdbCacheRepository,
    FakeParseLogRepository,
    FakeScanRunRepository,
    FakeTitleRepository,
    ManualMappingRepository,
    OccurrenceRepository,
    OmdbCacheRepository,
    ParseLogRepository,
    RssSnapshotRepository,
    ScanRunRepository,
    TitleRepository,
)
from movies_feed.scanner import ScannerConfig, ScannerService


class StaticTestFeedFetcher:
    def __init__(self):
        self.validator = FeedFetcher(
            allowed_hosts={"feed.example.test"},
            dns_resolver=lambda host, port: ["8.8.8.8"],
        )

    def _resolve_path(self, target: str) -> Path:
        p = Path(target)
        if not p.exists():
            for candidate in (
                Path(__file__).parent / "fixtures" / p.name,
                Path(__file__).parent.parent / p,
                Path("backend") / p,
            ):
                if candidate.exists():
                    return candidate
        return p

    def fetch(self, url: str) -> bytes:
        if url.lstrip().startswith("<"):
            return url.encode("utf-8")
        return self._resolve_path(url).read_bytes()

    def fetch_file(self, path: str) -> bytes:
        return self._resolve_path(path).read_bytes()

    def validate_parsed_feed(self, feed: Any):
        return self.validator.validate_parsed_feed(feed)


class MockOmdbClient(OmdbClient):
    def __init__(self, responses: Dict[str, Any]):
        super().__init__(api_key="mock")
        self.responses = responses
        self.request_count = 0
        self.limit_reached_on = -1

    def get_movie_info(self, title: str, year: str = None, media_type: str = None) -> OmdbMovieResult:
        self.request_count += 1
        if self.limit_reached_on > 0 and self.request_count >= self.limit_reached_on:
            raise OmdbLimitReachedError("limit reached")
        
        for k, v in self.responses.items():
            if k.lower() in title.lower():
                if isinstance(v, Exception):
                    raise v
                return v
        
        raise OmdbNoMatchError("Not found")

    def get_by_imdb_id(self, imdb_id: str) -> OmdbMovieResult:
        self.request_count += 1
        for k, v in self.responses.items():
            if k.lower() == imdb_id.lower():
                if isinstance(v, Exception):
                    raise v
                return v
        raise OmdbNoMatchError(f"IMDb ID {imdb_id} not found")

    def _normalize_payload(self, payload: Dict[str, Any]) -> OmdbMovieResult:
        return OmdbMovieResult(
            title=payload.get("Title", ""),
            year=int(payload.get("Year")) if payload.get("Year") else None,
            imdb_id=payload.get("imdbID"),
            media_type="movie",
            rating=None, votes=None, metascore=None,
            genres=payload.get("Genre", "").split(", "),
            countries=payload.get("Country", "").split(", "),
            director=None, plot=None, poster_url=None,
            runtime=None, awards=None, box_office=None, ratings=[], raw_payload=payload
        )


class ScannerTestBuilder:
    def __init__(
        self,
        *,
        config: Optional[ScannerConfig] = None,
        omdb_client: Optional[OmdbClient] = None,
        now: Optional[datetime.datetime] = None,
        metadata_resolver: Optional[MetadataResolver] = None,
        feed_fetcher: Optional[FeedFetcher] = None,
        title_repo: Optional[TitleRepository] = None,
        occurrence_repo: Optional[OccurrenceRepository] = None,
        cache_repo: Optional[OmdbCacheRepository] = None,
        run_repo: Optional[ScanRunRepository] = None,
        parse_log_repo: Optional[ParseLogRepository] = None,
        manual_mapping_repo: Optional[ManualMappingRepository] = None,
        audit_proposal_repo: Optional[AuditProposalRepository] = None,
        ai_matcher: Any = None,
        application_store: Optional[ProposalApplicationStore] = None,
        rss_snapshot_repo: Optional[RssSnapshotRepository] = None,
    ) -> None:
        self.config = config
        self.omdb_client = omdb_client
        self.now = now
        self.metadata_resolver = metadata_resolver
        self.feed_fetcher = feed_fetcher
        self.title_repo = title_repo
        self.occurrence_repo = occurrence_repo
        self.cache_repo = cache_repo
        self.run_repo = run_repo
        self.parse_log_repo = parse_log_repo
        self.manual_mapping_repo = manual_mapping_repo
        self.audit_proposal_repo = audit_proposal_repo
        self.ai_matcher = ai_matcher
        self.application_store = application_store
        self.rss_snapshot_repo = rss_snapshot_repo

    def build(
        self,
        *,
        config: Optional[ScannerConfig] = None,
        omdb_client: Optional[OmdbClient] = None,
        now: Optional[datetime.datetime] = None,
        metadata_resolver: Optional[MetadataResolver] = None,
        feed_fetcher: Optional[FeedFetcher] = None,
        title_repo: Optional[TitleRepository] = None,
        occurrence_repo: Optional[OccurrenceRepository] = None,
        cache_repo: Optional[OmdbCacheRepository] = None,
        run_repo: Optional[ScanRunRepository] = None,
        parse_log_repo: Optional[ParseLogRepository] = None,
        manual_mapping_repo: Optional[ManualMappingRepository] = None,
        audit_proposal_repo: Optional[AuditProposalRepository] = None,
        ai_matcher: Any = None,
        application_store: Optional[ProposalApplicationStore] = None,
        rss_snapshot_repo: Optional[RssSnapshotRepository] = None,
    ) -> ScannerService:
        return ScannerService(
            config=config or self.config or ScannerConfig(),
            omdb_client=omdb_client or self.omdb_client or MockOmdbClient({}),
            title_repo=title_repo or self.title_repo or FakeTitleRepository(),
            occurrence_repo=(
                occurrence_repo
                or self.occurrence_repo
                or FakeOccurrenceRepository()
            ),
            cache_repo=cache_repo or self.cache_repo or FakeOmdbCacheRepository(),
            run_repo=run_repo or self.run_repo or FakeScanRunRepository(),
            parse_log_repo=(
                parse_log_repo
                or self.parse_log_repo
                or FakeParseLogRepository()
            ),
            manual_mapping_repo=(
                manual_mapping_repo
                or self.manual_mapping_repo
                or FakeManualMappingRepository()
            ),
            audit_proposal_repo=(
                audit_proposal_repo
                or self.audit_proposal_repo
                or FakeAuditProposalRepository()
            ),
            ai_matcher=ai_matcher if ai_matcher is not None else self.ai_matcher,
            now=now if now is not None else self.now,
            feed_fetcher=(
                feed_fetcher
                or self.feed_fetcher
                or StaticTestFeedFetcher()
            ),
            metadata_resolver=(
                metadata_resolver
                if metadata_resolver is not None
                else self.metadata_resolver
            ),
            application_store=(
                application_store
                if application_store is not None
                else self.application_store
            ),
            rss_snapshot_repo=(
                rss_snapshot_repo
                if rss_snapshot_repo is not None
                else self.rss_snapshot_repo
            ),
        )


def make_series_result(
    title: str = "Seasoned Show",
    year: int = 2007,
    broadcast_year: str = "2007-2015",
    genres=None,
) -> OmdbMovieResult:
    genres = genres or ["Drama"]
    content_kind = "documentary" if "Documentary" in genres else "standard"
    return OmdbMovieResult(
        title=title,
        year=year,
        imdb_id="tt0804497",
        media_type="series",
        rating=8.0,
        votes=1000,
        metascore=None,
        genres=genres,
        countries=["USA"],
        director=None,
        plot="A series",
        poster_url=None,
        runtime=None,
        awards=None,
        box_office=None,
        ratings=[],
        raw_payload={
            "Response": "True",
            "Title": title,
            "Year": broadcast_year,
            "imdbID": "tt0804497",
            "Type": "series",
            "Genre": ", ".join(genres),
            "Country": "USA",
        },
        source_type="series",
        content_kind=content_kind,
        broadcast_range=parse_broadcast_range(broadcast_year),
    )


def make_inline_feed(raw_title: str, published_at: str = "") -> str:
    publication = f"<pubDate>{published_at}</pubDate>" if published_at else ""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>{raw_title}</title>
                    <link>https://example.com/torrent/series-1</link>
                    <guid>series-guid-1</guid>
                    {publication}
                </item>
            </channel>
        </rss>'''


def make_multi_entry_feed(entries) -> str:
    items = "".join(
        f'''<item>
                <title>{title}</title>
                <link>https://example.com/torrent/{guid}</link>
                <guid>{guid}</guid>
            </item>'''
        for guid, title in entries
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>{items}</channel></rss>'''