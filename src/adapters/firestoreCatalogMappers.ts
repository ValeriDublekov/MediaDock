import { Occurrence, Title } from '../domain/catalog';

export type FirestoreDocumentData = Record<string, any>;

export interface RssSnapshotState {
  snapshotId: string;
  runId: string | null;
  createdAt: Date;
  itemCount: number | null;
}

export interface RssSnapshotItem {
  titleId: string;
  sourceType: string;
  groupOrder: number;
  feedOrder: number;
  entryOrder: number;
  rssPosition: number;
}

export function toDate(value: unknown): Date {
  if (!value) return new Date(0);
  if (typeof (value as { toDate?: () => Date }).toDate === 'function') {
    return (value as { toDate: () => Date }).toDate();
  }
  if (value instanceof Date) return value;
  if (typeof value === 'number' || typeof value === 'string') return new Date(value);
  return new Date(0);
}

export function mapTitleDocument(documentId: string, data: FirestoreDocumentData): Title {
  return {
    id: documentId,
    title: data.title ?? '',
    normalizedTitle: data.normalizedTitle ?? '',
    year: typeof data.year === 'number' ? data.year : null,
    mediaType: data.mediaType ?? 'movie',
    firstSeenAt: toDate(data.firstSeenAt),
    lastSeenAt: toDate(data.lastSeenAt),
    updatedAt: toDate(data.updatedAt),
    imdbId: data.imdbId ?? null,
    imdbRating: typeof data.imdbRating === 'number' ? data.imdbRating : null,
    imdbVotes: typeof data.imdbVotes === 'number' ? data.imdbVotes : null,
    metascore: typeof data.metascore === 'number' ? data.metascore : null,
    genres: Array.isArray(data.genres) ? data.genres : null,
    countries: Array.isArray(data.countries) ? data.countries : null,
    director: data.director ?? null,
    plot: data.plot ?? null,
    posterUrl: data.posterUrl ?? null,
    runtime: data.runtime ?? null,
    awards: data.awards ?? null,
    boxOffice: data.boxOffice ?? null,
    ratings: Array.isArray(data.ratings) ? data.ratings : null,
  };
}

export function mapOccurrenceDocument(
  documentId: string,
  data: FirestoreDocumentData
): Occurrence {
  return {
    id: documentId,
    sourceFeedId: data.sourceFeedId ?? '',
    sourceFeedName: data.sourceFeedName ?? '',
    feedEntryId: data.feedEntryId ?? null,
    torrentUrl: data.torrentUrl ?? '',
    rawTitle: data.rawTitle ?? '',
    quality: data.quality ?? null,
    ripType: data.ripType ?? null,
    firstSeenAt: toDate(data.firstSeenAt),
    lastSeenAt: toDate(data.lastSeenAt),
  };
}

export function mapRssSnapshotStateDocument(
  data: FirestoreDocumentData
): RssSnapshotState {
  const snapshotId = data.snapshotId;
  if (typeof snapshotId !== 'string' || !snapshotId) {
    throw new Error('RSS snapshot state is missing a snapshotId');
  }

  return {
    snapshotId,
    runId: typeof data.runId === 'string' ? data.runId : null,
    createdAt: toDate(data.createdAt),
    itemCount: typeof data.itemCount === 'number' ? data.itemCount : null,
  };
}

function requiredSnapshotNumber(data: FirestoreDocumentData, fieldName: string): number {
  const value = data[fieldName];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`RSS snapshot item is missing a numeric ${fieldName}`);
  }
  return value;
}

export function mapRssSnapshotItemDocument(
  data: FirestoreDocumentData,
  documentId?: string
): RssSnapshotItem {
  const titleId = typeof data.titleId === 'string' && data.titleId ? data.titleId : documentId;
  if (!titleId) {
    throw new Error('RSS snapshot item is missing a titleId');
  }
  if (typeof data.sourceType !== 'string' || !data.sourceType) {
    throw new Error('RSS snapshot item is missing a sourceType');
  }

  return {
    titleId,
    sourceType: data.sourceType,
    groupOrder: requiredSnapshotNumber(data, 'groupOrder'),
    feedOrder: requiredSnapshotNumber(data, 'feedOrder'),
    entryOrder: requiredSnapshotNumber(data, 'entryOrder'),
    rssPosition: requiredSnapshotNumber(data, 'rssPosition'),
  };
}
