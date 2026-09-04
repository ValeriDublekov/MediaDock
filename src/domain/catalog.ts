export type MediaType = 'movie' | 'series' | 'documentary' | 'short' | string;

export interface Rating {
  source: string;
  value: string;
}

export interface Title {
  id: string;
  title: string;
  normalizedTitle: string;
  year: number | null;
  mediaType: MediaType;
  firstSeenAt: Date;
  lastSeenAt: Date;
  updatedAt: Date;
  imdbId?: string | null;
  imdbRating?: number | null;
  imdbVotes?: number | null;
  metascore?: number | null;
  genres?: string[] | null;
  countries?: string[] | null;
  director?: string | null;
  plot?: string | null;
  posterUrl?: string | null;
  runtime?: string | null;
  awards?: string | null;
  boxOffice?: string | null;
  ratings?: Rating[] | null;
  qualities?: string[] | null;
  occurrences?: Occurrence[] | null;
}

export interface Occurrence {
  id: string;
  sourceFeedId: string;
  sourceFeedName: string;
  feedEntryId: string | null;
  torrentUrl: string;
  rawTitle: string;
  quality: string | null;
  ripType: string | null;
  firstSeenAt: Date;
  lastSeenAt: Date;
}

export interface CatalogCursor {
  lastSeenAt: Date;
  id: string;
}

export interface LatestRssSnapshotCursor {
  snapshotId: string;
  rssPosition: number;
  titleId: string;
}

export type RssSourceType = 'movie' | 'series';

export interface LatestRssSnapshotPage {
  items: Title[];
  nextCursor: LatestRssSnapshotCursor | null;
  hasMore: boolean;
  snapshotId: string | null;
}

export interface CatalogPageOptions {
  pageSize: number;
  cursor?: CatalogCursor | null;
}

export interface CatalogPage {
  items: Title[];
  nextCursor: CatalogCursor | null;
  hasMore: boolean;
}

export interface CatalogRepository {
  getCatalogPage(options: CatalogPageOptions): Promise<CatalogPage>;
  getLatestRssSnapshotPage?(options: {
    pageSize: number;
    sourceType: RssSourceType;
    cursor?: LatestRssSnapshotCursor | null;
  }): Promise<LatestRssSnapshotPage>;
  getTitleById(id: string): Promise<Title | null>;
  getTitlesByIds?(ids: string[]): Promise<Title[]>;
  getOccurrences(titleId: string): Promise<Occurrence[]>;
}
