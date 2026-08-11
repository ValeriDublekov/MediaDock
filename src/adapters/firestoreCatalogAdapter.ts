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
  where,
} from 'firebase/firestore';
import { getDb } from './firebaseApp';
import {
  CatalogRepository,
  CatalogPageOptions,
  CatalogPage,
  CatalogCursor,
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

  async getCatalogPage(options: CatalogPageOptions): Promise<CatalogPage> {
    const db = this.getDbInstance();
    const titlesRef = collection(db, 'titles');

    let items: Title[] = [];
    let hasMore = false;
    let nextCursor: CatalogCursor | null = null;

    if (!options.cursor) {
      // Load all titles with lastSeenAt in the last 5 days
      const fiveDaysAgo = new Date();
      fiveDaysAgo.setDate(fiveDaysAgo.getDate() - 5);
      const fiveDaysAgoTimestamp = Timestamp.fromDate(fiveDaysAgo);

      const q5Days = query(
        titlesRef,
        where('lastSeenAt', '>=', fiveDaysAgoTimestamp),
        orderBy('lastSeenAt', 'desc'),
        orderBy(documentId(), 'desc')
      );

      const snapshot = await getDocs(q5Days);
      items = snapshot.docs.map(mapDocToTitle);

      if (items.length > 0) {
        hasMore = true;
        const lastDoc = snapshot.docs[snapshot.docs.length - 1];
        const lastData = lastDoc.data() as DocumentData;
        nextCursor = {
          lastSeenAt: toDate(lastData['lastSeenAt']),
          id: lastDoc.id,
        };
      } else {
        // Fallback to normal pagination if there are no titles in the last 5 days
        const qNormal = query(
          titlesRef,
          orderBy('lastSeenAt', 'desc'),
          orderBy(documentId(), 'desc'),
          limit(options.pageSize)
        );
        const normalSnapshot = await getDocs(qNormal);
        items = normalSnapshot.docs.map(mapDocToTitle);
        hasMore = normalSnapshot.docs.length === options.pageSize;
        const lastDoc = normalSnapshot.docs[normalSnapshot.docs.length - 1];
        if (lastDoc && hasMore) {
          const lastData = lastDoc.data() as DocumentData;
          nextCursor = {
            lastSeenAt: toDate(lastData['lastSeenAt']),
            id: lastDoc.id,
          };
        }
      }
    } else {
      const cursorTimestamp = Timestamp.fromDate(options.cursor.lastSeenAt);
      const q = query(
        titlesRef,
        orderBy('lastSeenAt', 'desc'),
        orderBy(documentId(), 'desc'),
        startAfter(cursorTimestamp, options.cursor.id),
        limit(options.pageSize)
      );
      const snapshot = await getDocs(q);
      items = snapshot.docs.map(mapDocToTitle);
      hasMore = snapshot.docs.length === options.pageSize;
      const lastDoc = snapshot.docs[snapshot.docs.length - 1];
      if (lastDoc && hasMore) {
        const lastData = lastDoc.data() as DocumentData;
        nextCursor = {
          lastSeenAt: toDate(lastData['lastSeenAt']),
          id: lastDoc.id,
        };
      }
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
