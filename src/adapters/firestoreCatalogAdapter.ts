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

    let q;
    if (options.cursor) {
      const cursorTimestamp = Timestamp.fromDate(options.cursor.lastSeenAt);
      q = query(
        titlesRef,
        orderBy('lastSeenAt', 'desc'),
        orderBy(documentId(), 'desc'),
        startAfter(cursorTimestamp, options.cursor.id),
        limit(options.pageSize)
      );
    } else {
      q = query(
        titlesRef,
        orderBy('lastSeenAt', 'desc'),
        orderBy(documentId(), 'desc'),
        limit(options.pageSize)
      );
    }

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

  async getOccurrences(titleId: string): Promise<Occurrence[]> {
    const db = this.getDbInstance();
    const occurrencesRef = collection(db, 'titles', titleId, 'occurrences');
    const q = query(occurrencesRef, orderBy('firstSeenAt', 'desc'));
    const snapshot = await getDocs(q);

    return snapshot.docs.map(mapDocToOccurrence);
  }
}

export const firestoreCatalogAdapter = new FirestoreCatalogAdapter();
