import {
  collection,
  doc,
  getDoc,
  getDocs,
  query,
  orderBy,
  limit,
  startAfter,
  documentId,
  Timestamp,
  Firestore,
  DocumentData,
  QueryDocumentSnapshot,
  QueryConstraint,
  where,
} from 'firebase/firestore';
import { getDb } from './firebaseApp';
import {
  CatalogRepository,
  CatalogPageOptions,
  CatalogPage,
  CatalogCursor,
  LatestRssSnapshotCursor,
  LatestRssSnapshotPage,
  Title,
  Occurrence,
} from '../domain/catalog';

function toDate(val: unknown): Date {
  if (!val) return new Date(0);
  if (typeof (val as { toDate?: () => Date }).toDate === 'function') {
    return (val as { toDate: () => Date }).toDate();
  }
  if (val instanceof Date) return val;
  if (typeof val === 'number' || typeof val === 'string') return new Date(val);
  return new Date(0);
}

function mapDocToTitle(docSnap: QueryDocumentSnapshot<DocumentData>): Title {
  const data = docSnap.data();
  return {
    id: docSnap.id,
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

function mapDocToOccurrence(docSnap: QueryDocumentSnapshot<DocumentData>): Occurrence {
  const data = docSnap.data();
  return {
    id: docSnap.id,
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

export class FirestoreCatalogAdapter implements CatalogRepository {
  constructor(private getDbInstance: () => Firestore = getDb) {}

  async getLatestRssSnapshotPage(options: {
    pageSize: number;
    cursor?: LatestRssSnapshotCursor | null;
  }): Promise<LatestRssSnapshotPage> {
    const db = this.getDbInstance();
    const cursor = options.cursor ?? null;
    const snapshotId = cursor?.snapshotId ?? await this.getCurrentSnapshotId(db);

    if (!snapshotId) {
      return {
        items: [],
        nextCursor: null,
        hasMore: false,
        snapshotId: null,
      };
    }

    const itemsRef = collection(db, 'rssSnapshots', snapshotId, 'items');
    const constraints: QueryConstraint[] = [orderBy('rssPosition', 'asc')];
    if (cursor) {
      constraints.push(startAfter(cursor.rssPosition));
    }
    constraints.push(limit(options.pageSize + 1));

    const snapshot = await getDocs(query(itemsRef, ...constraints));
    const hasMore = snapshot.docs.length > options.pageSize;
    const pageDocs = hasMore ? snapshot.docs.slice(0, options.pageSize) : snapshot.docs;
    const titleIds = pageDocs.map((itemDoc) => {
      const data = itemDoc.data() as DocumentData;
      return typeof data.titleId === 'string' && data.titleId ? data.titleId : itemDoc.id;
    });
    const hydratedTitles = titleIds.length > 0 ? await this.getTitlesByIds(titleIds) : [];
    const titlesById = new Map(hydratedTitles.map((title) => [title.id, title]));
    const items = titleIds
      .map((titleId) => titlesById.get(titleId))
      .filter((title): title is Title => title !== undefined);

    let nextCursor: LatestRssSnapshotCursor | null = null;
    const lastDoc = pageDocs[pageDocs.length - 1];
    if (lastDoc && hasMore) {
      const lastData = lastDoc.data() as DocumentData;
      const rssPosition = lastData.rssPosition;
      if (typeof rssPosition !== 'number') {
        throw new Error('RSS snapshot item is missing a numeric rssPosition');
      }
      nextCursor = {
        snapshotId,
        rssPosition,
        titleId: typeof lastData.titleId === 'string' ? lastData.titleId : lastDoc.id,
      };
    }

    return {
      items,
      nextCursor,
      hasMore,
      snapshotId,
    };
  }

  private async getCurrentSnapshotId(db: Firestore): Promise<string | null> {
    const stateSnapshot = await getDoc(doc(db, 'rssSnapshotState', 'current'));
    if (!stateSnapshot.exists()) return null;
    const snapshotId = stateSnapshot.data().snapshotId;
    return typeof snapshotId === 'string' && snapshotId ? snapshotId : null;
  }

  async getCatalogPage(options: CatalogPageOptions): Promise<CatalogPage> {
    const db = this.getDbInstance();
    const titlesRef = collection(db, 'titles');

    const q = options.cursor
      ? query(
          titlesRef,
          orderBy('lastSeenAt', 'desc'),
          orderBy(documentId(), 'desc'),
          startAfter(
            Timestamp.fromDate(options.cursor.lastSeenAt),
            options.cursor.id
          ),
          limit(options.pageSize)
        )
      : query(
          titlesRef,
          orderBy('lastSeenAt', 'desc'),
          orderBy(documentId(), 'desc'),
          limit(options.pageSize)
        );
    const snapshot = await getDocs(q);
    const items = snapshot.docs.map(mapDocToTitle);
    const hasMore = snapshot.docs.length === options.pageSize;
    const lastDoc = snapshot.docs[snapshot.docs.length - 1];
    let nextCursor: CatalogCursor | null = null;
    if (lastDoc && hasMore) {
      const lastData = lastDoc.data() as DocumentData;
      nextCursor = {
        lastSeenAt: toDate(lastData['lastSeenAt']),
        id: lastDoc.id,
      };
    }

    return {
      items,
      nextCursor,
      hasMore,
    };
  }

  async getTitleById(id: string): Promise<Title | null> {
    const db = this.getDbInstance();
    const docRef = doc(db, 'titles', id);
    const docSnap = await getDoc(docRef);

    if (!docSnap.exists()) {
      return null;
    }

    return mapDocToTitle(docSnap as QueryDocumentSnapshot<DocumentData>);
  }

  async getTitlesByIds(ids: string[]): Promise<Title[]> {
    if (!ids || ids.length === 0) return [];
    const db = this.getDbInstance();
    const titlesRef = collection(db, 'titles');
    const uniqueIds = Array.from(new Set(ids));
    const results: Title[] = [];

    // Chunk into batches of 30 for documentId() in [...]
    const chunkSize = 30;
    for (let i = 0; i < uniqueIds.length; i += chunkSize) {
      const chunk = uniqueIds.slice(i, i + chunkSize);
      const q = query(titlesRef, where(documentId(), 'in', chunk));
      const snapshot = await getDocs(q);
      snapshot.docs.forEach((docSnap) => {
        results.push(mapDocToTitle(docSnap));
      });
    }

    return results;
  }

  async getOccurrences(titleId: string): Promise<Occurrence[]> {
    const db = this.getDbInstance();
    const occurrencesRef = collection(db, 'titles', titleId, 'occurrences');
    const q = query(occurrencesRef, orderBy('firstSeenAt', 'desc'));
    const snapshot = await getDocs(q);

    return snapshot.docs.map(mapDocToOccurrence);
  }
}

export const firestoreCatalogAdapter = new FirestoreCatalogAdapter();
